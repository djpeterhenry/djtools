import datetime
import os
import subprocess
import types
import xml.etree.ElementTree as ET

import pytest

from typing import cast

import ableton_aid as aa
import export_rekordbox as er
from conftest import DAY, make_record
from db_types import ClipInfo, Record


# ---------------------------------------------------------------- history


def test_parse_history_date_ts():
    day_ts = aa.get_ts_for(2024, 6, 15)
    assert er._parse_history_date_ts("HISTORY 2024-06-15") == (day_ts, day_ts)
    assert er._parse_history_date_ts("HISTORY 2024-06-15 (2)") == (day_ts, day_ts + 2000)
    assert er._parse_history_date_ts("My Playlist") is None
    assert er._parse_history_date_ts("HISTORY 2024-06-15 extra") is None


def test_history_song_ts():
    day_ts = aa.get_ts_for(2024, 6, 15)
    played = datetime.datetime(2024, 6, 15, 23, 30)
    assert er._history_song_ts(types.SimpleNamespace(created_at=played), day_ts, day_ts, 3) == played.timestamp()
    # a clock way off falls back to date order
    bogus = datetime.datetime(2020, 1, 1)
    assert er._history_song_ts(types.SimpleNamespace(created_at=bogus), day_ts, day_ts + 1000, 3) == day_ts + 1003
    assert er._history_song_ts(types.SimpleNamespace(), day_ts, day_ts, 5) == day_ts + 5


class FakeRekordboxDb:
    def __init__(self, histories, songs):
        self.histories = histories
        self.songs = songs
        self.closed = False

    def get_history(self):
        return self.histories

    def get_history_songs(self, HistoryID):
        return self.songs[HistoryID]

    def close(self):
        self.closed = True


def _history(id, name, created):
    return types.SimpleNamespace(ID=id, Name=name, DateCreated=created)


def _song(track_no, artist, title, created_at=None):
    content = types.SimpleNamespace(
        Artist=types.SimpleNamespace(Name=artist) if artist else None, Title=title
    )
    return types.SimpleNamespace(TrackNo=track_no, Content=content, created_at=created_at)


@pytest.fixture
def fake_rekordbox(monkeypatch):
    import pyrekordbox

    holder = {}

    def install(histories, songs):
        holder["db"] = FakeRekordboxDb(histories, songs)
        monkeypatch.setattr(pyrekordbox, "Rekordbox6Database", lambda: holder["db"])
        return holder["db"]

    return install


def test_stamp_from_rekordbox_db(songs_dir, write_db, db_dict, fake_rekordbox):
    write_db(db_dict)
    played = datetime.datetime(2024, 6, 10, 21, 0)
    db = fake_rekordbox(
        [
            _history(1, "HISTORY 2024-06-10", 1),
            _history(2, "HISTORY 2024-06-14", 2),
            _history(3, "Not a history", 3),
        ],
        {
            1: [_song(1, "A", "Old Favorite   [#GOOD]", played)],
            2: [_song(1, "B", "New One"), _song(2, None, "Unknown")],
        },
    )
    er.stamp_from_rekordbox_db()
    assert db.closed
    result = aa.read_db_file()
    assert played.timestamp() in result["A - Old Favorite.alc"]["ts_list"]
    assert aa.get_ts_for(2024, 6, 14) in result["B - New One.alc"]["ts_list"]
    # the most recent session is redone next time, in case it was still going
    with open(er.REKORDBOX_PROCESSED_IDS_FILE) as f:
        assert f.read() == "[1]"


def test_stamp_from_rekordbox_db_without_history(songs_dir, write_db, db_dict, fake_rekordbox):
    write_db(db_dict)
    fake_rekordbox([], {})
    er.stamp_from_rekordbox_db()


