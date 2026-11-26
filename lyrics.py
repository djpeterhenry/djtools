#!/usr/bin/env python3.11
"""Word-timed lyrics for songs, shown as karaoke by reforce.

A song's lyrics live in a sidecar beside the exported samples rekordbox plays:

    <LocalSamples>/Lyrics/<song stem>.lyrics.json

with an index.json in that folder that reforce reads to find the sidecar for the
title / artist rkbx_link reports.  They sit in a subfolder because
purge_incompatible_samples probes (and may delete) every file in LocalSamples.

Times are seconds in the exported sample (the file at rekordbox's Location),
which is the position rkbx_link sends: rekordbox plays that file unwarped (the
Ableton warp markers only shape its beatgrid).  The sample's sha1 is stored so a
re-export that changes the audio (a new conversion, silence added) shows up as
stale; `realign` then times the reviewed text again on the new file.

Run from the songs folder (where database.json lives):

    python3.11 lyrics.py add "Clarity (Acapella)"      # lyrics from LRCLIB, align
    python3.11 lyrics.py add "Some Song" --lyrics-file lyrics.txt
    python3.11 lyrics.py realign "Clarity (Acapella)"  # keep the text, time it again
    python3.11 lyrics.py check                         # stale / missing samples
    python3.11 lyrics.py index                         # rebuild index.json

The review / correction page is lyrics_server.py.

The machine learning (vocal separation, Whisper, forced alignment) is in
lyrics_align.py and loaded only when needed.
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterable

from unidecode import unidecode

import ableton_aid as aa
from export_rekordbox import REKORDBOX_LOCAL_SAMPLE_PATH

LYRICS_DIR = os.path.join(REKORDBOX_LOCAL_SAMPLE_PATH, "Lyrics")
INDEX_NAME = "index.json"
SUFFIX = ".lyrics.json"
FORMAT_VERSION = 1

LRCLIB = "https://lrclib.net/api"
USER_AGENT = "djtools-lyrics"

# Lyrics (one per line) -> a sidecar's lines; see build_lines.
Line = dict[str, Any]
Sidecar = dict[str, Any]


# ---------------------------------------------------------------- files

def lyrics_dir() -> str:
    return os.environ.get("DJTOOLS_LYRICS_DIR", LYRICS_DIR)


def sidecar_path(song: str) -> str:
    """The sidecar of a database song ("Artist - Track.als")."""
    return os.path.join(lyrics_dir(), os.path.splitext(song)[0] + SUFFIX)


def file_sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json_atomic(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def read_sidecar(path: str) -> Sidecar:
    with open(path, encoding="utf8") as f:
        return json.load(f)


def list_sidecars() -> list[str]:
    d = lyrics_dir()
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, n) for n in os.listdir(d) if n.endswith(SUFFIX) and not n.startswith("."))


def save_sidecar(sidecar: Sidecar, path: str | None = None) -> str:
    """Write a sidecar (stamped modified) and refresh the index."""
    path = path or sidecar_path(sidecar["song"])
    sidecar["modified"] = time.time()
    write_json_atomic(path, sidecar)
    write_index()
    return path


def write_index() -> dict[str, Any]:
    """index.json: what reforce needs to find a deck's sidecar.

    Keyed by the title and artist the rekordbox export gives the track (see
    export_rekordbox_xml: aa.get_artist_and_track), which is what rkbx_link
    reports (before the tag padding)."""
    songs = []
    for path in list_sidecars():
        try:
            s = read_sidecar(path)
        except (OSError, ValueError) as e:
            print("Skipping unreadable {}: {}".format(os.path.basename(path), e))
            continue
        songs.append({
            "artist": s.get("artist", ""),
            "title": s.get("title", ""),
            "file": os.path.basename(path),
            "reviewed": bool(s.get("reviewed")),
        })
    index = {"version": FORMAT_VERSION, "songs": songs}
    write_json_atomic(os.path.join(lyrics_dir(), INDEX_NAME), index)
    return index


def sidecar_status(s: Sidecar) -> str:
    """"missing" (no sample), "stale" (the sample changed since it was timed) or "ok"."""
    sample = s.get("sample", "")
    if not sample or not os.path.isfile(sample):
        return "missing"
    if os.path.getsize(sample) != s.get("sample_size") or file_sha1(sample) != s.get("sample_sha1"):
        return "stale"
    return "ok"


# ---------------------------------------------------------------- songs

def find_songs(db_dict: dict[str, Any], query: str) -> list[str]:
    """Database songs whose name contains every word of query (case-insensitive), exact names first."""
    q = query.lower().strip()
    words = q.split()
    hits = [f for f in db_dict if all(w in f.lower() for w in words)]
    hits.sort(key=lambda f: (os.path.splitext(f)[0].lower() != q, len(f), f.lower()))
    return hits


def song_sample(db_dict: dict[str, Any], song: str) -> str:
    sample = aa.get_existing_rekordbox_sample(db_dict[song])
    if sample is None:
        raise SystemExit("No exported sample for {} (export to rekordbox first)".format(song))
    return sample


_NO_SEPARATE = re.compile(r"acap+ell?a|a cap+ell?a|\bvocals?\b|\bvox\b", re.I)


def is_vocal_only(song: str, tags: Iterable[str] = ()) -> bool:
    """Acapellas and vocal loops are aligned as they are (no vocal separation): tagged "vocal" (in this library those are
    all acapellas), or named like one."""
    return "vocal" in tags or bool(_NO_SEPARATE.search(os.path.splitext(song)[0]))


_PARENS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")


def search_terms(song: str) -> tuple[str, str]:
    """(artist, title) to look a song's lyrics up by: the artist as named, the title without (Remix) / [Edit] parts."""
    artist, title = aa.get_artist_and_track(song)
    title = _PARENS.sub("", title).strip() or title
    return artist, title


