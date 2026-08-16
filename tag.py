# from "pip install enum34"
from enum import Enum


class ListEnum(Enum):
    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))


class Tag(ListEnum):
    # Top level genre tags
    JAZZ = "JAZZ"
    DISCO = "DISCO"
    BIG_ROOM = "BIG_ROOM"
    TECH_HOUSE = "TECH_HOUSE"
    AFRO = "AFRO"
    ACTUAL_HOUSE = "ACTUAL_HOUSE"
    PROGRESSIVE = "PROGRESSIVE"
    ACID = "ACID"
    TROPICAL = "TROPICAL"
    FILTER_HOUSE = "FILTER_HOUSE"
    ROCK_HOUSE = "ROCK_HOUSE"
    DUBSTEP = "DUBSTEP"
    UK_GARAGE = "UK_GARAGE"
    HIDE_GENRE = "HIDE_GENRE"

    # some legacy lowercase tags.  Could updated.
    X = "x"
    X_REKORDBOX = "x_rekordbox"
    VOCAL_TAG = "vocal"

    # Try to categorize lots of recent and good songs with one of these:
    LYRICS = "lyrics"
    NO_LYRICS = "no_lyrics"

    # better uppercase
    SKIP_KEY = "ALL KEYS"
    SKIP_BPM = "ALL BPM"
    GOOD_TAG = "GOOD"  # This one can be applied with "g" so order doesn't matter
    SS_TAG = "SS"
    P_NASTY_TAG = "P_NASTY"
    CRISPY_TACOS = "CRISPY_TACOS"
    DRUM_LOOPS = "DRUM_LOOPS"
    CASTRO = "CASTRO"

    # Venue/slot tags, slot first: typing "d"/"n" in the web ui tag menus jumps
    # straight to them. Rekordbox search is substring, so "cloverdale" still
    # finds both there.
    DAY_CLOVERDALE = "DAY_CLOVERDALE"
    NIGHT_CLOVERDALE = "NIGHT_CLOVERDALE"


REKORDBOX_GENRE_TAGS = [
    Tag.JAZZ,
    Tag.DISCO,
    Tag.BIG_ROOM,
    Tag.TECH_HOUSE,
    Tag.AFRO,
    Tag.ACTUAL_HOUSE,
    Tag.PROGRESSIVE,
    Tag.ACID,
    Tag.TROPICAL,
    Tag.FILTER_HOUSE,
    Tag.ROCK_HOUSE,
    Tag.DUBSTEP,
    Tag.UK_GARAGE,
    Tag.HIDE_GENRE,
    Tag.CASTRO,
]

REKORDBOX_GENRE_TAG_VALUE_SET = set(genre.value for genre in REKORDBOX_GENRE_TAGS)

# Kept out of the web ui's tag menus (both the filter dropdown and the "+ tag"
# autocomplete). Records keep them and the rekordbox export still reads them --
# they just aren't offered while browsing. Chips already on a song still show,
# so nothing here becomes unremovable.
HIDDEN_TAG_VALUES = {
    # set by workflow, not chosen while browsing
    Tag.X.value,
    Tag.X_REKORDBOX.value,
    Tag.HIDE_GENRE.value,
    Tag.SKIP_KEY.value,
    Tag.SKIP_BPM.value,
    # free-form leftovers, never declared above
    "90",
    "classic",
    "hiphop",
    "northfield",
}

# In both the filename suffixes and the playlist folder below.
REKORDBOX_COMMON_TAGS = REKORDBOX_GENRE_TAGS + [
    Tag.GOOD_TAG,
    Tag.DAY_CLOVERDALE,
    Tag.NIGHT_CLOVERDALE,
]

REKORDBOX_FILENAME_TAGS = REKORDBOX_COMMON_TAGS + [
    Tag.VOCAL_TAG,
    Tag.LYRICS,
    Tag.NO_LYRICS,
]

REKORDBOX_PLAYLIST_TAGS = REKORDBOX_COMMON_TAGS + [
    Tag.P_NASTY_TAG,
    Tag.CRISPY_TACOS,
    Tag.DRUM_LOOPS,
]
