"""lyrics_server.py: the review page's API, on sidecars in a tmp lyrics dir.

No machine learning and no ffmpeg: the aligner and the audio helpers are faked.
"""

import os

import pytest
from fastapi.testclient import TestClient

import lyrics
import lyrics_server
from test_lyrics import FakeAligner

SONG = "Zedd & Foxes - Clarity (Acapella).alc"
NAME = "Zedd & Foxes - Clarity (Acapella).lyrics.json"


def _line(text, t0, step=0.5):
    words = [{"t0": t0 + i * step, "t1": t0 + (i + 1) * step, "text": w, "score": 0.9}
             for i, w in enumerate(text.split())]
    return lyrics.timed_line(text, words)


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "Zedd & Foxes - Clarity (Acapella).wav"
    path.write_bytes(b"RIFF....fake audio")
    return path


@pytest.fixture
def client(monkeypatch, sample):
    db = {SONG: {"tags": ["vocal"], "rekordbox_local_sample": str(sample)},
          "Zedd - Clarity.alc": {"tags": []}}
    monkeypatch.setattr(lyrics_server.state, "db_dict", db)
    monkeypatch.setattr(lyrics_server.state, "jobs", {})
    monkeypatch.setattr(lyrics_server.state, "peaks", {})
    monkeypatch.setattr(lyrics_server.state, "aligner_key", None)
    return TestClient(lyrics_server.app)


@pytest.fixture
def sidecar(sample):
    lines = [_line("High dive into frozen waves", 10.0), _line("Where the past comes back", 14.0)]
    s = lyrics.new_sidecar(SONG, str(sample), 200.0, lines, "High dive into frozen waves",
                           {"lyrics": "lrclib:7", "lrclib": {"artist": "Zedd", "track": "Clarity"}})
    lyrics.save_sidecar(s)
    return lyrics.read_sidecar(lyrics.sidecar_path(SONG))


@pytest.mark.parametrize("name", ["../x.lyrics.json", "a/b.lyrics.json", "x.json"])
def test_sidecar_file_rejects_paths_and_other_files(client, name):
    with pytest.raises(lyrics_server.HTTPException) as e:
        lyrics_server.sidecar_file(name)
    assert e.value.status_code == 400


def test_sidecar_file_unknown(client):
    with pytest.raises(lyrics_server.HTTPException) as e:
        lyrics_server.sidecar_file("Nope.lyrics.json")
    assert e.value.status_code == 404


def test_songs_lists_summaries(client, sidecar):
    [song] = client.get("/api/songs").json()
    assert song["file"] == NAME
    assert song["song"] == SONG
    assert (song["lines"], song["edited"], song["reviewed"]) == (2, 0, False)
    assert song["status"] == "ok"
    assert song["source"]["kind"] == "lrclib"


def test_get_lyrics(client, sidecar):
    got = client.get("/api/lyrics/" + NAME).json()
    assert got["status"] == "ok"
    assert got["has_vocals"] is False
    assert [l["text"] for l in got["lines"]] == ["High dive into frozen waves", "Where the past comes back"]


def test_clean_lines_sorts_rounds_and_drops_empty():
    lines = [
        {"words": [{"t0": 5.0, "t1": 5.0, "text": " b "}, {"t0": 4.12345, "t1": 4.5, "text": "a"}], "note": "x"},
        {"words": [{"t0": 1.0, "t1": 2.0, "text": "  "}]},  # no words left: dropped
        {"words": [{"t0": 1.0, "t1": 1.5, "text": "first"}]},
    ]
    out = lyrics_server.clean_lines(lines)
    assert [l["text"] for l in out] == ["first", "a b"]
    a, b = out[1]["words"]
    assert a["t0"] == 4.123
    assert b["t1"] == 5.01  # a word always has some length
    assert out[1]["note"] == "x"
    assert "note" not in out[0]


def test_put_marks_edits_and_keeps_removed(client, sidecar):
    lines = sidecar["lines"]
    edited = dict(lines[1], words=[dict(w) for w in lines[1]["words"]])
    edited["words"][0]["text"] = "Here"
    body = {"lines": [edited], "offset": 0.1234, "reviewed": False, "base_modified": sidecar["modified"]}
    got = client.put("/api/lyrics/" + NAME, json=body)
    assert got.status_code == 200
    saved = lyrics.read_sidecar(lyrics.sidecar_path(SONG))
    assert saved["offset"] == 0.123
    [line] = saved["lines"]
    assert line["text"].startswith("Here") and line["edited"] is True
    # Both automatic lines are gone from the page: the first deleted, the second replaced.
    assert [r["text"] for r in saved["removed"]] == ["High dive into frozen waves", "Where the past comes back"]


def test_put_new_reference_becomes_manual(client, sidecar):
    body = {"lines": sidecar["lines"], "reference": "Typed by hand"}
    got = client.put("/api/lyrics/" + NAME, json=body).json()
    assert got["source_info"]["kind"] == "manual"
    assert lyrics.read_sidecar(lyrics.sidecar_path(SONG))["reference"] == "Typed by hand"


def test_put_refuses_a_stale_edit(client, sidecar):
    body = {"lines": sidecar["lines"], "base_modified": sidecar["modified"] - 60}
    assert client.put("/api/lyrics/" + NAME, json=body).status_code == 409


def test_delete_updates_index(client, sidecar):
    assert client.delete("/api/lyrics/" + NAME).json() == {"ok": True}
    assert not os.path.exists(lyrics.sidecar_path(SONG))
    assert lyrics.write_index()["songs"] == []


