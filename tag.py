"""The tags the tools know, and what each one does.

Tags are free-form strings on a record (any tag can be added), but known tags
have properties, set per tag in the config's [tags] table (see config.py), or
DEFAULT_TAGS below when it has none:

    [tags]
    DISCO = ["genre", "mark", "playlist"]
    DAY_VENUE = ["mark", "playlist"]
    LOOPS = ["playlist"]
    oldstuff = ["hidden"]

Properties:
    genre     the song's genre: shown in the Tk genre column, counts for the
              "needs genre" filters, colored as a genre on the web
    mark      marked in the rekordbox file name, e.g. "Song [#disco]"
    playlist  exported as a rekordbox playlist (in the "Tag" folder)
    hidden    left out of the web browser's tag menus (the Tk browser lists
              every tag, since its menu is also how tags are picked and
              added); the hidden_tags setting hides by pattern in both

The table's order is the order of the marks in a file name, of the playlists
and of the tag menus.  With a table, it is the whole list: a tag left out has
no properties.  The built-in tags (Tag below) keep what the code does with
them either way, and are always offered in the tag menus.
"""

import builtins
from enum import Enum

import config


class ListEnum(Enum):
    @classmethod
    def list(cls) -> builtins.list[str]:
        return [c.value for c in cls]


class Tag(ListEnum):
    """Tags with a meaning in the code."""

    HIDE_GENRE = "HIDE_GENRE"  # no genre, on purpose: always counts as a genre

    # some legacy lowercase tags.  Could updated.
    X = "x"  # left out of everything
    X_REKORDBOX = "x_rekordbox"  # left out of the rekordbox export
    VOCAL_TAG = "vocal"

    # Try to categorize lots of recent and good songs with one of these:
    LYRICS = "lyrics"
    NO_LYRICS = "no_lyrics"

    # better uppercase
    SKIP_KEY = "ALL KEYS"
    SKIP_BPM = "ALL BPM"
    GOOD_TAG = "GOOD"  # This one can be applied with "g" so order doesn't matter
    SS_TAG = "SS"  # left out of the rekordbox export; its own filter in the Tk browser


PROPERTIES = ("genre", "mark", "playlist", "hidden")

_GENRE = ["genre", "mark", "playlist"]

DEFAULT_TAGS: dict[str, list[str]] = {
    "JAZZ": _GENRE,
    "DISCO": _GENRE,
    "BIG_ROOM": _GENRE,
    "TECH_HOUSE": _GENRE,
    "AFRO": _GENRE,
    "ACTUAL_HOUSE": _GENRE,
    "PROGRESSIVE": _GENRE,
    "ACID": _GENRE,
    "TROPICAL": _GENRE,
    "FILTER_HOUSE": _GENRE,
    "ROCK_HOUSE": _GENRE,
    "DUBSTEP": _GENRE,
    "UK_GARAGE": _GENRE,
    Tag.HIDE_GENRE.value: _GENRE + ["hidden"],
    Tag.GOOD_TAG.value: ["mark", "playlist"],
    Tag.VOCAL_TAG.value: ["mark"],
    Tag.LYRICS.value: ["mark"],
    Tag.NO_LYRICS.value: ["mark"],
    Tag.SS_TAG.value: [],
    Tag.X.value: ["hidden"],
    Tag.X_REKORDBOX.value: ["hidden"],
    Tag.SKIP_KEY.value: ["hidden"],
    Tag.SKIP_BPM.value: ["hidden"],
}


def check(table: dict[str, builtins.list[str]]) -> None:
    """Stop on a property name that isn't one of PROPERTIES (a typo would otherwise do nothing)."""
    for name, props in table.items():
        unknown = [p for p in props if p not in PROPERTIES]
        if unknown:
            raise SystemExit(
                "djtools config: tags.{}: unknown property {} (known: {})".format(
                    name, ", ".join(unknown), ", ".join(PROPERTIES)
                )
            )


TAGS: dict[str, builtins.list[str]] = config.get_tags() or DEFAULT_TAGS
check(TAGS)


def with_property(prop: str) -> builtins.list[str]:
    """The tags that have `prop`, in the table's order."""
    return [name for name, props in TAGS.items() if prop in props]


# HIDE_GENRE is a genre even when the table leaves it out: the Tk browser's
# "hide genre" button is how a song is marked as needing none.
REKORDBOX_GENRE_TAGS: list[str] = list(dict.fromkeys(with_property("genre") + [Tag.HIDE_GENRE.value]))
REKORDBOX_GENRE_TAG_VALUE_SET = set(REKORDBOX_GENRE_TAGS)

# Marked in rekordbox file names ("[#disco]"), in this order.
REKORDBOX_FILENAME_TAGS: list[str] = with_property("mark")

# Exported as rekordbox playlists, in this order.
REKORDBOX_PLAYLIST_TAGS: list[str] = with_property("playlist")

# Kept out of the web ui's tag menus (both the filter dropdown and the "+ tag"
# autocomplete). Records keep them and the rekordbox export still reads them --
# they just aren't offered while browsing. Chips already on a song still show,
# so nothing here becomes unremovable.  (More in the hidden_tags setting.)
HIDDEN_TAG_VALUES = set(with_property("hidden"))

# Offered in the browsers' tag menus ahead of the other tags found in the db.
MENU_TAGS: list[str] = list(dict.fromkeys(list(TAGS) + Tag.list()))


def find_tag(name: str) -> str | None:
    """The known tag named `name`, ignoring case (e.g. "Big_Room" -> "BIG_ROOM"), or None."""
    by_upper = {t.upper(): t for t in MENU_TAGS}
    return by_upper.get(name.upper())
