"""Shapes of the records stored in database.json.

database.json maps each Ableton file (relative to the songs folder, e.g.
"Artist - Track.alc") to a Record.
"""

from typing import TypedDict


class WarpMarker(TypedDict):
    sec_time: float  # position in the audio file
    beat_time: float  # position on Ableton's beat grid


class ClipInfo(TypedDict):
    """The first AudioClip of an .alc/.als, as read from its XML."""

    warp_markers: list[WarpMarker]
    loop_start: float
    loop_end: float
    start_relative: float
    loop_on: bool
    hidden_loop_start: float
    hidden_loop_end: float
    sample: str  # relative to the songs folder
    sample_ts: float
    sample_filepath_is_new_format: bool


class Record(TypedDict, total=False):
    bpm: int
    key: str  # e.g. "Am", "F#m" or camelot "8A"; ends in "?" when unsure
    tags: list[str]
    ts_list: list[float]  # play timestamps
    alc_ts: float  # mtime of the .alc/.als when its clip was last read
    old_alc_ts: float
    als_ts: float
    # None when the clip's sample file has gone missing
    clip: ClipInfo | None
    clips: list[ClipInfo | None]  # every AudioClip of an .als
    release_year_discogs: int | None
    release_year_manual: int | None
    labels_discogs: list[str]
    rekordbox_local_sample: str  # exported copy of the sample


DbDict = dict[str, Record]
