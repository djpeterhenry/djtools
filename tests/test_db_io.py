import json

import pytest

import ableton_aid as aa


def test_round_trip_unicode(songs_dir):
    db = {"Röyksopp - Éclair.alc": {"bpm": 120, "tags": ["ß"]}}
    aa.write_db_file(db)
    assert aa.read_db_file() == db
    # stored as real utf-8, not \u escapes
    assert "Röyksopp" in (songs_dir / aa.DATABASE_JSON).read_text(encoding="utf8")


def test_write_rotates_backups(songs_dir):
    aa.write_db_file({"v": 1})
    aa.write_db_file({"v": 2})
    aa.write_db_file({"v": 3})
    assert aa.read_db_file() == {"v": 3}
    assert json.loads((songs_dir / "database.json.1").read_text()) == {"v": 2}
    assert json.loads((songs_dir / "database.json.2").read_text()) == {"v": 1}


def test_rotate_file_caps_at_max(songs_dir):
    for n in (49, 50):
        (songs_dir / "f.{}".format(n)).write_text(str(n))
    (songs_dir / "f").write_text("current")
    aa.rotate_file("f")
    assert not (songs_dir / "f").exists()
    assert (songs_dir / "f.1").read_text() == "current"
    assert (songs_dir / "f.50").read_text() == "49"
    assert not (songs_dir / "f.51").exists()


@pytest.mark.xfail(strict=True, reason="bug: a failed write leaves no database.json")
def test_failed_write_keeps_current_db(songs_dir):
    aa.write_db_file({"v": 1})
    with pytest.raises(TypeError):
        aa.write_db_file({"v": {1, 2}})  # sets aren't JSON serializable
    assert aa.read_db_file() == {"v": 1}


def test_get_missing(songs_dir):
    (songs_dir / "here.alc").write_bytes(b"")
    aa.write_db_file({"here.alc": {}, "gone.alc": {}})
    assert aa.get_missing() == ["gone.alc"]
