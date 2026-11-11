import datetime

import pytest

import ableton_aid as aa
from conftest import DAY, make_record


def test_tags():
    record = make_record(tags=["a"])
    assert aa.has_tag(record, "a")
    aa.add_tag(record, "b")
    aa.add_tag(record, "b")
    assert record["tags"] == ["a", "b"]
    aa.remove_tag(record, "a")
    aa.remove_tag(record, "missing")
    assert record["tags"] == ["b"]
    assert aa.get_tags({}) == []
    assert not aa.has_tag({}, "a")


def test_add_tag_without_tags_list():
    record = {"bpm": 120}
    aa.add_tag(record, "GOOD")
    assert record["tags"] == ["GOOD"]


def test_add_missing_tags_and_transfer():
    source = make_record(
        bpm=100, key="Am", tags=["vocal", "GOOD"], release_year_manual=1999, ts_list=[1.0]
    )
    target = {"bpm": 90}
    aa.transfer_shared_record_fields(source, target)
    # existing fields win, missing ones are copied, plays are not
    assert target == {
        "bpm": 90,
        "key": "Am",
        "release_year_manual": 1999,
        "tags": ["vocal", "GOOD"],
    }
    aa.add_missing_tags(target, ["GOOD", "new"])
    assert target["tags"] == ["vocal", "GOOD", "new"]


@pytest.mark.parametrize(
    "tags, expected", [([], True), (["x"], False), (["x_rekordbox"], False), (["SS"], False), (["GOOD"], True)]
)
def test_use_for_rekordbox(tags, expected):
    assert aa.use_for_rekordbox(make_record(tags=tags)) is expected


def test_is_vocal():
    assert aa.is_vocal(make_record(tags=["vocal"]))
    assert not aa.is_vocal(make_record())


def test_ts_helpers(fixed_now):
    record = make_record(ts_list=[fixed_now, fixed_now - DAY, fixed_now - 60])
    assert aa.get_ts_list(record) == sorted(record["ts_list"])
    assert aa.get_last_ts(record) == fixed_now
    assert aa.get_last_ts({}) == 0
    # two plays on the same day count once, keeping the later one
    assert aa.get_ts_list_date_limited(record) == [fixed_now - DAY, fixed_now]
    assert aa.get_ts_date_count(record) == 2
    assert aa.get_ts_date_count(record, ts_after=fixed_now - 3600) == 1

    aa.add_ts(record, fixed_now + 5)
    aa.add_ts(record, fixed_now + 5)
    assert record["ts_list"].count(fixed_now + 5) == 1
    new = {}
    aa.add_ts(new, 7.0)
    assert new["ts_list"] == [7.0]


def test_get_alc_ts():
    assert aa.get_alc_ts({}) == 0
    recent = aa.OLD_ALC_TS_CUTOFF + 10
    assert aa.get_alc_ts({"alc_ts": recent, "old_alc_ts": 5}) == recent
    old = aa.OLD_ALC_TS_CUTOFF - 10
    assert aa.get_alc_ts({"alc_ts": old, "old_alc_ts": 5}) == 5
    assert aa.get_alc_ts({"alc_ts": old}) == old
    assert aa.get_alc_or_last_ts({"alc_ts": 10, "ts_list": [20]}) == 20
    assert aa.get_alc_or_last_ts({"alc_ts": 30, "ts_list": [20]}) == 30


def test_get_release_year():
    assert aa.get_release_year({}) is None
    assert aa.get_release_year({"release_year_discogs": 2001}) == 2001
    assert aa.get_release_year({"release_year_discogs": 2001, "release_year_manual": 1995}) == 1995
    assert aa.get_release_year({"release_year_discogs": 2001, "release_year_manual": None}) == 2001


