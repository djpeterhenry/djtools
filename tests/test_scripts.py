"""The small command-line wrappers: silence, convert_to_aiff, demucs, server_util.

External programs (ffmpeg, demucs, lsof) are replaced by fakes that record the
command they were given.
"""

import gzip
import os
import signal
import subprocess
import types
import xml.etree.ElementTree as ET

import pytest

import ableton_aid as aa
import convert_to_aiff
import demucs
import server_util
import silence
from conftest import make_record

# ---------------------------------------------------------------- silence


@pytest.mark.parametrize("seconds, label", [(5, "5s"), (5.0, "5s"), (2.5, "2.5s")])
def test_seconds_label(seconds, label):
    assert silence._seconds_label(seconds) == label


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """ffmpeg that writes its last argument (the output) and records the call."""
    calls = []

    def check_call(cmd):
        calls.append(cmd)
        with open(cmd[-1], "wb") as f:
            f.write(b"silenced audio")
        return 0

    monkeypatch.setattr(subprocess, "check_call", check_call)
    return calls


def test_silence_writes_sample_clip_and_record(make_alc, write_db, fake_ffmpeg, songs_dir):
    alc = make_alc("A - Song.alc", warp_markers=((0.25, 0.0), (8.25, 16.0)))
    write_db({alc: make_record(bpm=124, key="8A", tags=["GOOD"], release_year_manual=1999)})

    silence.silence(alc, seconds=2.5)

    [cmd] = fake_ffmpeg
    assert cmd[cmd.index("-af") + 1] == "adelay=2500:all=1"
    new_sample = cmd[-1]
    assert new_sample.endswith("Samples/Imported/A - Song (2.5s silence).aiff")

    new_alc = "A - Song (2.5s silence).alc"
    clip = aa.get_audioclip_from_alc(new_alc)
    assert [m["sec_time"] for m in clip["warp_markers"]] == [2.75, 10.75]
    assert [m["beat_time"] for m in clip["warp_markers"]] == [0.0, 16.0]
    assert os.path.samefile(clip["sample"], new_sample)

    xml = ET.fromstring(gzip.open(new_alc).read())
    assert xml.find(".//DefaultDuration").get("Value") == str(441000 + int(2.5 * 44100))

    db = aa.read_db_file()
    assert db[new_alc] == {"bpm": 124, "key": "8A", "release_year_manual": 1999, "tags": ["GOOD"]}


@pytest.mark.parametrize(
    "setup, seconds, message",
    [
        ("none", 5, "not found in the database"),
        ("ok", 0, "must be positive"),
        ("old_format", 5, "sample_filepath_is_new_format"),
        ("no_sample", 5, "Could not read an audio clip"),
    ],
)
def test_silence_refuses(make_alc, write_db, fake_ffmpeg, capsys, setup, seconds, message):
    alc = make_alc(
        "A - Song.alc", new_format=setup != "old_format", create_sample=setup != "no_sample"
    )
    write_db({} if setup == "none" else {alc: make_record()})
    silence.silence(alc, seconds=seconds)
    assert message in capsys.readouterr().out
    assert fake_ffmpeg == []


# ---------------------------------------------------------------- convert_to_aiff


def test_convert_filename(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "check_call", calls.append)
    convert_to_aiff.convert_filename("dir/Song.mp3")
    convert_to_aiff.convert_filename("dir/Song.mp3", pcm_16bit=True)
    plain, pcm = calls
    assert plain[-1] == "dir/Song (from .mp3).aiff"
    assert "-c:a" not in plain
    # big-endian: little-endian pcm in an .aiff is the byte-swapped AIFF-C CDJs refuse
    assert pcm[pcm.index("-c:a") + 1] == "pcm_s16be"


def test_convert_folder_only_mp3s(tmp_path, monkeypatch):
    for name in ["a.mp3", "b.MP3", "c.wav", "d.aiff"]:
        (tmp_path / name).write_bytes(b"")
    done = []
    monkeypatch.setattr(convert_to_aiff, "convert_filename", lambda f, pcm_16bit: done.append(os.path.basename(f)))
    convert_to_aiff.convert_folder(str(tmp_path))
    assert sorted(done) == ["a.mp3", "b.MP3"]


# ---------------------------------------------------------------- demucs


def test_demucs_command_and_result(monkeypatch):
    calls = []

    def run(cmd, check):
        calls.append(cmd)
        if "bad.wav" in cmd:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", run)
    assert demucs.demucs("good.wav", "/out") is True
    assert calls[0] == ["demucs", "-d", "cpu", "good.wav", "--out", "/out", "--name", "htdemucs"]
    assert demucs.demucs("bad.wav", "/out", model_name="htdemucs_ft") is False


# ---------------------------------------------------------------- server_util


def test_kill_existing_server_spares_itself(monkeypatch):
    me = os.getpid()
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout="111\n{}\n222\n".format(me))
    )
    killed = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
    slept = []
    monkeypatch.setattr(server_util.time, "sleep", slept.append)
    assert server_util.kill_existing_server(8765, wait=0.5) == [111, 222]
    assert killed == [(111, signal.SIGTERM), (222, signal.SIGTERM)]
    assert slept == [0.5]


def test_kill_existing_server_nothing_listening(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=""))
    monkeypatch.setattr(server_util.time, "sleep", lambda s: pytest.fail("no need to wait"))
    assert server_util.kill_existing_server(8765) == []