def test_update_rekordbox_tags(songs_dir, write_db, db_dict, tmp_path, monkeypatch):
    write_db(db_dict)
    tags_dir = tmp_path / "tags"
    tags_dir.mkdir()
    lines = ["#\tArtist\tTrack Title", "1\tB\tNew One [#a0]", "2\tNobody\tNothing"]
    (tags_dir / "disco.txt").write_text("\n".join(lines) + "\n", encoding="utf-16le")
    (tags_dir / "not_a_tag.txt").write_text("\n".join(lines) + "\n", encoding="utf-16le")
    monkeypatch.setattr(er, "REKORDBOX_TAGS_PATH", str(tags_dir))
    er.update_rekordbox_tags()
    result = aa.read_db_file()
    assert result["B - New One.alc"]["tags"] == ["DISCO"]
    assert "not_a_tag" not in str(result)


# ---------------------------------------------------------- compatibility


@pytest.mark.parametrize(
    "stream, path, expected",
    [
        (None, "x.mp3", None),
        ({"codec_name": "mp3", "format_name": "wav", "sample_rate": "44100"}, "x.mp3", "a wav container named .mp3"),
        (
            {"codec_name": "pcm_s16le", "format_name": "aiff", "sample_rate": "44100"},
            "x.aiff",
            "byte-swapped AIFF-C (pcm_s16le, needs big-endian)",
        ),
        (
            {"codec_name": "mp3", "format_name": "mp3", "sample_rate": "44100", "bit_rate": "350000"},
            "x.mp3",
            "350 kbps mp3 (max 320)",
        ),
        ({"codec_name": "mp3", "format_name": "mp3", "sample_rate": "44100", "bit_rate": "320000"}, "x.mp3", None),
        ({"codec_name": "pcm_f32le", "format_name": "wav", "sample_rate": "44100"}, "x.wav", "pcm_f32le (no CDJ plays float)"),
        (
            {"codec_name": "pcm_s32le", "format_name": "wav", "sample_rate": "44100", "bits_per_sample": 32},
            "x.wav",
            "32-bit pcm (max 24)",
        ),
        (
            {"codec_name": "pcm_s24be", "format_name": "aiff", "sample_rate": "96000", "bits_per_raw_sample": "24"},
            "x.aiff",
            "96000 Hz (needs 44100 or 48000)",
        ),
        ({"codec_name": "pcm_s16be", "format_name": "aiff", "sample_rate": "48000"}, "x.aif", None),
        ({"codec_name": "aac", "format_name": "mov,mp4,m4a", "sample_rate": "44100"}, "x.m4a", None),
        ({"codec_name": "flac", "format_name": "", "sample_rate": "44100"}, "x.wav", None),
    ],
)
def test_get_incompatible_reason(stream, path, expected):
    assert er.get_incompatible_reason(stream, path) == expected


def test_probe_audio_stream(monkeypatch):
    out = b'{"streams": [{"codec_name": "mp3"}], "format": {"format_name": "mp3"}}'
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: out)
    assert er.probe_audio_stream("x.mp3") == {"codec_name": "mp3", "format_name": "mp3"}

    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: b'{"streams": []}')
    assert er.probe_audio_stream("x.mp3") is None

    def fail(*a, **k):
        raise subprocess.CalledProcessError(1, "ffprobe")

    monkeypatch.setattr(subprocess, "check_output", fail)
    assert er.probe_audio_stream("x.mp3") is None


def test_run_ffmpeg_convert(tmp_path, monkeypatch):
    target = tmp_path / "out.aiff"
    calls = []

    def ok(cmd):
        calls.append(cmd)
        open(cmd[-1], "w").close()

    monkeypatch.setattr(subprocess, "check_call", ok)
    er.run_ffmpeg_convert("in.flac", str(target), ["-c:a", "x"])
    assert calls == [["ffmpeg", "-y", "-i", "in.flac", "-c:a", "x", str(tmp_path / "out.partial.aiff")]]
    assert target.exists()