@pytest.mark.parametrize(
    "filter_bpm, bpm_range, bpm, expected",
    [
        (124, 2, 124, True),
        (124, 2, 126, True),
        (124, 2, 127, False),
        (124, 0, 62, True),  # half time
        (124, 0, 248, True),  # double time
        (90, 3, 180, True),
        (90, 3, 100, False),
    ],
)
def test_matches_bpm_filter(filter_bpm, bpm_range, bpm, expected):
    assert aa.matches_bpm_filter(filter_bpm, bpm_range, bpm) is expected


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("Artist - Track.alc", ("Artist", "Track")),
        ("JustATrack.alc", ("", "JustATrack")),
        ("A - B - C (Remix).als", ("A", "B - C (Remix)")),
        ("Röyksopp - Éclair.alc", ("Royksopp", "Eclair")),
        ("  Spaced  -  Out  .alc", ("Spaced", "Out")),
    ],
)
def test_get_artist_and_track(filename, expected):
    assert aa.get_artist_and_track(filename) == expected


def test_get_display_name():
    assert aa.get_display_name("A - B.alc", {}) == "A - B"
    assert aa.get_display_name("A - B.als", {}) == "A - B (ALS)"
    assert aa.get_display_name("A - B.alc", {"tags": ["vocal"]}) == "A - B [Vocal]"


def test_get_date_from_ts():
    ts = datetime.datetime(2023, 4, 5, 13, 0).timestamp()
    assert aa.get_date_from_ts(ts) == "2023-04-05"


def test_get_sample():
    assert aa.get_sample({"clip": {"sample": "../x.aiff"}}) == "../x.aiff"
    assert aa.get_sample({}) is None


def test_get_sample_with_none_clip():
    assert aa.get_sample({"clip": None}) is None
    assert aa.get_sample_unicode({"clip": None}) is None


def test_get_existing_rekordbox_sample(tmp_path):
    sample = tmp_path / "s.aiff"
    sample.write_bytes(b"")
    key = aa.REKORDBOX_LOCAL_SAMPLE_KEY
    assert aa.get_existing_rekordbox_sample({key: str(sample)}, key) == str(sample)
    assert aa.get_existing_rekordbox_sample({key: str(tmp_path / "gone")}, key) is None
    assert aa.get_existing_rekordbox_sample({}, key) is None


def test_extension_helpers():
    assert aa.is_alc_file("a.alc") and not aa.is_alc_file("a.als")
    assert aa.is_als_file("a.als")
    assert aa.is_ableton_file("x.mp3") and aa.is_ableton_file("x.alc")
    assert not aa.is_ableton_file("x.txt")
    assert aa.get_export_sample_path("A - B.alc", ".aiff", "/out") == "/out/A - B.aiff"


def test_get_key_from_keyfinder_cli(monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "check_output", lambda cmd: b"Am\n")
    assert aa.get_key_from_keyfinder_cli("s.mp3") == "Am"


def test_get_key_from_keyfinder_cli_converts_on_failure(tmp_path, monkeypatch):
    import subprocess

    sample = str(tmp_path / "s.flac")
    seen = []

    def check_output(cmd):
        seen.append(cmd[1])
        if cmd[1] == sample:
            raise subprocess.CalledProcessError(1, cmd)
        return b"C#m"

    monkeypatch.setattr(subprocess, "check_output", check_output)
    monkeypatch.setattr(subprocess, "check_call", lambda cmd: open(cmd[-1], "w").close())
    assert aa.get_key_from_keyfinder_cli(sample) == "C#m"
    assert seen == [sample, sample + ".temp.wav"]
    assert not (tmp_path / "s.flac.temp.wav").exists()


def test_get_key_from_keyfinder_cli_other_failure(monkeypatch):
    import subprocess

    def fail(cmd):
        raise subprocess.CalledProcessError(2, cmd)

    monkeypatch.setattr(subprocess, "check_output", fail)
    with pytest.raises(subprocess.CalledProcessError):
        aa.get_key_from_keyfinder_cli("s.mp3")


def test_get_discogs_token(tmp_path, monkeypatch):
    token_file = tmp_path / "token"
    monkeypatch.setattr(aa, "DISCOGS_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("DISCOGS_TOKEN", " from-env\n")
    assert aa.get_discogs_token() == "from-env"
    monkeypatch.delenv("DISCOGS_TOKEN")
    with pytest.raises(SystemExit):
        aa.get_discogs_token()
    token_file.write_text("from-file\n")
    assert aa.get_discogs_token() == "from-file"
