"""Shared fixtures.

Nothing here touches the real music library, rekordbox, discogs, ffmpeg or git:
every test runs inside a tmp dir laid out like the Ableton project.
"""

import gzip
import os
import time

from typing import Any, cast

import pytest

import ableton_aid as aa
from db_types import DbDict, Record

# 2024-06-15 12:00 local time: a fixed "now" for anything recency based.
FIXED_NOW = time.mktime((2024, 6, 15, 12, 0, 0, 0, 0, -1))
DAY = 24 * 60 * 60


@pytest.fixture
def fixed_now(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: FIXED_NOW)
    return FIXED_NOW


def make_record(**fields: Any) -> Record:
    record: dict[str, Any] = {"bpm": 124, "key": "Am", "tags": []}
    record.update(fields)
    return cast(Record, record)


@pytest.fixture
def songs_dir(tmp_path, monkeypatch):
    """A tmp copy of the layout scripts run in: <project>/Songs is the cwd,
    samples live in <project>/Samples/Imported."""
    project = tmp_path / "project"
    songs = project / "Songs"
    songs.mkdir(parents=True)
    (project / "Samples" / "Imported").mkdir(parents=True)
    monkeypatch.chdir(songs)
    return songs


def _clip_xml(name, warp_markers, loop, sample_name, new_format, project):
    markers = "".join(
        '<WarpMarker SecTime="{}" BeatTime="{}" />'.format(sec, beat)
        for sec, beat in warp_markers
    )
    if new_format:
        fileref = (
            '<RelativePathType Value="3" />'
            '<RelativePath Value="Samples/Imported/{0}" />'
            '<Path Value="{1}/Samples/Imported/{0}" />'.format(sample_name, project)
        )
    else:
        fileref = (
            '<HasRelativePath Value="true" />'
            "<RelativePath>"
            '<RelativePathElement Dir="Samples" />'
            '<RelativePathElement Dir="Imported" />'
            "</RelativePath>"
            '<Name Value="{}" />'.format(sample_name)
        )
    return (
        '<AudioClip Time="0">'
        '<Name Value="{name}" />'
        "<WarpMarkers>{markers}</WarpMarkers>"
        "<Loop>"
        '<LoopStart Value="{loop_start}" />'
        '<LoopEnd Value="{loop_end}" />'
        '<StartRelative Value="{start_relative}" />'
        '<LoopOn Value="{loop_on}" />'
        '<HiddenLoopStart Value="{hidden_loop_start}" />'
        '<HiddenLoopEnd Value="{hidden_loop_end}" />'
        "</Loop>"
        "<SampleRef>"
        "<FileRef>{fileref}</FileRef>"
        '<DefaultDuration Value="441000" />'
        '<DefaultSampleRate Value="44100" />'
        "</SampleRef>"
        "</AudioClip>"
    ).format(
        name=name,
        markers=markers,
        fileref=fileref,
        loop_on="true" if loop.get("loop_on") else "false",
        loop_start=loop.get("loop_start", 0.0),
        loop_end=loop.get("loop_end", 16.0),
        start_relative=loop.get("start_relative", 0.0),
        hidden_loop_start=loop.get("hidden_loop_start", 0.0),
        hidden_loop_end=loop.get("hidden_loop_end", 16.0),
    )


@pytest.fixture
def make_alc(songs_dir):
    """Write a minimal gzip'd Ableton clip/set that the XML readers accept.

    Returns the filename relative to the songs dir, as the db keys are.
    """
    project = songs_dir.parent

    def _make(
        filename="Artist - Track.alc",
        warp_markers=((0.5, 0.0), (8.5, 16.0)),
        loop=None,
        sample_name=None,
        new_format=True,
        create_sample=True,
        num_clips=1,
    ):
        sample_name = sample_name or os.path.splitext(filename)[0] + ".aiff"
        if create_sample:
            (project / "Samples" / "Imported" / sample_name).write_bytes(b"audio")
        clip = _clip_xml(
            os.path.splitext(filename)[0],
            warp_markers,
            loop or {},
            sample_name,
            new_format,
            project,
        )
        xml = '<?xml version="1.0" encoding="UTF-8"?><Ableton>{}</Ableton>'.format(
            clip * num_clips
        )
        (songs_dir / filename).write_bytes(gzip.compress(xml.encode("utf8")))
        return filename

    return _make


@pytest.fixture
def db_dict(fixed_now) -> DbDict:
    """A handful of records covering the shapes seen in the real database."""
    return {
        "A - Old Favorite.alc": make_record(
            bpm=122,
            key="8A",
            tags=["GOOD"],
            ts_list=[fixed_now - 400 * DAY, fixed_now - 30 * DAY, fixed_now - 30 * DAY + 60],
            alc_ts=fixed_now - 1000 * DAY,
        ),
        "B - New One.alc": make_record(
            bpm=126,
            key="Db",
            ts_list=[fixed_now - 2 * DAY],
            alc_ts=fixed_now - 5 * DAY,
        ),
        "C - Vocal.alc": make_record(bpm=90, key="F#m", tags=["vocal"], alc_ts=fixed_now - 10 * DAY),
        "D - Hidden.alc": make_record(tags=["x"], alc_ts=fixed_now - 3 * DAY),
        "E - No Key.alc": {"bpm": 128, "tags": [], "alc_ts": fixed_now - 20 * DAY},
        "F - Missing Clip.alc": make_record(clip=None, alc_ts=fixed_now - 50 * DAY),
    }


@pytest.fixture
def write_db(songs_dir):
    """Write a db_dict as the songs dir's database.json."""

    def _write(db):
        aa.write_db_file(db)
        return songs_dir / aa.DATABASE_JSON

    return _write
