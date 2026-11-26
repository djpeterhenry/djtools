"""lyrics_align.py without the machine learning: probing, the timeline decode and the caches.

ffprobe / ffmpeg / demucs are fakes; Whisper is only reached through its cache.
"""

import json
import os
import subprocess
import types

import pytest

import lyrics
import lyrics_align as la


def _probe_result(streams):
    return types.SimpleNamespace(stdout=json.dumps({"streams": streams}))


@pytest.mark.parametrize(
    "streams, expected",
    [
        ([{"start_time": "0.025057", "sample_rate": "44100"}], (0.025057, 44100)),
        ([{"start_time": "N/A", "sample_rate": "48000"}], (0.0, 48000)),
        ([{}], (0.0, 0)),
        ([], (0.0, 0)),
    ],
)
def test_probe_audio(monkeypatch, streams, expected):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _probe_result(streams))
    assert la.probe_audio("x.mp3") == expected


def test_sample_shift_only_for_gapless_mp3(monkeypatch):
    monkeypatch.setattr(la, "probe_audio", lambda path: (1105 / 44100, 44100))
    assert la.sample_shift("a.mp3") == pytest.approx(2257 / 44100)
    assert la.sample_shift("a.wav") == 0.0


def test_timeline_path_plain_files_are_used_as_they_are(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no decode for a wav"))
    for name in ["a.wav", "a.AIFF", "a.aif"]:
        assert la.timeline_path(str(tmp_path / name)) == str(tmp_path / name)


@pytest.fixture
def mp3(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"ID3 fake mp3")
    return str(path)


def _fake_ffmpeg(calls):
    def run(cmd, check):
        calls.append(cmd)
        with open(cmd[-1], "wb") as f:
            f.write(b"decoded")

    return run


def test_timeline_path_pads_a_gapless_mp3_once(mp3, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_ffmpeg(calls))
    monkeypatch.setattr(la, "probe_audio", lambda path: (1105 / 44100, 44100))
    out = la.timeline_path(mp3)
    assert out == os.path.join(la.cache_dir(mp3), "timeline.flac")
    assert os.path.isfile(out)
    [cmd] = calls
    assert cmd[cmd.index("-af") + 1] == "adelay=2257S:all=1"
    assert la.timeline_path(mp3) == out  # cached
    assert len(calls) == 1


def test_timeline_path_plain_mp3_is_not_padded(mp3, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", _fake_ffmpeg(calls))
    monkeypatch.setattr(la, "probe_audio", lambda path: (0.0, 44100))
    la.timeline_path(mp3)
    assert "-af" not in calls[0]


def test_vocals_path_runs_demucs_once(tmp_path, monkeypatch):
    sample = tmp_path / "song.wav"
    sample.write_bytes(b"RIFF fake")
    calls = []

    def run(cmd, check):
        calls.append(cmd)
        out_dir = cmd[cmd.index("-o") + 1]
        stem_dir = os.path.join(out_dir, "htdemucs", "song")
        os.makedirs(stem_dir)
        with open(os.path.join(stem_dir, "vocals.wav"), "wb") as f:
            f.write(b"vocals")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(la, "_mps", lambda: False)
    out = la.vocals_path(str(sample))
    assert out == os.path.join(la.cache_dir(str(sample)), "vocals-timeline.wav")
    with open(out, "rb") as f:
        assert f.read() == b"vocals"
    assert la.vocals_path(str(sample)) == out
    assert len(calls) == 1
    assert calls[0][:4] == ["demucs", "--two-stems", "vocals", "-n"]


def test_transcribe_uses_its_cache(tmp_path, monkeypatch):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF fake")
    segments = [{"start": 1.0, "end": 2.0, "text": "Hello", "words": []}]
    lyrics.write_json_atomic(
        os.path.join(la.cache_dir(str(audio)), "whisper-en-nc.json"),
        {"model": la.WHISPER_MODEL, "segments": segments},
    )
    # None in sys.modules makes `import mlx_whisper` fail: a cache hit never gets there.
    monkeypatch.setitem(__import__("sys").modules, "mlx_whisper", None)
    assert la.transcribe(str(audio), "en") == segments


def test_transcribe_redoes_another_models_cache(tmp_path, monkeypatch):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF fake")
    path = os.path.join(la.cache_dir(str(audio)), "whisper-auto-nc.json")
    lyrics.write_json_atomic(path, {"model": "old-model", "segments": []})
    raw = [{"start": 0.5, "end": 1.5, "text": " Hi", "words": [{"word": "Hi"}], "tokens": [1, 2]}]
    fake = types.SimpleNamespace(transcribe=lambda audio, **kw: {"segments": raw})
    monkeypatch.setitem(__import__("sys").modules, "mlx_whisper", fake)
    got = la.transcribe(str(audio))
    assert got == [{"start": 0.5, "end": 1.5, "text": " Hi", "words": [{"word": "Hi"}]}]
    with open(path) as f:
        assert json.load(f) == {"model": la.WHISPER_MODEL, "segments": got}
