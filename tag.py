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
    SHANNON_TAG = "SHANNON"
    DAN_TAG = "DAN"
    CRISPY_TACOS = "CRISPY_TACOS"
    DRUM_LOOPS = "DRUM_LOOPS"
    CASTRO = "CASTRO"


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

REKORDBOX_COMMON_TAGS = REKORDBOX_GENRE_TAGS + [
    Tag.GOOD_TAG,
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
