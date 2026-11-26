#!/usr/bin/env python3.11
"""Publish: a squashed release of master (or a chosen commit) from the private repo to the public one, carefully.

    scripts/publish.py [--to COMMIT] [-m MESSAGE] [--dry-run] [--skip-tests] [--yes] [--contributions-ok]
    scripts/publish.py --bring-in        # bring pull requests merged on the public repo into this branch

Development happens in a private repo (remote `origin`). The public repo (remote `public`) gets one commit per
publish: its files are exactly those of COMMIT (default master), its parent is the current public/main, and its message
is a release note (asked for, or -m). The private history never goes public. Each publish commit ends with a
"Published-From: <private commit>" line, which is how the next publish knows what is new.

Pull requests are merged on the public repo. Before the next publish, bring them in here (`--bring-in` cherry-picks
the contributors' commits since the last publish); publishing stops while public/main has changes that are not in
what is being published, so a squash never undoes a contribution. (`--contributions-ok` after checking by hand, when
you brought them in some other way or changed those lines since.)

Checks on every file being published (any of these stops the publish):
  - secrets: the discogs token ($DISCOGS_TOKEN or ~/.config/djtools/discogs_token), searched for literally; API keys,
    tokens and private keys by their usual shapes
  - personal strings: one regular expression per line in .git/publish-patterns (local only, never published)
  - absolute home folder paths (/Users/<name>/...)
  - files that never belong: Python caches, .DS_Store, .env, config.toml, discogs_token, a library's database.json
    and lyrics sidecars (*.lyrics.json, copyrighted lyrics)
Shown for a look (not blocking): images, audio, video and other binaries, and files over 2 MB, when new or changed.

A local pre-push hook (.git/hooks/pre-push) refuses pushes to the public repo that don't come from this script.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_REMOTE = "public"
PUBLIC_BRANCH = "main"
PUBLISH_ENV = "DJTOOLS_PUBLISH"  # set only by this script; the pre-push hook checks it

SECRET_SHAPES = [
    (r"sk-ant-[A-Za-z0-9_-]{16,}", "Anthropic API key"),
    (r"\bghp_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}", "GitHub token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
    (r"\bxox[abpr]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"Bearer [A-Za-z0-9._~+/-]{24,}", "bearer token"),
]
HOME_PATH = re.compile(r"/Users/(?!Shared/)[A-Za-z0-9._-]+/")
NEVER_FILES = re.compile(
    r"(^|/)(__pycache__/|\.DS_Store$|\.env$|config\.toml$|discogs_token$|database\.json$)|\.pyc$|\.lyrics\.json$"
)
REVIEW_EXT = {".png", ".jpg", ".jpeg", ".gif", ".heic", ".webp", ".mov", ".mp4", ".m4v", ".wav", ".mp3", ".aiff",
              ".m4a", ".flac", ".pdf", ".zip", ".icns", ".moves", ".bin"}
BIG = 2 * 1024 * 1024


def git(*args: str, check: bool = True, **kw) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout


def blob_contents(blobs: list[str]) -> dict[str, bytes]:
    """Contents of the given blobs (git cat-file --batch)."""
    if not blobs:
        return {}
    p = subprocess.run(["git", "-C", str(ROOT), "cat-file", "--batch"], input="\n".join(blobs).encode() + b"\n",
                       capture_output=True, check=True)
    out, data, i = {}, p.stdout, 0
    while i < len(data):
        nl = data.index(b"\n", i)
        sha, _, size = data[i:nl].decode().split(" ")
        start = nl + 1
        out[sha] = data[start:start + int(size)]
        i = start + int(size) + 1
    return out


def local_secrets() -> list[tuple[str, str]]:
    """(value, what) for the secrets kept locally; never printed."""
    found = []
    token = os.environ.get("DISCOGS_TOKEN", "").strip()
    if not token:
        try:
            token = (Path.home() / ".config/djtools/discogs_token").read_text().strip()
        except OSError:
            pass
    if len(token) >= 8:
        found.append((token, "the discogs token"))
    return found


def personal_patterns() -> list[re.Pattern]:
    path = ROOT / ".git" / "publish-patterns"
    if not path.exists():
        return []
    pats = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pats.append(re.compile(line))
    return pats


def tree_scan(commit: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(files, lines) of a commit's tree: files = (path, blob), lines = (path, text) of every text file."""
    files = []
    for row in git("ls-tree", "-r", commit).splitlines():
        meta, path = row.split("\t", 1)
        _, kind, blob = meta.split()
        if kind == "blob":
            files.append((path, blob))
    texts = blob_contents([b for _, b in files])
    lines = []
    for path, blob in files:
        data = texts.get(blob, b"")
        if b"\0" in data[:8192]:
            continue
        for line in data.decode("utf-8", "replace").splitlines():
            lines.append((path, line))
    return files, lines