def test_run_ffmpeg_convert_cleans_up(tmp_path, monkeypatch):
    target = tmp_path / "out.aiff"

    def fail(cmd):
        open(cmd[-1], "w").close()
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "check_call", fail)
    with pytest.raises(KeyboardInterrupt):
        er.run_ffmpeg_convert("in.flac", str(target))
    assert os.listdir(tmp_path) == []


@pytest.mark.parametrize("rate, expected", [("96000", "48000"), ("88200", "44100"), ("22050", "44100"), ("48000", "48000")])
def test_convert_to_compatible(monkeypatch, rate, expected):
    calls = []
    monkeypatch.setattr(er, "run_ffmpeg_convert", lambda s, t, args: calls.append(args))
    er.convert_to_compatible("s", "t", {"sample_rate": rate})
    assert calls == [["-c:a", "pcm_s16be", "-ar", expected]]


def test_link_or_copy(tmp_path, monkeypatch):
    source = tmp_path / "s"
    source.write_text("x")
    er.link_or_copy(str(source), str(tmp_path / "linked"))
    assert os.stat(tmp_path / "linked").st_ino == os.stat(source).st_ino

    def no_link(a, b):
        raise OSError("EXDEV")

    monkeypatch.setattr(os, "link", no_link)
    er.link_or_copy(str(source), str(tmp_path / "copied"))
    assert (tmp_path / "copied").read_text() == "x"
    assert os.stat(tmp_path / "copied").st_ino != os.stat(source).st_ino


def test_purge_incompatible_samples(tmp_path, monkeypatch):
    for name in ["good.aiff", "bad.wav", "bad.aiff", ".hidden"]:
        (tmp_path / name).write_text("")
    float_stream = {"codec_name": "pcm_f32le", "format_name": "wav", "sample_rate": "44100"}
    good_stream = {"codec_name": "pcm_s16be", "format_name": "aiff", "sample_rate": "44100"}
    monkeypatch.setattr(
        er, "probe_audio_stream", lambda p: good_stream if "good" in p else dict(float_stream)
    )
    er.purge_incompatible_samples(str(tmp_path), delete=False)
    assert len(os.listdir(tmp_path)) == 4
    er.purge_incompatible_samples(str(tmp_path), delete=True)
    assert sorted(os.listdir(tmp_path)) == [".hidden", "good.aiff"]