def main_artist(artist: str) -> str:
    """The first of several artists ("Zedd & Foxes" -> "Zedd"); a name with "&" in it stays whole only by luck,
    so this is the fallback search, after the artist as named ("Above & Beyond")."""
    return re.split(r"\s*(?:&|,| feat\.? | ft\.? | x | vs\.? )\s*", artist, flags=re.I)[0].strip() or artist


# ---------------------------------------------------------------- LRCLIB

def _get_json(url: str, retries: int = 5) -> Any:
    """GET JSON, waiting and trying again when LRCLIB says too many requests (429) or is briefly down (5xx)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if attempt == retries or not (e.code == 429 or e.code >= 500):
                raise
            wait = e.headers.get("Retry-After") if e.headers else None
            time.sleep(float(wait) if wait and wait.isdigit() else 2.0 * 2 ** attempt)
    raise AssertionError("unreachable")


def lrclib_search(artist: str, title: str) -> list[dict[str, Any]]:
    """LRCLIB results with lyrics, best first (artist and title match, then synced, then most common text)."""
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    queries = [{"track_name": title, "artist_name": artist}]
    if main_artist(artist) != artist:
        queries.append({"track_name": title, "artist_name": main_artist(artist)})
    queries.append({"q": "{} {}".format(main_artist(artist), title)})
    for params in queries:
        try:
            got = _get_json(LRCLIB + "/search?" + urllib.parse.urlencode(params))
        except OSError as e:
            print("LRCLIB search failed: {}".format(e))
            continue
        for r in got:
            if r.get("id") in seen or r.get("instrumental") or not (r.get("plainLyrics") or r.get("syncedLyrics")):
                continue
            seen.add(r["id"])
            results.append(r)
        if results:
            break

    results = [r for r in results if lrclib_matches(r, artist, title)]

    def sim(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

    counts: dict[str, int] = {}
    for r in results:
        key = " ".join(norm_words(lyrics_text(r)))
        counts[key] = counts.get(key, 0) + 1
    results.sort(key=lambda r: (
        -round(sim(r.get("trackName", ""), title) + sim(r.get("artistName", ""), artist), 1),
        -counts[" ".join(norm_words(lyrics_text(r)))],
        not r.get("syncedLyrics"),
    ))
    return results


def lrclib_matches(r: dict[str, Any], artist: str, title: str) -> bool:
    """Whether an LRCLIB result is this song at all: the title alike and one of the artists named.

    The free-text fallback search returns anything with the words ("Pretty Pink - Echo" found Echo & the
    Bunnymen); spellings vary ("Kidnap Kid", "HAYLA; Kaskade; Kx5", "Four to floor 03 (Extended Mix)")."""
    def letters(x: str) -> str:
        return "".join(norm_words(x))

    want, got = letters(" ".join(bare_title(title))), letters(" ".join(bare_title(r.get("trackName", ""))))
    title_ok = bool(want) and (want in got or got in want and len(got) >= 3
                               or difflib.SequenceMatcher(None, want, got).ratio() >= 0.6)
    names = [letters(a) for a in re.split(r"\s*(?:&|,|;| feat\.? | ft\.? | x | vs\.? | and )\s*", artist, flags=re.I)]
    theirs = letters(r.get("artistName", ""))
    artist_ok = any(n and (n in theirs or theirs and theirs in n) for n in names)
    return title_ok and artist_ok


def lyrics_text(r: dict[str, Any]) -> str:
    """An LRCLIB result's lyrics as plain lines (synced lyrics without their time stamps)."""
    if r.get("plainLyrics"):
        return r["plainLyrics"]
    return "\n".join(re.sub(r"^\[[^\]]*\]\s*", "", l) for l in (r.get("syncedLyrics") or "").splitlines())