def last_publish(public_main: str) -> tuple[str | None, str | None]:
    """(public commit, private commit it was made from) of the newest publish on public/main."""
    pub = git("log", "-1", "--grep=^Published-From: ", "--format=%H", public_main).strip() or None
    if not pub:
        return None, None
    src = git("log", "-1", "--format=%(trailers:key=Published-From,valueonly)", pub).strip() or None
    return pub, src


def contributions_present(last_pub: str, public_main: str, target: str) -> bool:
    """True when the changes on public/main since the last publish are already in target's files."""
    diff = subprocess.run(["git", "-C", str(ROOT), "diff", "--binary", last_pub, public_main],
                          capture_output=True, check=True).stdout
    if not diff.strip():
        return True
    index = ROOT / ".git" / "publish-check.index"
    env = dict(os.environ, GIT_INDEX_FILE=str(index))
    try:
        subprocess.run(["git", "-C", str(ROOT), "read-tree", target], env=env, check=True, capture_output=True)
        r = subprocess.run(["git", "-C", str(ROOT), "apply", "--cached", "--reverse", "--check"], input=diff,
                           env=env, capture_output=True)
        return r.returncode == 0
    finally:
        index.unlink(missing_ok=True)


def bring_in() -> int:
    """Cherry-pick the contributors' commits on public/main since the last publish into the current branch."""
    git("fetch", "--quiet", PUBLIC_REMOTE)
    public_main = git("rev-parse", "--verify", "--quiet", f"refs/remotes/{PUBLIC_REMOTE}/{PUBLIC_BRANCH}", check=False).strip()
    if not public_main:
        print("Nothing to bring in: the public repo has no main yet.")
        return 0
    pub, _ = last_publish(public_main)
    rng = f"{pub}..{public_main}" if pub else public_main
    commits = git("rev-list", "--reverse", "--no-merges", rng).split()
    if not commits:
        print("Nothing to bring in: no contributions since the last publish.")
        return 0
    if git("status", "--porcelain", "--untracked-files=no").strip():
        sys.exit("Commit or stash your changes first (the contributions are cherry-picked onto this branch).")
    print(f"Bringing in {len(commits)} commit(s) from the public repo:")
    print(git("log", "--no-walk=unsorted", "--oneline", "--no-decorate", *commits).rstrip())
    r = subprocess.run(["git", "-C", str(ROOT), "cherry-pick", "-x", *commits])
    if r.returncode != 0:
        print("\nA conflict: resolve it, `git cherry-pick --continue`, then run this again for the rest (or "
              "`git cherry-pick --abort`).")
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--to", default="master", help="the commit whose files to publish (default master)")
    ap.add_argument("-m", "--message", help="the release note (asked for when missing)")
    ap.add_argument("--dry-run", action="store_true", help="show and check, never push")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--yes", action="store_true", help="don't ask (needs -m; still stops on any problem)")
    ap.add_argument("--contributions-ok", action="store_true",
                    help="publish although public/main's changes since the last publish don't apply here unchanged")
    ap.add_argument("--bring-in", action="store_true", help="cherry-pick contributions from the public repo, then stop")
    a = ap.parse_args()

    if PUBLIC_REMOTE not in git("remote").split():
        if not a.dry_run or a.bring_in:
            sys.exit(f"No '{PUBLIC_REMOTE}' remote (git remote add {PUBLIC_REMOTE} URL).")
        print(f"note: no '{PUBLIC_REMOTE}' remote yet; checking as a first publish")
    if a.bring_in:
        return bring_in()
    if a.yes and not a.message and not a.dry_run:
        sys.exit("--yes needs -m MESSAGE.")
    git("fetch", "--quiet", PUBLIC_REMOTE, check=False)
    target = git("rev-parse", "--verify", f"{a.to}^{{commit}}").strip()
    public_main = git("rev-parse", "--verify", "--quiet", f"refs/remotes/{PUBLIC_REMOTE}/{PUBLIC_BRANCH}", check=False).strip()
    public_main = public_main or None
    last_pub, last_src = last_publish(public_main) if public_main else (None, None)

    if public_main and git("rev-parse", f"{public_main}^{{tree}}").strip() == git("rev-parse", f"{target}^{{tree}}").strip():
        print("Nothing to publish: the public repo already has exactly these files.")
        return 0
    if public_main and last_pub and not a.contributions_ok and not contributions_present(last_pub, public_main, target):
        print("Stopped: the public repo has changes since the last publish that are not in what you're publishing")
        print("(a merged pull request?). Bring them in first:  scripts/publish.py --bring-in")
        print(git("log", "--oneline", "--no-decorate", f"{last_pub}..{public_main}").rstrip())
        return 1
    if public_main and not last_pub and not a.contributions_ok:
        sys.exit("public/main has no publish commit (no Published-From line): check it by hand, then --contributions-ok.")

    # What's new: private commits since the last publish (to help write the note), files changed on the public side.
    if last_src and git("cat-file", "-t", last_src, check=False).strip() == "commit":
        commits = git("log", "--oneline", "--no-decorate", f"{last_src}..{target}").splitlines()
    elif public_main:
        commits = []
    else:
        commits = git("log", "--oneline", "--no-decorate", target).splitlines()
    if public_main:
        print(f"Publishing the files of {target[:7]} as one commit on top of {PUBLIC_REMOTE}/main.")
        if commits:
            print(f"Private commits since the last publish ({len(commits)}):")
            for c in commits[:40]:
                print("   ", c[:110])
            if len(commits) > 40:
                print(f"    ... and {len(commits) - 40} more")
        print()
        print(git("diff", "--stat=110", public_main, target).rstrip())
    else:
        print(f"First publish: the files of {target[:7]} as the public repo's first commit "
              f"(none of the {len(commits)} private commits go public).")

    files, lines = tree_scan(target)
    changed = None
    if public_main:
        changed = set(git("diff", "--name-only", "--no-renames", public_main, target).splitlines())
    problems: list[str] = []
    review: list[str] = []

    def hit(kind: str, path: str, detail: str = "") -> None:
        problems.append(f"{kind}: {path}" + (f": {detail}" if detail else ""))

    secrets = local_secrets()
    shapes = [(re.compile(r), what) for r, what in SECRET_SHAPES]
    pats = personal_patterns()
    for path, text in lines:
        for value, what in secrets:
            if value in text:
                hit("secret", path, what)
        for rx, what in shapes:
            if rx.search(text):
                hit("secret", path, what)
        home = HOME_PATH.search(text)
        if home:
            hit("home path", path, home.group(0) + "...")
        for rx in pats:
            if rx.search(text):
                hit("personal", path, f"matches /{rx.pattern}/")

    for path, blob in files:
        if NEVER_FILES.search(path):
            hit("file", path, "never published")
        if changed is not None and path not in changed:
            continue
        size = int(git("cat-file", "-s", blob).strip())
        if Path(path).suffix.lower() in REVIEW_EXT or size > BIG:
            review.append(f"{path} ({size / 1024:.0f} KB)")

    print()
    if not pats:
        print("note: no .git/publish-patterns; only the built-in checks ran")
    if review:
        print("Have a look at these (binary or large):")
        for r in sorted(set(review))[:30]:
            print("   ", r)
    if problems:
        print(f"\nStopped: {len(problems)} problem(s). Fix them in a new commit, then publish again:")
        for p in sorted(set(problems))[:60]:
            print("   ", p)
        return 1
    print(f"Checks passed ({len(lines)} line(s), {len(files)} file(s) scanned).")

    if not a.skip_tests:
        head = git("rev-parse", "HEAD").strip()
        dirty = git("status", "--porcelain", "--untracked-files=no").strip()
        if head != target or dirty:
            print("note: tests skipped (they run on the working tree, which isn't exactly the commit being published)")
        else:
            print("Testing...")
            for cmd in ([sys.executable, "-m", "pytest", "-q"], [sys.executable, "-m", "ruff", "check", "."]):
                r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
                if r.returncode != 0:
                    print((r.stdout + r.stderr)[-3000:])
                    print("Stopped: tests or lint failed.")
                    return 1
            print("Tests passed.")

    if a.dry_run:
        print("Dry run: nothing pushed.")
        return 0
    message = a.message
    if not message:
        print("\nRelease note for the public commit (first line a short summary; an empty line ends it):")
        rows = []
        while True:
            row = input("> " if not rows else "  ")
            if not row.strip():
                break
            rows.append(row)
        message = "\n".join(rows).strip()
        if not message:
            print("Not published (no release note).")
            return 1
    if not a.yes:
        answer = input("Publish to the public repo? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Not published.")
            return 1
    tree = git("rev-parse", f"{target}^{{tree}}").strip()
    body = message.rstrip() + f"\n\nPublished-From: {target}\n"
    parents = ["-p", public_main] if public_main else []
    commit = subprocess.run(["git", "-C", str(ROOT), "commit-tree", tree, *parents, "-F", "-"], input=body,
                            capture_output=True, text=True, check=True).stdout.strip()
    env = dict(os.environ, **{PUBLISH_ENV: "1"})
    r = subprocess.run(["git", "-C", str(ROOT), "push", PUBLIC_REMOTE, f"{commit}:refs/heads/{PUBLIC_BRANCH}"], env=env)
    if r.returncode == 0:
        git("fetch", "--quiet", PUBLIC_REMOTE, check=False)
        print(f"Published {commit[:7]}.")
    return r.returncode

if __name__ == "__main__":
    sys.exit(main())
