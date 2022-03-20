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
    # better uppercase
    SKIP_KEY = "ALL KEYS"
    SKIP_BPM = "ALL BPM"
    LOOK_TAG = "LOOK"
    GOOD_TAG = "GOOD"
    SS_TAG = "SS"
    P_NASTY_TAG = "P_NASTY"
    SHANNON_TAG = "SHANNON"
    DAN_TAG = "DAN"
    PETER_PICKS_TAG = "PETER_PICKS"
    CRISPY_TACOS = "CRISPY_TACOS"
    DRUM_LOOPS = "DRUM_LOOPS"
    ACTUAL_HOUSE = "ACTUAL_HOUSE"