def lrclib_source(r: dict[str, Any]) -> dict[str, Any]:
    """The sidecar's `source` for lyrics taken from an LRCLIB result (what matched, for the review page)."""
    return {"lyrics": "lrclib:{}".format(r["id"]), "lrclib": {
        "artist": r.get("artistName", ""), "track": r.get("trackName", ""), "album": r.get("albumName", ""),
        "duration": r.get("duration", 0), "synced": bool(r.get("syncedLyrics"))}}


def lrclib_get(lrclib_id: int) -> dict[str, Any]:
    return _get_json("{}/get/{}".format(LRCLIB, int(lrclib_id)))


def bare_title(title: str) -> list[str]:
    """A title's words without a featured artist or a version that keeps the words
    ("Disarm You (feat. Ilsey)", "Wondering - Radio Edit" = the bare title)."""
    title = re.sub(r"(?:\s+-\s+|\s*[(\[])\s*(?:radio edit|original mix|extended mix|extended|album version|single version|"
                   r"(?:\d{4} )?remaster(?:ed)?(?: \d{4})?)\s*[)\]]?", "", title, flags=re.I)
    return norm_words(re.sub(r"[(\[]\s*(?:feat|ft|featuring|with)\b[^)\]]*[)\]]|\s(?:feat|ft)\.?\s.*$", "", title, flags=re.I))


def _same_line(a: dict[str, Any], b: dict[str, Any], tol: float = 0.03) -> bool:
    """Same text and word timing (within the rounding the review server applies)."""
    wa, wb = a.get("words", []), b.get("words", [])
    return a["text"] == b["text"] and len(wa) == len(wb) and all(
        x["text"] == y["text"] and abs(x["t0"] - y["t0"]) <= tol and abs(x["t1"] - y["t1"]) <= tol
        for x, y in zip(wa, wb))


def _overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["t0"] < b["t1"] and b["t0"] < a["t1"]


def mark_hand_edits(old_lines: list[dict[str, Any]], new_lines: list[dict[str, Any]],
                    removed: list[dict[str, Any]]) -> None:
    """A save from the review page: lines a person changed (text or timing) or added get
    "edited": True, and automatic lines they deleted or replaced go into `removed`, so a
    later rebuild keeps the person's lines and does not bring the wrong ones back. An edit
    is not acceptance: the rest of the song still takes automatic improvements until the
    song is marked reviewed."""
    for l in new_lines:
        o = next((o for o in old_lines if _same_line(o, l)), None)
        if o is None or o.get("edited"):
            l["edited"] = True
        else:
            l.pop("edited", None)
    for o in old_lines:
        if not o.get("edited") and not any(_same_line(o, l) for l in new_lines):
            removed.append({"t0": o["t0"], "t1": o["t1"], "text": o["text"]})