def test_relink_samples(songs_dir, write_db, tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    sample = songs_dir / "s.aiff"
    sample.write_text("audio")
    (export / "A - B.aiff").write_text("audio")
    (export / "C - D.aiff").write_text("other")
    (songs_dir / "A - B.alc").write_text("")
    (songs_dir / "C - D.alc").write_text("")
    write_db(
        {
            "A - B.alc": make_record(clip={"sample": "s.aiff"}),
            "C - D.alc": make_record(clip={"sample": "s.aiff"}),
        }
    )
    er.relink_samples(str(export), relink=False)
    assert os.stat(export / "A - B.aiff").st_ino != os.stat(sample).st_ino
    er.relink_samples(str(export), relink=True)
    assert os.stat(export / "A - B.aiff").st_ino == os.stat(sample).st_ino
    assert (export / "C - D.aiff").read_text() == "other"


def test_export_rekordbox_samples(songs_dir, write_db, tmp_path, monkeypatch):
    monkeypatch.setattr(aa, "update_db_clips_safe", lambda: None)
    monkeypatch.setattr(aa, "generate_lists", lambda: None)
    export = tmp_path / "export"
    for name in ["copy.aiff", "float.wav", "remux.m4a", "hot.flac"]:
        (songs_dir / name).write_text(name)
    for name in ["Copy.alc", "Float.alc", "Remux.alc", "Hot.alc", "Skipped.alc"]:
        (songs_dir / name).write_text("")
    write_db(
        {
            "Copy.alc": make_record(clip={"sample": "copy.aiff"}),
            "Float.alc": make_record(clip={"sample": "float.wav"}),
            "Remux.alc": make_record(clip={"sample": "remux.m4a"}),
            "Hot.alc": make_record(clip={"sample": "hot.flac"}),
            "Skipped.alc": make_record(tags=["x"], clip={"sample": "copy.aiff"}),
        }
    )
    streams = {
        "copy.aiff": {"codec_name": "pcm_s16be", "format_name": "aiff", "sample_rate": "44100"},
        "float.wav": {"codec_name": "pcm_f32le", "format_name": "wav", "sample_rate": "44100"},
        "remux.m4a": {"codec_name": "aac", "format_name": "mov,mp4,m4a", "sample_rate": "44100"},
        "hot.flac": {"codec_name": "flac", "format_name": "flac", "sample_rate": "96000"},
    }
    monkeypatch.setattr(er, "probe_audio_stream", lambda p: streams[os.path.basename(p)])
    converted = []

    def fake_convert(source, target, *args):
        converted.append((os.path.basename(source), os.path.basename(target), bool(args)))
        open(target, "w").close()

    monkeypatch.setattr(er, "run_ffmpeg_convert", fake_convert)
    monkeypatch.setattr(er, "convert_to_compatible", fake_convert)

    er.export_rekordbox_samples(str(export), convert_flac=True)

    assert sorted(converted) == [
        ("float.wav", "Float.aiff", True),
        ("hot.flac", "Hot.aiff", True),
        ("remux.m4a", "Remux.aiff", False),
    ]
    assert os.stat(export / "Copy.aiff").st_ino == os.stat(songs_dir / "copy.aiff").st_ino
    db = aa.read_db_file()
    key = aa.REKORDBOX_LOCAL_SAMPLE_KEY
    assert db["Copy.alc"][key] == str(export / "Copy.aiff")
    assert db["Float.alc"][key] == str(export / "Float.aiff")
    assert key not in db["Skipped.alc"]

    # a second export only checks existence
    converted.clear()
    monkeypatch.setattr(er, "probe_audio_stream", lambda p: pytest.fail("probed again"))
    er.export_rekordbox_samples(str(export), convert_flac=True)
    assert converted == []


# ------------------------------------------------------------- beat grid


def test_get_bpm_and_range_list():
    result = er.get_bpm_and_range_list()
    assert result[0] == (0, 0)
    assert result == sorted(result)
    for pair in [(80, 5), (115, 5), (118, 4), (132, 4), (135, 5), (140, 5), (120, 10), (160, 10)]:
        assert pair in result
    assert len(result) == 1 + 8 + 8 + 2 + 9


def test_beat_seconds_conversion():
    assert er.get_seconds_for_beat(0, 1.0, 4, 120) == 3.0
    assert er.get_beat_for_seconds(0, 1.0, 3.0, 120) == 4.0
    marker = er.BeatGridMarker(sec_time=2.0, bpm=60, beat_time=8)
    assert er.get_seconds_relative_to_marker(marker, 10) == 4.0
    assert er.get_beat_relative_to_marker(marker, 4.0) == 10.0


def clip(warp_markers, **loop) -> ClipInfo:
    result: dict = {
        "warp_markers": [{"sec_time": s, "beat_time": b} for s, b in warp_markers],
        "loop_start": 0.0,
        "loop_end": 16.0,
        "start_relative": 0.0,
        "loop_on": False,
        "hidden_loop_start": 0.0,
        "hidden_loop_end": 16.0,
        "sample": "../s.aiff",
    }
    result.update(loop)
    return cast(ClipInfo, result)


def summary(markers):
    return [(m.sec_time, m.bpm, m.beat_time, m.memory_note) for m in markers]


def test_get_beat_grid_markers_simple():
    result = er.get_beat_grid_markers("f", clip([(1.0, 0.0), (9.0, 16.0)]))
    assert summary(result.beat_grid_markers) == [(1.0, 120.0, 0.0, None)]
    assert (result.start_cue.start, result.start_cue.end, result.start_cue.name) == (1.0, None, "Start")
    assert (result.loop_cue.start, result.loop_cue.end, result.loop_cue.loop_on) == (1.0, 9.0, False)


def test_get_beat_grid_markers_backfills_to_zero():
    result = er.get_beat_grid_markers("f", clip([(30.0, 32.0), (38.0, 48.0)], hidden_loop_start=4.0))
    assert summary(result.beat_grid_markers) == [
        (6.0, 120.0, -16.0, None),
        (14.0, 120.0, 0.0, None),
        (30.0, 120.0, 32.0, "Beat 1"),
    ]
    assert result.start_cue.start == 14.0
    # hidden loop doesn't start at the start cue: no loop
    assert result.loop_cue is None


def test_get_beat_grid_markers_loop_on():
    result = er.get_beat_grid_markers(
        "f", clip([(1.0, 0.0), (9.0, 16.0)], loop_on=True, loop_start=4.0, loop_end=8.0, hidden_loop_start=0.0)
    )
    assert result.start_cue.start == 3.0
    assert (result.loop_cue.start, result.loop_cue.end, result.loop_cue.loop_on) == (3.0, 5.0, True)


def test_get_track_info_and_add_to_track():
    record: Record = {"clip": clip([(30.0, 32.0), (38.0, 48.0)])}
    info = er.get_track_info("f", record)
    assert [c.name for c in info.hot_cues] == ["Start", "Start Loop"]
    assert [c.name for c in info.memory_cues] == ["Start", "Start Loop", "Beat 1"]

    et = ET.Element("TRACK")
    info.add_to_track(et)
    assert et.get("AverageBpm") == "120.0"
    tempos = et.findall("TEMPO")
    assert [(t.get("Inizio"), t.get("Battito")) for t in tempos] == [("6.0", "1"), ("14.0", "1"), ("30.0", "1")]
    marks = [(p.get("Name"), p.get("Type"), p.get("Num"), p.get("End")) for p in et.findall("POSITION_MARK")]
    assert marks == [
        ("Start", "0", "0", None),
        ("Start Loop", "4", "1", "22.0"),
        ("Start", "0", "-1", None),
        ("Start Loop", "4", "-1", "22.0"),
        ("Beat 1", "0", "-1", None),
    ]


def test_get_als_track_info_shims_before_next_start():
    markers = [(1.0, 0.0), (9.0, 16.0), (41.0, 80.0), (49.0, 96.0)]
    record: Record = {
        "clips": [
            clip(markers),
            clip(markers, loop_start=64.0, hidden_loop_start=64.0, hidden_loop_end=72.0),
            clip(markers, sample="../other.aiff"),
        ]
    }
    info = er.get_als_track_info("f", record)
    assert [(m.sec_time, m.beat_time) for m in info.beat_grid_markers] == [
        (1.0, 0.0),
        (9.0, 16.0),
        (32.5, 63.0),
        (41.0, 80.0),
    ]
    assert [c.start for c in info.hot_cues] == [1.0, 33.0]
    assert info.memory_cues == []


def test_get_als_track_info_skips_missing_clips():
    record: Record = {"clips": [None, clip([(1.0, 0.0), (9.0, 16.0)])]}
    assert len(er.get_als_track_info("f", record).hot_cues) == 1


# --------------------------------------------------------------- filters


def test_get_filtered_files(db_dict):
    files = [f for f in sorted(db_dict) if f != "E - No Key.alc"]
    assert er.get_filtered_files(db_dict, files, tags=["GOOD"]) == ["A - Old Favorite.alc"]
    # the vocal at 90 bpm is in regardless of bpm
    assert er.get_filtered_files(db_dict, files, bpm=124, bpm_range=2) == [
        "A - Old Favorite.alc",
        "B - New One.alc",
        "C - Vocal.alc",
        "D - Hidden.alc",
        "F - Missing Clip.alc",
    ]
    assert er.get_filtered_files(db_dict, files, cam_num_list=[3, 11]) == ["B - New One.alc", "C - Vocal.alc"]


def test_get_filtered_files_without_key(db_dict):
    assert er.get_filtered_files(db_dict, ["E - No Key.alc"], cam_num_list=[8]) == []


def test_matches_active_window(fixed_now):
    assert er.matches_active_window({"alc_ts": fixed_now - 500 * DAY}, 365, 3650)
    assert not er.matches_active_window({"alc_ts": fixed_now - 100 * DAY}, 365, 3650)
    assert not er.matches_active_window({"alc_ts": fixed_now - 4000 * DAY}, 365, 3650)


def test_get_top_play_count_files(db_dict):
    files = sorted(db_dict)
    assert er.get_top_play_count_files(db_dict, files, years=1, top_num=1) == {"B - New One.alc"}
    assert er.get_top_play_count_files(db_dict, files, years=2) == {"A - Old Favorite.alc", "B - New One.alc"}


def test_playlist_adder():
    adder = er.PlaylistAdder({"a": 0, "b": 1, "c": 2})
    root = ET.Element("NODE")
    adder.add_playlist_for_files(root, "List", ["a", "unknown", "c", "b"])
    playlist = root.find("NODE")
    assert playlist.get("Name") == "List"
    assert playlist.get("Entries") == "3"
    assert [t.get("Key") for t in playlist.findall("TRACK")] == ["0", "2", "1"]
    assert adder.playlists_added == 1


def test_playlist_adder_max_num():
    adder = er.PlaylistAdder({"a": 0, "b": 1, "c": 2})
    root = ET.Element("NODE")
    adder.add_playlist_for_files(root, "List", ["a", "b", "c"], max_num=2)
    assert root.find("NODE").get("Entries") == "2"


# --------------------------------------------------------- full export

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "rekordbox.xml")


