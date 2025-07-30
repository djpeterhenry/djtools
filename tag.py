# from "pip install enum34"
from enum import Enum


class ListEnum(Enum):
    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))


class Tag(ListEnum):
    # legacy lowercase
    X = "x"
    X_REKORDBOX = "x_rekordbox"
    VOCAL_TAG = "vocal"

    # Try to categorize lots of recent and good songs with one of these:
    LYRICS = "lyrics"
    NO_LYRICS = "no_lyrics"

    # Top level genre tag attempts
    JAZZ = "jazz"  # need to keep lowercase until you fix the database
    DISCO = "DISCO"
    BIG_ROOM = "BIG_ROOM"
    AFRO = "AFRO"

    # better uppercase
    SKIP_KEY = "ALL KEYS"
    SKIP_BPM = "ALL BPM"
    LOOK_TAG = "LOOK"
    GOOD_TAG = "GOOD"  # This one can be applied with "g" so order doesn't matter
    SS_TAG = "SS"
    P_NASTY_TAG = "P_NASTY"
    SHANNON_TAG = "SHANNON"
    DAN_TAG = "DAN"
    PETER_PICKS_TAG = "PETER_PICKS"
    CRISPY_TACOS = "CRISPY_TACOS"
    DRUM_LOOPS = "DRUM_LOOPS"
    ACTUAL_HOUSE = "ACTUAL_HOUSE"
    CASTRO = "CASTRO"
