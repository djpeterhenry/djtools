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