@pytest.fixture
def export_env(songs_dir, write_db, tmp_path, monkeypatch, fixed_now):
    """A small library ready for export_rekordbox_xml, with every side effect
    (rekordbox db, tag files, sample conversion, git) stubbed out."""
    import random

    random.seed(0)
    monkeypatch.setattr(er, "stamp_from_rekordbox_db", lambda: None)
    monkeypatch.setattr(er, "update_rekordbox_tags", lambda: None)
    monkeypatch.setattr(er, "export_rekordbox_samples", lambda **kw: None)

    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "warmup.txt").write_text("B - New One\nC - Vocal\nNot In Db\n")
    monkeypatch.setattr(aa, "LISTS_FOLDER", str(lists))
    active = tmp_path / "active_list.txt"
    active.write_text("-- a date\nA - Old Favorite.alc\n")
    monkeypatch.setattr(aa, "ACTIVE_LIST", str(active))

    samples = tmp_path / "samples"
    samples.mkdir()
    simple = clip([(1.0, 0.0), (9.0, 16.0)])
    db = {
        "A - Old Favorite.alc": make_record(
            bpm=122,
            key="8A",
            tags=["GOOD", "DISCO", "lyrics"],
            ts_list=[fixed_now - 400 * DAY, fixed_now - 30 * DAY],
            alc_ts=fixed_now - 1000 * DAY,
            release_year_discogs=1998,
            clip=simple,
        ),
        "B - New One.alc": make_record(
            bpm=126, key="Db", ts_list=[fixed_now - 2 * DAY], alc_ts=fixed_now - 5 * DAY, clip=simple
        ),
        "C - Vocal.alc": make_record(
            bpm=90, key="F#m", tags=["vocal"], alc_ts=fixed_now - 10 * DAY, release_year_manual=2005, clip=simple
        ),
        "D - Set.als": make_record(
            bpm=128,
            key="11B",
            alc_ts=fixed_now - 3 * DAY,
            ts_list=[fixed_now - 1 * DAY],
            clips=[simple, clip([(1.0, 0.0), (9.0, 16.0)], loop_start=32.0)],
        ),
        "E - Hidden.alc": make_record(tags=["x"], alc_ts=fixed_now, clip=simple),
        "F - No Sample.alc": make_record(alc_ts=fixed_now, clip=simple),
    }
    for f, record in db.items():
        (songs_dir / f).write_text("")
        if f != "F - No Sample.alc":
            sample = samples / (os.path.splitext(f)[0] + ".aiff")
            sample.write_text("")
            record[aa.REKORDBOX_LOCAL_SAMPLE_KEY] = str(sample)
    write_db(db)
    return tmp_path


