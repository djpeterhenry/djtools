import types

import pytest

import ableton_aid as aa
import actions
from conftest import DAY, make_record


@pytest.mark.parametrize(
    "track, expected",
    [
        ("Track (Original Mix)", "Track"),
        ("Track (feat. Someone) (Radio Edit)", "Track"),
        ("Track (Acapella)", "Track"),
        ("Track (Some Remix)", None),
        ("Track", None),
    ],
)
def test_simplify_track(track, expected):
    assert actions._simplify_track(track) == expected


@pytest.mark.parametrize("value, expected", [("1999", 1999), (2001, 2001), (0, None), ("0", None), (None, None), ("x", None)])
def test_as_year(value, expected):
    assert actions._as_year(value) == expected


def test_record_first_year():
    assert actions._record_first_year({}) is None
    ts_2019 = aa.get_ts_for(2019, 5, 1)
    ts_2022 = aa.get_ts_for(2022, 5, 1)
    assert actions._record_first_year({"alc_ts": ts_2019, "ts_list": [ts_2022]}) == 2019
    assert actions._record_first_year({"ts_list": [ts_2022]}) == 2022


class FakeDiscogs:
    """Answers search(track, artist=..., type=...) from a canned table."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def search(self, track, artist=None, type=None):
        self.calls.append((track, type))
        return self.answers.get((track, type), [])


def master(year):
    return types.SimpleNamespace(year=year)


def release(year, labels=(), master_year=None):
    return types.SimpleNamespace(
        year=year,
        labels=[types.SimpleNamespace(name=n) for n in labels],
        master=master(master_year) if master_year is not None else None,
    )


def test_discogs_master_hit_needs_one_request():
    d = FakeDiscogs({("T", "master"): [master("1995")]})
    assert actions._discogs_earliest_year(d, "A", "T") == (1995, None)
    assert d.calls == [("T", "master")]


def test_discogs_late_master_falls_back_to_release():
    d = FakeDiscogs(
        {
            ("T", "master"): [master("2010")],
            ("T", "release"): [release(2012, ["Label"], master_year=1999)],
        }
    )
    assert actions._discogs_earliest_year(d, "A", "T", not_after=2000) == (1999, ["Label"])


def test_discogs_release_earlier_than_master():
    d = FakeDiscogs({("T", "master"): [master(2010)], ("T", "release"): [release(2003, ["L"])]})
    assert actions._discogs_earliest_year(d, "A", "T", not_after=2000) == (2003, ["L"])


def test_discogs_simplified_retry():
    d = FakeDiscogs({("T", "release"): [release(2001, ["L"])]})
    assert actions._discogs_earliest_year(d, "A", "T (Original Mix)") == (2001, ["L"])
    assert ("T", "release") in d.calls


def test_discogs_nothing_found():
    assert actions._discogs_earliest_year(FakeDiscogs({}), "A", "T") == (None, None)


def test_get_suspicious_discogs_years():
    ts_2010 = aa.get_ts_for(2010, 1, 1)
    db = {
        "small gap": {"release_year_discogs": 2012, "alc_ts": ts_2010},
        "big gap": {"release_year_discogs": 2020, "alc_ts": ts_2010},
        "fine": {"release_year_discogs": 2009, "alc_ts": ts_2010},
        "manual": {"release_year_discogs": 2020, "release_year_manual": 2008, "alc_ts": ts_2010},
        "no history": {"release_year_discogs": 2020},
        "no year": {"alc_ts": ts_2010},
    }
    assert actions._get_suspicious_discogs_years(db) == [(10, 2010, "big gap"), (2, 2010, "small gap")]


def test_get_missing_release_dates(db_dict):
    db_dict["A - Old Favorite.alc"]["release_year_manual"] = 1999
    db_dict["C - Vocal.alc"]["release_year_discogs"] = 0
    by_plays = actions._get_missing_release_dates(db_dict)
    assert by_plays[0] == "B - New One.alc"
    assert "A - Old Favorite.alc" not in by_plays
    assert "D - Hidden.alc" not in by_plays  # x tagged
    assert "C - Vocal.alc" in by_plays
    by_date = actions._get_missing_release_dates(db_dict, order_by_date=True)
    assert by_date == aa.generate_date_plus_alc(by_date, db_dict)


def test_cue_to_tracklist(tmp_path):
    cue = tmp_path / "set.cue"
    cue.write_text(
        'TITLE "Mix"\n'
        "  TRACK 01 AUDIO\n"
        '\tTITLE "First Song [8A]"\n'
        '\tPERFORMER "Artist One"\n'
        "\tINDEX 01 00:00:00\n"
        "  TRACK 02 AUDIO\n"
        '\tTITLE "Second [3B]"\n'
        '\tPERFORMER "Artist Two"\n'
        "\tINDEX 01 05:10:00\n"
    )
    out = tmp_path / "out.txt"
    actions.cue_to_tracklist(str(cue), str(out))
    assert out.read_text() == "[00:00:00] Artist One - First Song\n[05:10:00] Artist Two - Second\n"


# ----------------------------------------------------- db editing commands


def test_rename_and_remove_tag(write_db):
    write_db({"a": make_record(tags=["old", "keep"]), "b": make_record(tags=[])})
    actions.rename_tag("old", "new")
    assert aa.read_db_file()["a"]["tags"] == ["new", "keep"]
    actions.remove_tag(" keep ")
    assert aa.read_db_file()["a"]["tags"] == ["new"]


@pytest.mark.xfail(strict=True, reason="bug: renaming onto an existing tag duplicates it")
def test_rename_tag_does_not_duplicate(write_db):
    write_db({"a": make_record(tags=["old", "new"])})
    actions.rename_tag("old", "new")
    assert aa.read_db_file()["a"]["tags"] == ["new"]


def test_edit_bpm(songs_dir, write_db, monkeypatch):
    (songs_dir / "a.alc").write_text("")
    write_db({"a.alc": make_record(bpm=100)})
    monkeypatch.setattr(aa, "get_int", lambda prompt: 128)
    actions.edit_bpm("a.alc")
    assert aa.read_db_file()["a.alc"]["bpm"] == 128


@pytest.mark.xfail(strict=True, reason="bug: editing a file not yet in the db raises NameError")
def test_edit_bpm_new_file(songs_dir, write_db, monkeypatch):
    (songs_dir / "new.alc").write_text("")
    write_db({})
    monkeypatch.setattr(aa, "get_int", lambda prompt: 128)
    actions.edit_bpm("new.alc")
    assert aa.read_db_file()["new.alc"]["bpm"] == 128


def test_add_bpms(songs_dir, write_db, monkeypatch):
    for name in ["a.alc", "b.alc", "c.alc"]:
        (songs_dir / name).write_text("")
    write_db({"a.alc": make_record()})
    answers = iter([111, None])
    monkeypatch.setattr(aa, "get_int", lambda prompt: next(answers))
    actions.add_bpms()
    db = aa.read_db_file()
    assert db["b.alc"] == {"bpm": 111, "tags": []}
    assert "c.alc" not in db


def test_add_keys(make_alc, write_db, monkeypatch):
    fn = make_alc()
    write_db({fn: {"bpm": 120, "tags": []}})
    monkeypatch.setattr(aa, "get_key_from_keyfinder_cli", lambda path: "Am")
    actions.add_keys()
    assert aa.read_db_file()[fn]["key"] == "Am"


@pytest.mark.xfail(strict=True, reason="bug: a song whose sample is missing crashes add_keys")
def test_add_keys_skips_missing_sample(make_alc, write_db, monkeypatch):
    fn = make_alc(create_sample=False)
    write_db({fn: {"bpm": 120, "tags": []}})
    monkeypatch.setattr(aa, "get_key_from_keyfinder_cli", lambda path: "Am")
    actions.add_keys()


def test_transfer_missing(songs_dir, write_db, monkeypatch):
    (songs_dir / "A - Track (Edit).alc").write_text("")
    write_db(
        {
            "A - Track.alc": make_record(bpm=99, key="5A", ts_list=[1.0, 2.0], tags=["GOOD"]),
            "A - Track (Edit).alc": {"ts_list": [3.0]},
        }
    )
    monkeypatch.setattr(aa, "get_int", lambda prompt: 0)
    actions.transfer_missing()
    db = aa.read_db_file()
    assert "A - Track.alc" not in db
    assert db["A - Track (Edit).alc"] == {"ts_list": [1.0, 2.0, 3.0], "bpm": 99, "key": "5A", "tags": ["GOOD"]}


@pytest.mark.xfail(strict=True, reason="bug: an out of range choice raises IndexError")
def test_transfer_missing_bad_choice(songs_dir, write_db, monkeypatch):
    (songs_dir / "A - Track (Edit).alc").write_text("")
    write_db({"A - Track.alc": make_record(), "A - Track (Edit).alc": {}})
    monkeypatch.setattr(aa, "get_int", lambda prompt: 9)
    actions.transfer_missing()
    assert "A - Track.alc" in aa.read_db_file()


def test_transfer_timestamps_and_other(songs_dir, write_db, tmp_path):
    write_db({"a": {"ts_list": [1.0]}, "b": {"ts_list": [2.0]}})
    actions.transfer_timestamps("a", "b")
    assert aa.read_db_file()["b"]["ts_list"] == [1.0, 2.0]

    other = tmp_path / "other.json"
    other.write_text('{"a": {"ts_list": [5.0, 1.0]}, "zzz": {}}')
    actions.transfer_other(str(other))
    assert aa.read_db_file()["a"]["ts_list"] == [1.0, 5.0]


def test_remove_recent_timestamps(write_db, fixed_now):
    write_db({"a": {"ts_list": [fixed_now - DAY, fixed_now - 60]}, "b": {}})
    actions.remove_recent_timestamps(5)
    db = aa.read_db_file()
    assert db["a"]["ts_list"] == [fixed_now - DAY]
    assert db["b"]["ts_list"] == []


def test_clear_release_date_none_values(write_db):
    write_db({"a": {"release_year_discogs": None}, "b": {"release_year_discogs": 2000}})
    actions.clear_release_date_none_values()
    db = aa.read_db_file()
    assert db == {"a": {}, "b": {"release_year_discogs": 2000}}


def test_release_dates_manual(write_db, monkeypatch):
    write_db({"Foo - Bar.alc": make_record(), "Other.alc": make_record()})
    monkeypatch.setattr(aa, "get_int", lambda prompt: 1987)
    actions.release_dates_manual(search_terms=["foo"])
    db = aa.read_db_file()
    assert db["Foo - Bar.alc"]["release_year_manual"] == 1987
    assert "release_year_manual" not in db["Other.alc"]


def test_release_dates_discogs(write_db, monkeypatch, fixed_now):
    write_db(
        {
            "A - Played.alc": make_record(ts_list=[fixed_now]),
            "Unparseable.alc": make_record(ts_list=[fixed_now]),
            "B - Never Played.alc": make_record(),
        }
    )
    fake = FakeDiscogs({("Played", "master"): [master(2001)]})
    monkeypatch.setattr(actions.discogs_client, "Client", lambda *a, **k: fake)
    actions.release_dates_discogs()
    db = aa.read_db_file()
    assert db["A - Played.alc"]["release_year_discogs"] == 2001
    assert db["Unparseable.alc"]["release_year_discogs"] is None
    assert "release_year_discogs" not in db["B - Never Played.alc"]


@pytest.mark.xfail(strict=True, reason="bug: an alc whose sample is missing raises AttributeError")
def test_demucs_missing_sample(make_alc, write_db):
    fn = make_alc(create_sample=False)
    write_db({fn: make_record()})
    actions.demucs(fn)


def test_demucs_vocal_sample_path(songs_dir):
    assert actions.demucs_vocal_sample_path("A - B.alc") == str(
        songs_dir.parent / "Samples" / "Demucs" / "A - B.alc.vocals.wav"
    )
