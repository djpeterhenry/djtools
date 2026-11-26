"""Where the tools find things outside the songs folder.

Each setting comes from, in order:

1. an environment variable (DJTOOLS_<NAME>, e.g. DJTOOLS_LISTS_FOLDER),
2. ~/.config/djtools/config.toml (or the file named by $DJTOOLS_CONFIG), e.g.

       lists_folder = "~/github/my-site/lists"
       collection_folder = "~/github/my-site/collection"

3. the default below.

A setting whose default is None turns its feature off until it is set: no
"Lists" playlists, no collection lists written.  Paths may start with "~".

List settings (LIST_DEFAULTS) are TOML arrays of strings in the file, or
comma-separated in the environment variable.

The known tags and their properties are a [tags] table in the file only (no
environment variable); see tag.py for the properties and the default table.
"""

import os
import tomllib
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.expanduser("~/.config/djtools/config.toml")

DEFAULTS: dict[str, str | None] = {
    # Folder of song lists (one "Artist - Track" per line, .txt or no
    # extension), each exported as a rekordbox playlist and offered in the
    # Tk browser.
    "lists_folder": None,
    # Folder that the export (and `actions.py generate-lists`) writes the sorted collection lists to.  If
    # it is inside a git repo, they are committed and pushed.
    "collection_folder": None,
    # Where samples are exported for rekordbox (copies, hardlinks or
    # conversions of the Ableton samples).
    "rekordbox_local_sample_path": "~/Music/PioneerDJ/LocalSamples",
    # Folder of rekordbox track-list exports (UTF-16 TSV) named after a tag,
    # e.g. GOOD.txt: every track in one gets that tag.
    "rekordbox_tags_path": "~/Documents/rekordbox_tags",
}

LIST_DEFAULTS: dict[str, list[str]] = {
    # The Tk and web browsers leave out of their tag menus any tag containing
    # one of these, e.g. ["-ab", "(venue)"] for tags you only use as notes.
    "hidden_tags": [],
}


def _read_file(path: str) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def _sources(environ: dict[str, str] | None) -> tuple[Any, dict[str, Any]]:
    """The environment and the config file's values, checked for unknown names."""
    env = os.environ if environ is None else environ
    from_file = _read_file(env.get("DJTOOLS_CONFIG") or CONFIG_FILE)
    unknown = set(from_file) - set(DEFAULTS) - set(LIST_DEFAULTS) - {"tags"}
    if unknown:
        raise SystemExit(
            "Unknown setting(s) in djtools config: {}".format(", ".join(sorted(unknown)))
        )
    return env, from_file


def load(environ: dict[str, str] | None = None) -> dict[str, str | None]:
    """Every path setting, resolved (see the module notes) and with "~" expanded."""
    env, from_file = _sources(environ)
    settings: dict[str, str | None] = {}
    for name, default in DEFAULTS.items():
        value = env.get("DJTOOLS_" + name.upper()) or from_file.get(name, default)
        settings[name] = os.path.expanduser(str(value)) if value else None
    return settings


def load_lists(environ: dict[str, str] | None = None) -> dict[str, list[str]]:
    """Every list setting, resolved (see the module notes)."""
    env, from_file = _sources(environ)
    settings: dict[str, list[str]] = {}
    for name, default in LIST_DEFAULTS.items():
        from_env = env.get("DJTOOLS_" + name.upper())
        if from_env:
            settings[name] = [v.strip() for v in from_env.split(",") if v.strip()]
            continue
        value = from_file.get(name, default)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise SystemExit("djtools config: {} must be a list of strings".format(name))
        settings[name] = list(value)
    return settings


def load_tags(environ: dict[str, str] | None = None) -> dict[str, list[str]] | None:
    """The [tags] table (tag -> property names, in the file's order), or None when the file has none."""
    _, from_file = _sources(environ)
    table = from_file.get("tags")
    if table is None:
        return None
    if not isinstance(table, dict):
        raise SystemExit("djtools config: tags must be a table ([tags], then TAG = [properties])")
    for name, props in table.items():
        if not isinstance(props, list) or not all(isinstance(p, str) for p in props):
            raise SystemExit('djtools config: tags.{} must be a list of property names, e.g. ["playlist"]'.format(name))
    return {name: list(props) for name, props in table.items()}


SETTINGS = load()
LIST_SETTINGS = load_lists()
TAGS_SETTING = load_tags()


def get(name: str) -> str | None:
    return SETTINGS[name]


def get_required(name: str) -> str:
    """A setting that has a default, so is never None."""
    value = SETTINGS[name]
    assert value is not None, name
    return value


def get_list(name: str) -> list[str]:
    return LIST_SETTINGS[name]


def get_tags() -> dict[str, list[str]] | None:
    return TAGS_SETTING