def normalize(xml_text, tmp_path):
    """Indent (so a golden diff is readable) and hide the tmp dir."""
    root = ET.fromstring(xml_text.encode("utf-8"))
    ET.indent(root)
    return ET.tostring(root, encoding="unicode").replace(str(tmp_path), "<TMP>") + "\n"


def test_export_rekordbox_xml(export_env):
    out = export_env / "rekordbox.xml"
    er.export_rekordbox_xml(str(out))
    root = ET.parse(out).getroot()

    collection = root.find("COLLECTION")
    tracks = {t.get("Artist", ""): t for t in collection.findall("TRACK")}
    assert collection.get("Entries") == "4"
    assert sorted(tracks) == ["A", "B", "C", "D"]

    a = tracks["A"]
    name = a.get("Name", "")
    assert name.startswith("Old Favorite ")
    for suffix in ["[#disco]", "[#good]", "[#lyrics]", "[#8=A]", "[#p2]", "[#y98]", "[#t2]", "[#a0]", "[#n3]"]:
        assert suffix in name
    # added 1000 days ago: not new within 2 years, still active from the recent play
    assert "[#n2]" not in name and "[#o0]" not in name
    assert a.get("Tonality") == "8A"
    assert a.get("Comments") == "002"
    assert a.get("Year") == "1998"
    assert a.get("Location").startswith("file://localhost/")
    assert len(tracks["D"].findall("POSITION_MARK")) == 2

    playlists = {n.get("Name"): n for n in root.iter("NODE") if n.get("Type") == "1"}
    for name in ["All", "Sets", "New", "Top", "Top (SF)", "Active", "warmup", "disco", "good", "120 (5) BPM"]:
        assert name in playlists
    keys = lambda name: [t.get("Key") for t in playlists[name].findall("TRACK")]
    ids = {artist: t.get("TrackID") for artist, t in tracks.items()}
    assert keys("Active") == [ids["A"]]
    assert keys("warmup") == [ids["B"], ids["C"]]
    assert keys("All") == [ids[x] for x in "DBCA"]


def test_export_rekordbox_xml_golden(export_env):
    """Byte-for-byte snapshot of the whole export, to catch any refactoring drift.

    Regenerate with UPDATE_GOLDEN=1 after an intended output change.
    """
    out = export_env / "rekordbox.xml"
    er.export_rekordbox_xml(str(out))
    actual = normalize(out.read_text(encoding="utf-8"), export_env)
    if os.environ.get("UPDATE_GOLDEN"):
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as f:
            f.write(actual)
    with open(GOLDEN, encoding="utf-8") as f:
        assert actual == f.read()


def test_export_skips_track_without_clip(export_env):
    db = aa.read_db_file()
    db["B - New One.alc"]["clip"] = None
    aa.write_db_file(db)
    out = export_env / "rekordbox.xml"
    er.export_rekordbox_xml(str(out))
    collection = ET.parse(out).getroot().find("COLLECTION")
    assert collection is not None
    assert collection.get("Entries") == "3"
    assert "B" not in [t.get("Artist") for t in collection.findall("TRACK")]