def merge_rebuilt(current: list[dict[str, Any]], rebuilt: list[dict[str, Any]],
                  removed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An automatic rebuild of a song a person has partly edited: their lines stay, and
    rebuilt lines fill the rest, except where they overlap a person's line or are a line
    the person deleted (same words at an overlapping time)."""
    mine = [l for l in current if l.get("edited")]
    out = list(mine)
    for l in rebuilt:
        if any(_overlaps(l, m) for m in mine):
            continue
        if any(norm_words(r["text"]) == norm_words(l["text"]) and _overlaps(l, r) for r in removed):
            continue
        out.append({k: v for k, v in l.items() if k != "edited"})
    return sorted(out, key=lambda l: l["t0"])


def keep_hand_edits(old: Sidecar, new: Sidecar) -> Sidecar:
    """`new`, a rebuild of a song that already had lyrics (`old`), with the person's work
    carried over: their edited lines (merge_rebuilt), the lines they deleted (still left
    out next time), the song's offset and when it was first made."""
    new["lines"] = merge_rebuilt(old.get("lines", []), new["lines"], old.get("removed", []))
    if old.get("removed"):
        new["removed"] = old["removed"]
    for key in ("offset", "created"):
        if key in old:
            new[key] = old[key]
    return new


def describe_source(sidecar: Sidecar) -> dict[str, Any]:
    """Where a sidecar's text came from, for the review page.

    kind: "lrclib" (looked up), "whisper" (no lyrics found: Whisper's own
    hearing, the least trustworthy), "manual" (pasted or edited text), "file".
    other_version: the LRCLIB match's title differs from the song's (a
    remix or edit whose words may differ)."""
    src = sidecar.get("source", {}) or {}
    what = str(src.get("lyrics", ""))
    if what.startswith("lrclib:"):
        m = src.get("lrclib") or {}
        _, title = search_terms(sidecar.get("song", ""))
        label = "LRCLIB #{}".format(what.split(":", 1)[1])
        if m:
            label += ": {} \u2013 {}".format(m.get("artist", ""), m.get("track", ""))
            if m.get("album"):
                label += " \u00b7 album: {}".format(m["album"])
        other = bool(m) and bare_title(m.get("track", "")) != bare_title(title)
        return {"kind": "lrclib", "label": label, "other_version": other}
    if what in ("none", "") and not sidecar.get("reference"):
        return {"kind": "whisper", "label": "No lyrics found: Whisper's own hearing (check every word)",
                "other_version": False}
    if what == "file":
        return {"kind": "file", "label": "Lyrics from a file", "other_version": False}
    return {"kind": "manual", "label": "Lyrics typed or pasted in this page", "other_version": False}


# ---------------------------------------------------------------- text

def norm_words(s: str) -> list[str]:
    """Lowercase words for matching ("’" folded to "'", punctuation dropped)."""
    s = unidecode(s.replace("’", "'")).lower()
    s = re.sub(r"in'(?=\s|$)", "ing", s)
    return [w.strip("'") for w in re.sub(r"[^a-z0-9' ]", " ", s).split() if w.strip("'")]


def guess_language(text: str | None) -> str | None:
    """"en" for lyrics written in plain Latin letters with common English words; else None (Whisper detects it).
    Telling Whisper stops it hallucinating other scripts over the instrumental parts."""
    if not text:
        return None
    words = norm_words(text)
    if not words:
        return None
    letters = [c for c in text if c.isalpha()]
    ascii_share = sum(c.isascii() for c in letters) / max(1, len(letters))
    common = {"the", "you", "i", "and", "to", "a", "me", "my", "it", "in", "we", "your", "of", "is", "on", "love"}
    share = sum(w in common for w in words) / len(words)
    return "en" if ascii_share > 0.95 and share > 0.12 else None


def lyric_lines(text: str) -> list[str]:
    """Reference lyrics as display lines: blank lines and section labels ("[Chorus]") dropped."""
    out = []
    for l in text.splitlines():
        l = re.sub(r"^\[[^\]]*\]\s*", "", l.strip()).strip()
        if l and not re.fullmatch(r"\(?(?:x\d+|\d+x)\)?", l, re.I):
            out.append(" ".join(l.split()))
    return out


def lyric_units(lines: list[str]) -> list[list[str]]:
    """What one Whisper segment may be: a lyric line, two lines in a row, or a part of a line split at a comma.
    Each unit is the list of display lines it covers.  Duplicates (by words) are kept once."""
    units: list[list[str]] = [[l] for l in lines]
    units += [[a, b] for a, b in zip(lines, lines[1:])]
    for l in lines:
        parts = [p.strip() for p in re.split(r",\s*", l)]
        if len(parts) > 1:
            for p in parts:
                if len(norm_words(p)) >= 2:
                    units.append([p[0].upper() + p[1:]])
    seen: dict[str, list[str]] = {}
    for u in units:
        seen.setdefault(" ".join(norm_words(" ".join(u))), u)
    return list(seen.values())


def whisper_segment_ok(seg: dict[str, Any]) -> bool:
    """False for Whisper's duplicated / hallucinated segments: most words without any length."""
    words = seg.get("words") or []
    if not words:
        return bool(seg.get("text", "").strip())
    zero = sum(1 for w in words if w["end"] - w["start"] < 0.02)
    return zero < len(words) / 2


# What Whisper says over silence and music; never matched to a lyric by sound alone.
WHISPER_FILLERS = {"thank you", "thank you very much", "thanks for watching", "thank you for watching", "i'm sorry",
                   "the end", "oh god", "for you", "you", "bye", "okay", "so"}


# Whisper's credits and sign-offs from subtitled video ("Closed Captioning by ...", "ご視聴ありがとうございました").
WHISPER_CREDITS = re.compile(r"caption|subtitle|www\.|\.(?:com|org|net)\b|for watching|ご視聴|ありがとうございました", re.I)


def is_whisper_filler(text: str) -> bool:
    """What Whisper writes over music and silence rather than anything sung."""
    return " ".join(norm_words(text)) in WHISPER_FILLERS or bool(WHISPER_CREDITS.search(text))


def mostly_other_script(texts: Iterable[str]) -> bool:
    letters = [c for t in texts for c in t if c.isalpha()]
    return bool(letters) and sum(not c.isascii() for c in letters) > len(letters) / 2


def word_similarity(heard: list[str], lyric: list[str]) -> float:
    return difflib.SequenceMatcher(None, heard, lyric).ratio()


def sound_similarity(heard: list[str], lyric: list[str]) -> float:
    """How alike by sound: the letters without spaces, less 0.16 (so it reads on the words' scale).

    Processed vocals are misheard into other words that sound the same ("This is how to rest" for "This is house
    arrest", "Teantropan fire" for "Teardrop on the fire"): on the 121 songs of 2026-11-24, letter matches of .66
    and up were right, and "Thank you." against lyrics sat at .62.  Only for what matches no lyric by words: as a
    second score for every segment it made near-ties that the audio then broke wrongly ("Come and hold me baby"
    chose "Come catch me babe" over "And come hold me babe")."""
    if " ".join(heard) in WHISPER_FILLERS:
        return 0.0
    return difflib.SequenceMatcher(None, "".join(heard), "".join(lyric)).ratio() - 0.16


def choose_unit(
    seg_text: str,
    units: list[list[str]],
    audio_score: Callable[[list[str]], float] | None = None,
    by_sound: bool = True,
) -> tuple[list[str] | None, list[tuple[float, list[str]]]]:
    """The lyric unit a Whisper segment sings.

    By text similarity to what Whisper heard; among close candidates of about the
    same length the audio decides (audio_score: higher = fits the sound better).
    Only similar lengths are compared by audio because forced alignment explains
    a missing phrase as silence almost for free.  Returns (unit or None, the
    candidates with their scores)."""
    wn = norm_words(seg_text)
    if not wn:
        return None, []
    sim = word_similarity
    if by_sound and max((word_similarity(wn, norm_words(" ".join(u))) for u in units), default=0.0) < 0.5:
        sim = sound_similarity
    scored = sorted(((sim(wn, norm_words(" ".join(u))), u) for u in units), key=lambda x: -x[0])
    # 0.5: heavily processed vocals are badly misheard ("All I need is a true body" for "... that you believe", 0.57);
    # on the top 50 of Top (SF) every line 0.5 added was right, and Whisper's made-up lines stay well below it.
    if not scored or scored[0][0] < 0.5:
        return None, []
    best = scored[0][0]
    cands = [u for r, u in scored
             if r >= 0.5 and (r >= best - 0.03 or (r >= best - 0.2 and abs(len(norm_words(" ".join(u))) - len(wn)) <= 1))]
    cands = cands[:6]
    if len(cands) == 1 or audio_score is None:
        return cands[0], [(best, cands[0])]
    by_audio = sorted(((audio_score(u), u) for u in cands), key=lambda x: -x[0])
    return by_audio[0][1], by_audio


# ---------------------------------------------------------------- aligning

Aligner = Any  # lyrics_align.Aligner (duck typed so tests can fake it)


def split_words(line: str) -> list[str]:
    return line.split()


def fill_untimed(words: list[dict[str, Any]], t0: float, t1: float) -> None:
    """Words the aligner could not time (no letters, e.g. "24/7"): spread between their timed neighbors."""
    n = len(words)
    i = 0
    while i < n:
        if words[i].get("t0") is not None:
            i += 1
            continue
        j = i
        while j < n and words[j].get("t0") is None:
            j += 1
        a = words[i - 1]["t1"] if i > 0 else t0
        b = words[j]["t0"] if j < n else t1
        step = max(0.0, b - a) / (j - i)
        for k in range(i, j):
            words[k]["t0"] = round(a + step * (k - i), 3)
            words[k]["t1"] = round(a + step * (k - i + 1), 3)
            words[k]["score"] = 0.0
        i = j


def timed_line(text: str, words: list[dict[str, Any]], **extra: Any) -> Line:
    line = {"t0": words[0]["t0"], "t1": words[-1]["t1"], "text": text, "words": words}
    line.update(extra)
    return line


def align_unit(aligner: Aligner, unit: list[str], a: float, b: float) -> list[Line]:
    """Time the display lines of a unit inside [a, b]; one line per display line."""
    flat = [w for l in unit for w in split_words(l)]
    words = aligner.align_words(flat, a, b)
    fill_untimed(words, a, b)
    out, k = [], 0
    for l in unit:
        n = len(split_words(l))
        out.append(timed_line(l, words[k:k + n]))
        k += n
    return out


def token_word(w: str) -> str:
    """A word as MMS_FA's alphabet spells it: romanized, lowercase a-z and '."""
    return re.sub(r"[^a-z']", "", unidecode(w.replace("\u2019", "'")).lower())


def dragged(lines: list[Line]) -> bool:
    """A word pulled away from the rest: over 1.5 s of silence inside a line, or one word over 3 s (held notes
    are shorter; forced alignment drags a first word back across what was sung before)."""
    words = [w for l in lines for w in l["words"]]
    return any(b["t0"] - a["t1"] > 1.5 for l in lines for a, b in zip(l["words"], l["words"][1:])) or \
        any(w["t1"] - w["t0"] > 3.0 for w in words)


def build_lines(
    segments: list[dict[str, Any]],
    reference: str | None,
    aligner: Aligner,
    duration: float,
    log: Callable[[str], None] = print,
) -> list[Line]:
    """Whisper segments -> timed display lines.

    With reference lyrics: each segment becomes the lyric unit it sings (spelling
    from the lyrics, the song's own structure and repeats from Whisper); a
    segment that matches no lyric line is dropped (Whisper's "Thank you." on
    silence).  Without: Whisper's own text.  Then forced alignment times every
    word inside the segment (padded 0.6 s)."""
    units = lyric_units(lyric_lines(reference)) if reference else []
    segs = [seg for seg in segments if seg.get("text", "").strip()]
    latin = not mostly_other_script(seg["text"] for seg in segs)   # then a segment in another script is made up
    lines: list[Line] = []
    i = 0
    while i < len(segs):
        seg = segs[i]
        i += 1
        text = seg["text"].strip()
        start, end = seg["start"], seg["end"]
        pad = 0.6
        if not whisper_segment_ok(seg):
            # words without length but the right text ("Love will tear us apart again"): look around it more widely
            if not units or choose_unit(text, units)[0] is None or len(norm_words(text)) < 2:
                log("{:7.2f} drop (Whisper duplicate): {}".format(start, text))
                continue
            pad = 1.5
        if units:
            def pick(t: str, a: float, b: float, by_sound: bool = True) -> tuple[list[str] | None,
                                                                                  list[tuple[float, list[str]]]]:
                return choose_unit(t, units, lambda u: aligner.path_score(" ".join(u).split(), a, b), by_sound)

            a, b = max(0.0, start - pad), min(duration, end + pad)
            unit, cands = pick(text, a, b)
            if unit is None and i < len(segs) and segs[i]["start"] - end < 3.0 and whisper_segment_ok(segs[i]):
                # Whisper often splits one lyric line in two: try it with the next segment.
                nxt = segs[i]
                both = text + " " + nxt["text"].strip()
                b2 = min(duration, nxt["end"] + 0.6)
                unit, cands = pick(both, a, b2, by_sound=False)   # by sound, a part can match anything
                u_words = norm_words(" ".join(unit or []))
                if unit is not None and (word_similarity(norm_words(nxt["text"]), u_words)
                                         >= word_similarity(norm_words(both), u_words)) \
                        and dragged(align_unit(aligner, unit, a, b2)):
                    # the next segment alone is that line ("When they're over" + "All I know") and timed over both
                    # a word is dragged back over this one's audio ("All" held 5 s before "I know"): leave it alone
                    unit, cands = None, []
                if unit is not None:
                    i += 1
                    text, end, b = both, nxt["end"], b2
            if unit is None:
                log("{:7.2f} drop (not in the lyrics): {}".format(start, text))
                continue
            got = align_unit(aligner, unit, a, b)
            if len(cands) > 1:
                for l in got:
                    l["note"] = "chosen by audio from {} candidates".format(len(cands))
        else:
            if not norm_words(text) or is_whisper_filler(text) or (latin and mostly_other_script([text])):
                if norm_words(text):
                    log("{:7.2f} drop (what Whisper says over music): {}".format(start, text))
                continue
            got = align_unit(aligner, [text], max(0.0, start - 0.6), min(duration, end + 0.6))
            for l in got:
                l["note"] = "Whisper's text (no lyrics)"
        lines.extend(got)
    lines.sort(key=lambda l: l["t0"])
    lines = drop_overlaps(lines, log)
    for l in lines:
        log("{:7.2f} {}".format(l["t0"], l["text"]))
    return lines


def line_score(l: Line) -> float:
    ws = l["words"]
    return sum(w.get("score", 0.0) for w in ws) / max(1, len(ws))


def drop_overlaps(lines: list[Line], log: Callable[[str], None] = print, tol: float = 0.25) -> list[Line]:
    """Lines that overlap in time.  The same words claimed twice (two Whisper segments for one sung line): the one
    the audio fits worse goes.  Different words: the earlier line ends where the next begins (the aligner stretches
    a line's last word into the gap after it)."""
    out: list[Line] = []
    for l in lines:
        if out and l["t0"] < out[-1]["t1"] - tol:
            prev = out[-1]
            same = difflib.SequenceMatcher(None, norm_words(prev["text"]), norm_words(l["text"])).ratio() >= 0.6
            if same:
                keep, lose = (prev, l) if line_score(prev) >= line_score(l) else (l, prev)
                log("{:7.2f} drop (overlaps {:.2f} {!r}): {}".format(lose["t0"], keep["t0"], keep["text"], lose["text"]))
                out[-1] = keep
                continue
        if out and l["t0"] < out[-1]["t1"]:
            trim_end(out[-1], l["t0"])
        out.append(l)
    return out


def trim_end(line: Line, t: float) -> None:
    """Line ends by t: words past it squeezed in before it."""
    for w in line["words"]:
        if w["t1"] > t:
            w["t1"] = round(max(w["t0"] + 0.02, t), 3)
        if w["t0"] > w["t1"] - 0.02:
            w["t0"] = round(w["t1"] - 0.02, 3)
    line["t1"] = line["words"][-1]["t1"]


def realign_line(aligner: Aligner, line: Line, text: str, a: float, b: float) -> Line:
    """One line timed again (new text, or the same text in a new window)."""
    got = align_unit(aligner, [" ".join(text.split())], a, b)[0]
    return got


def line_window(lines: list[Line], i: int, duration: float, pad: float = 1.0) -> tuple[float, float]:
    """Where line i may move when it is timed again: its span padded, but not into its neighbors."""
    l = lines[i]
    a = max(0.0, l["t0"] - pad)
    b = min(duration, l["t1"] + pad)
    if i > 0:
        a = max(a, lines[i - 1]["t1"] - 0.05)
    if i + 1 < len(lines):
        b = min(b, lines[i + 1]["t0"] + 0.05)
    if b - a < 0.3:
        a, b = max(0.0, l["t0"] - 0.15), min(duration, l["t1"] + 0.15)
    return a, b


# ---------------------------------------------------------------- whole songs

def new_sidecar(song: str, sample: str, duration: float, lines: list[Line], reference: str | None,
                source: dict[str, Any]) -> Sidecar:
    artist, title = aa.get_artist_and_track(song)
    now = time.time()
    return {
        "version": FORMAT_VERSION,
        "song": song,
        "artist": artist,
        "title": title,
        "sample": sample,
        "sample_sha1": file_sha1(sample),
        "sample_size": os.path.getsize(sample),
        "duration": round(duration, 3),
        "offset": 0.0,
        "reviewed": False,
        "created": now,
        "modified": now,
        "source": source,
        "reference": reference or "",
        "lines": lines,
    }


def create(song: str, sample: str, reference: str | None, source: dict[str, Any],
           separate: bool | None = None, log: Callable[[str], None] = print, tags: Iterable[str] = ()) -> Sidecar:
    """Separate (unless an acapella), transcribe, choose lyric lines and align: a new sidecar (not saved)."""
    import lyrics_align as la

    if separate is None:
        separate = not is_vocal_only(song, tags)
    log("Vocals: {}".format("separating (demucs)" if separate else "the sample as it is"))
    audio = la.vocals_path(sample) if separate else la.timeline_path(sample)
    language = guess_language(reference)
    log("Transcribing (Whisper{})...".format(", " + language if language else ""))
    segments = la.transcribe(audio, language)
    if language is None and not reference and song.isascii() and mostly_other_script(g["text"] for g in segments):
        # no lyrics to tell the language, and Whisper heard Japanese in an English-named song (its sign-offs
        # over the instrumental): English
        log("Whisper heard another script; transcribing as English")
        segments = la.transcribe(audio, "en")
    aligner = la.Aligner(audio)
    log("Aligning ({} segments)...".format(len(segments)))
    lines = build_lines(segments, reference, aligner, aligner.duration, log=log)
    source = dict(source, separated=separate, whisper=la.WHISPER_MODEL, aligner="torchaudio MMS_FA",
                  timeline_shift=round(la.sample_shift(sample), 4))
    return new_sidecar(song, sample, aligner.duration, lines, reference, source)


def realign_sidecar(s: Sidecar, log: Callable[[str], None] = print) -> Sidecar:
    """Every line timed again on the current sample, keeping the (reviewed) text and line order.

    For a re-exported sample: the windows are the old times shifted by how far
    the audio moved (cross-correlation of the old and new files' starts is not
    kept, so this searches each line padded by 2 s)."""
    import lyrics_align as la

    sample = s["sample"]
    audio = la.vocals_path(sample) if s.get("source", {}).get("separated") else la.timeline_path(sample)
    aligner = la.Aligner(audio)
    lines = s["lines"]
    out = []
    for i, l in enumerate(lines):
        a, b = line_window(lines, i, aligner.duration, pad=2.0)
        nl = realign_line(aligner, l, l["text"], a, b)
        if l.get("edited"):  # still the person's line, now on the new sample
            nl["edited"] = True
        log("{:7.2f} -> {:7.2f} {}".format(l["t0"], nl["t0"], l["text"]))
        out.append(nl)
    s["lines"] = out
    s["sample_sha1"] = file_sha1(sample)
    s["sample_size"] = os.path.getsize(sample)
    s["duration"] = round(aligner.duration, 3)
    s.setdefault("source", {})["timeline_shift"] = round(la.sample_shift(sample), 4)
    s["reviewed"] = False
    return s


# ---------------------------------------------------------------- CLI

def pick_song(db_dict: dict[str, Any], query: str) -> str:
    hits = find_songs(db_dict, query)
    if not hits:
        raise SystemExit("No song matches {!r}".format(query))
    if len(hits) > 1 and os.path.splitext(hits[0])[0].lower() != query.lower().strip():
        print("Several songs match; using the first:")
        for h in hits[:8]:
            print("  " + h)
    return hits[0]


def cmd_add(args: argparse.Namespace) -> None:
    db_dict = aa.read_db_file()
    song = pick_song(db_dict, args.song)
    sample = song_sample(db_dict, song)
    path = sidecar_path(song)
    old = read_sidecar(path) if os.path.exists(path) else None
    if old is not None and not args.force:
        raise SystemExit("{} already has lyrics ({}); --force to redo them".format(song, path))
    if old is not None and old.get("reviewed"):
        raise SystemExit("{} is marked reviewed, so its lyrics stay as they are; unmark it in the review "
                         "page to rebuild it, or use Redo song there to start over".format(song))
    if args.lyrics_file:
        with open(args.lyrics_file, encoding="utf8") as f:
            reference: str | None = f.read()
        source: dict[str, Any] = {"lyrics": "file"}
    elif args.no_lyrics:
        reference, source = None, {"lyrics": "none"}
    else:
        artist, title = search_terms(song)
        print("LRCLIB: {} - {}".format(artist, title))
        results = lrclib_search(artist, title)
        if not results:
            print("No lyrics found; using Whisper's own text")
            reference, source = None, {"lyrics": "none"}
        else:
            r = results[0]
            print("Using LRCLIB #{}: {} - {}".format(r["id"], r.get("artistName"), r.get("trackName")))
            reference, source = lyrics_text(r), lrclib_source(r)
    separate = True if args.separate else False if args.no_separate else None
    s = create(song, sample, reference, source, separate=separate, tags=db_dict[song].get("tags", []))
    if old is not None:
        s = keep_hand_edits(old, s)
        kept = sum(1 for l in s["lines"] if l.get("edited"))
        if kept or old.get("removed"):
            print("Kept {} edited line(s); {} deleted line(s) stay out".format(kept, len(old.get("removed", []))))
    print("Wrote {}".format(save_sidecar(s)))


def cmd_realign(args: argparse.Namespace) -> None:
    db_dict = aa.read_db_file()
    song = pick_song(db_dict, args.song)
    path = sidecar_path(song)
    s = read_sidecar(path)
    s["sample"] = aa.get_existing_rekordbox_sample(db_dict[song]) or s["sample"]
    realign_sidecar(s)
    print("Wrote {}".format(save_sidecar(s, path)))


def cmd_check(args: argparse.Namespace) -> None:
    bad = 0
    for path in list_sidecars():
        s = read_sidecar(path)
        st = sidecar_status(s)
        mark = {"ok": "  ", "stale": "! ", "missing": "? "}[st]
        print("{}{:9s} {:10s} {}".format(mark, st, "reviewed" if s.get("reviewed") else "", os.path.basename(path)))
        bad += st != "ok"
    if bad:
        print("\n{} need attention: stale = the sample changed (lyrics.py realign), missing = no sample".format(bad))


def cmd_index(args: argparse.Namespace) -> None:
    index = write_index()
    print("{} songs in {}".format(len(index["songs"]), os.path.join(lyrics_dir(), INDEX_NAME)))


def main(argv: Iterable[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="lyrics for a song: look up, align, write the sidecar")
    a.add_argument("song", help="database song (any words of its name)")
    a.add_argument("--lyrics-file", help="the lyrics as text (one line per line) instead of LRCLIB")
    a.add_argument("--no-lyrics", action="store_true", help="Whisper's own text, no reference lyrics")
    a.add_argument("--separate", action="store_true", help="separate the vocals even for an acapella")
    a.add_argument("--no-separate", action="store_true", help="align the sample as it is")
    a.add_argument("--force", action="store_true", help="rebuild existing lyrics, keeping your edited lines")
    a.set_defaults(func=cmd_add)
    r = sub.add_parser("realign", help="time a song's lyrics again (keeps the text)")
    r.add_argument("song")
    r.set_defaults(func=cmd_realign)
    sub.add_parser("check", help="sidecars whose sample changed or is gone").set_defaults(func=cmd_check)
    sub.add_parser("index", help="rebuild index.json").set_defaults(func=cmd_index)
    args = p.parse_args(list(argv) if argv is not None else None)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