def test_audio_plays_the_timeline_and_missing_sample_is_404(client, sidecar, sample, monkeypatch):
    import lyrics_align

    monkeypatch.setattr(lyrics_align, "timeline_path", lambda s: s)
    got = client.get("/api/audio/" + NAME)
    assert got.status_code == 200
    assert got.content == sample.read_bytes()
    os.remove(sample)
    assert client.get("/api/audio/" + NAME).status_code == 404


def test_playable_converts_aiff_once(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, check):
        calls.append(cmd)
        with open(cmd[-1], "wb") as f:
            f.write(b"flac")

    monkeypatch.setattr(lyrics_server.subprocess, "run", fake_run)
    wav = tmp_path / "a.wav"
    assert lyrics_server.playable(str(wav)) == str(wav)
    aiff = tmp_path / "a.aiff"
    aiff.write_bytes(b"FORM")
    out = lyrics_server.playable(str(aiff))
    assert out.endswith("play.flac") and os.path.isfile(out)
    assert lyrics_server.playable(str(aiff)) == out
    assert len(calls) == 1


def test_realign_times_one_line(client, sidecar, monkeypatch):
    monkeypatch.setattr(lyrics_server, "align_audio", lambda s: s["sample"])
    monkeypatch.setattr(lyrics_server, "get_aligner", lambda audio: FakeAligner())
    got = client.post("/api/realign/" + NAME, json={"text": "  Where   the past ", "a": -1.0, "b": 4.0}).json()
    assert got["text"] == "Where the past"
    assert got["t0"] == 0.0 and got["t1"] == 4.0
    assert client.post("/api/realign/" + NAME, json={"text": "?!", "a": 0, "b": 1}).status_code == 400


def test_get_aligner_is_reused_until_the_audio_changes(tmp_path, monkeypatch):
    import lyrics_align

    made = []
    monkeypatch.setattr(lyrics_align, "Aligner", lambda audio: made.append(audio) or object())
    monkeypatch.setattr(lyrics_server.state, "aligner_key", None)
    audio = tmp_path / "v.wav"
    audio.write_bytes(b"x")
    first = lyrics_server.get_aligner(str(audio))
    assert lyrics_server.get_aligner(str(audio)) is first
    os.utime(audio, (1, 1))
    assert lyrics_server.get_aligner(str(audio)) is not first
    assert len(made) == 2


def test_search(client, sidecar):
    assert client.get("/api/search", params={"q": "c"}).json() == []
    got = client.get("/api/search", params={"q": "clarity"}).json()
    assert [r["song"] for r in got] == ["Zedd - Clarity.alc", SONG]
    plain, acapella = got
    assert (plain["has_lyrics"], plain["has_sample"], plain["vocal_only"]) == (False, False, False)
    assert (acapella["has_lyrics"], acapella["has_sample"], acapella["vocal_only"]) == (True, True, True)


def test_add_errors(client, sidecar):
    assert client.post("/api/add", json={"song": "Nope.alc"}).status_code == 404
    assert client.post("/api/add", json={"song": SONG}).status_code == 409
    assert client.get("/api/jobs/123").status_code == 404


def test_run_job_writes_the_sidecar(client, sample, monkeypatch):
    def fake_create(song, sample, reference, source, separate, log, tags):
        log("made")
        return lyrics.new_sidecar(song, sample, 100.0, [_line("Hello there", 1.0)], reference, source)

    monkeypatch.setattr(lyrics, "create", fake_create)
    lyrics_server.state.jobs["1"] = {"id": "1", "song": SONG, "state": "running", "log": [], "file": None}
    lyrics_server.run_job("1", lyrics_server.Add(song=SONG, reference="Hello there"))
    job = client.get("/api/jobs/1").json()
    assert job["state"] == "done" and job["file"] == NAME and job["log"] == ["made"]
    assert lyrics.read_sidecar(lyrics.sidecar_path(SONG))["source"] == {"lyrics": "manual"}


def test_run_job_reports_failure(client, monkeypatch):
    lyrics_server.state.jobs["2"] = {"id": "2", "song": "Zedd - Clarity.alc", "state": "running", "log": [],
                                     "file": None}
    lyrics_server.run_job("2", lyrics_server.Add(song="Zedd - Clarity.alc"))
    job = lyrics_server.state.jobs["2"]
    assert job["state"] == "failed"
    assert "no exported sample" in job["log"][-1]


def test_load(songs_dir, write_db, db_dict, monkeypatch):
    write_db(db_dict)
    monkeypatch.setattr(lyrics_server.state, "db_dict", {})
    lyrics_server.load(str(songs_dir))
    assert set(lyrics_server.state.db_dict) == set(db_dict)


def test_load_without_db(tmp_path):
    with pytest.raises(SystemExit):
        lyrics_server.load(str(tmp_path))


def test_peaks_are_scaled_and_cached(client, sidecar, monkeypatch):
    import types

    import numpy as np

    import lyrics_align

    monkeypatch.setattr(lyrics_align, "timeline_path", lambda s: s)
    # 0.03 s at 8 kHz: three 1/100 s windows, quiet, loud, silent
    pcm = np.concatenate([np.full(80, 0.1), np.full(80, -0.8), np.zeros(80)]).astype(np.float32)
    calls = []

    def run(cmd, capture_output, check):
        calls.append(cmd)
        return types.SimpleNamespace(stdout=pcm.tobytes())

    monkeypatch.setattr(lyrics_server.subprocess, "run", run)
    got = client.get("/api/peaks/" + NAME).json()
    assert got["rate"] == 100
    quiet, loud, silent = got["peaks"]
    assert loud == 255 and silent == 0 and 0 < quiet < 255
    assert client.get("/api/peaks/" + NAME).json() == got
    assert len(calls) == 1
