import datetime
import subprocess

import pytest
from fastapi.testclient import TestClient

import ableton_aid as aa
import song_server
from conftest import make_record


@pytest.fixture
def client(songs_dir, db_dict, monkeypatch):
    monkeypatch.setattr(song_server.state, "db_dict", db_dict)
    monkeypatch.setattr(song_server.state, "order", sorted(db_dict))
    monkeypatch.setattr(song_server.state, "last_backup", 0.0)
    return TestClient(song_server.app)


def test_song_view(client, db_dict, fixed_now):
    view = song_server.song_view("A - Old Favorite.alc")
    assert view["id"] == "A - Old Favorite.alc"
    assert view["name"] == "A - Old Favorite"
    assert view["ext"] == "ALC"
    assert (view["key"], view["camelot"], view["camelot_num"]) == ("8A", "8A", 8)
    assert view["plays"] == 2
    assert view["good"] and not view["vocal"]
    assert view["recency"] == aa.get_alc_or_last_ts(db_dict["A - Old Favorite.alc"])
    epoch = datetime.date(1970, 1, 1).toordinal()
    assert view["play_days"][-1] == datetime.date.fromtimestamp(fixed_now - 30 * 86400 + 60).toordinal() - epoch
    assert view["has_sample"] is False


def test_song_view_sparse_record(client):
    view = song_server.song_view("E - No Key.alc")
    assert (view["key"], view["camelot"], view["camelot_num"]) == ("", "", None)
    assert view["sample_ts"] == 0
    assert song_server.song_view("F - Missing Clip.alc")["sample_ts"] == 0


def test_known_tags(client, db_dict):
    db_dict["B - New One.alc"]["tags"] = ["zz_custom", "x", "northfield"]
    tags = song_server.known_tags()
    assert tags[-1] == "zz_custom"
    assert "GOOD" in tags
    assert "x" not in tags and "northfield" not in tags


def test_index_and_data(client):
    assert client.get("/").status_code == 200
    data = client.get("/api/data").json()
    assert [s["id"] for s in data["songs"]] == sorted(song_server.state.db_dict)
    assert data["camelot_dict"]["Am"] == "8A"


def test_edit_tag(client, songs_dir):
    resp = client.post("/api/tag", json={"id": "B - New One.alc", "tag": " DISCO ", "action": "add"})
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["DISCO"]
    assert aa.read_db_file()["B - New One.alc"]["tags"] == ["DISCO"]
    resp = client.post("/api/tag", json={"id": "B - New One.alc", "tag": "DISCO", "action": "remove"})
    assert resp.json()["tags"] == []


@pytest.mark.parametrize(
    "body, status",
    [
        ({"id": "nope", "tag": "x", "action": "add"}, 404),
        ({"id": "B - New One.alc", "tag": "  ", "action": "add"}, 400),
        ({"id": "B - New One.alc", "tag": "x", "action": "toggle"}, 400),
    ],
)
def test_edit_tag_errors(client, body, status):
    assert client.post("/api/tag", json=body).status_code == status


def test_touch(client, fixed_now):
    before = client.get("/api/data").json()["songs"]
    resp = client.post("/api/touch", json={"id": "C - Vocal.alc"})
    assert resp.json()["plays"] == 1
    assert fixed_now in aa.read_db_file()["C - Vocal.alc"]["ts_list"]
    assert client.post("/api/touch", json={"id": "nope"}).status_code == 404
    assert len(before) == 6


def test_save_db_rotates_at_most_every_few_minutes(client, songs_dir, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(song_server.time, "time", lambda: now[0])
    aa.write_db_file({"old": {}})
    song_server.save_db()
    assert (songs_dir / "database.json.1").exists()
    song_server.save_db()
    assert not (songs_dir / "database.json.2").exists()
    now[0] += song_server.BACKUP_MIN_INTERVAL_SEC + 1
    song_server.save_db()
    assert (songs_dir / "database.json.2").exists()
    assert set(aa.read_db_file()) == set(song_server.state.db_dict)


def test_reveal_and_play(client, db_dict, songs_dir, monkeypatch):
    revealed, opened = [], []
    monkeypatch.setattr(aa, "reveal_file", revealed.append)
    monkeypatch.setattr(subprocess, "call", lambda cmd, **kw: opened.append(cmd))
    sample = songs_dir / "s.aiff"
    sample.write_text("")
    db_dict["B - New One.alc"][aa.REKORDBOX_LOCAL_SAMPLE_KEY] = str(sample)
    db_dict["B - New One.alc"]["clip"] = {"sample": "s.aiff"}

    assert client.post("/api/reveal", json={"id": "B - New One.alc"}).status_code == 200
    assert revealed == [str(sample)]
    assert client.post("/api/reveal", json={"id": "A - Old Favorite.alc"}).status_code == 404
    assert client.post("/api/play", json={"id": "B - New One.alc"}).status_code == 200
    assert opened == [["open", "s.aiff"]]
    assert client.post("/api/play", json={"id": "A - Old Favorite.alc"}).status_code == 404


def test_copy(client, songs_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "call", lambda cmd, **kw: calls.append((cmd, kw)))
    assert client.post("/api/copy", json={"id": "B - New One.alc"}).status_code == 404  # not on disk
    (songs_dir / "B - New One.alc").write_text("")
    assert client.post("/api/copy", json={"id": "B - New One.alc"}).status_code == 200
    assert len(calls) == 1


@pytest.mark.xfail(strict=True, reason="bug: the path is pasted into a shell command string")
def test_copy_passes_path_without_shell(client, db_dict, songs_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "call", lambda cmd, **kw: calls.append((cmd, kw)))
    name = 'Quote " and $(dollar).alc'
    db_dict[name] = make_record()
    (songs_dir / name).write_text("")
    client.post("/api/copy", json={"id": name})
    cmd, kw = calls[0]
    assert not kw.get("shell")
    assert cmd[-1] == str(songs_dir / name)


def test_load(songs_dir, db_dict, monkeypatch):
    aa.write_db_file(db_dict)
    (songs_dir / "A - Old Favorite.alc").write_text("")
    monkeypatch.setattr(song_server.state, "db_dict", {})
    song_server.load(str(songs_dir))
    assert song_server.state.order == ["A - Old Favorite.alc"]
    assert len(song_server.state.db_dict) == 6


def test_load_without_db(tmp_path):
    with pytest.raises(SystemExit):
        song_server.load(str(tmp_path))
