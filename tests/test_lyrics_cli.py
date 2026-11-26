"""lyrics.py's commands, LRCLIB client and whole-song steps, with the network and ML faked."""

import io
import json
import urllib.error

import pytest

import ableton_aid as aa
import lyrics
import lyrics_align
from conftest import make_record
from test_lyrics import FakeAligner

SONG = "Zedd - Clarity.alc"


@pytest.fixture
def library(songs_dir, write_db, tmp_path):
    sample = tmp_path / "Zedd - Clarity.wav"
    sample.write_bytes(b"RIFF fake audio")
    write_db({SONG: make_record(rekordbox_local_sample=str(sample)), "Zedd - Spectrum.alc": make_record()})
    return sample


@pytest.fixture
def fake_create(monkeypatch):
    """lyrics.create without the ML: records what it was asked."""
    calls = []

    def create(song, sample, reference, source, separate=None, log=print, tags=()):
        calls.append({"song": song, "reference": reference, "source": source, "separate": separate})
        line = lyrics.timed_line("Hi", [{"t0": 1.0, "t1": 1.5, "text": "Hi", "score": 1.0}])
        return lyrics.new_sidecar(song, sample, 10.0, [line], reference, source)

    monkeypatch.setattr(lyrics, "create", create)
    return calls


def test_pick_song(capsys):
    db = {"Zedd - Clarity.alc": {}, "Zedd - Clarity (Remix).alc": {}}
    assert lyrics.pick_song(db, "zedd - clarity") == "Zedd - Clarity.alc"
    assert capsys.readouterr().out == ""  # an exact name is no guess
    assert lyrics.pick_song(db, "clarity") == "Zedd - Clarity.alc"
    assert "Several songs match" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="No song matches"):
        lyrics.pick_song(db, "nothing")


def test_song_sample_needs_an_export(library):
    db = aa.read_db_file()
    assert lyrics.song_sample(db, SONG) == str(library)
    with pytest.raises(SystemExit, match="export to rekordbox first"):
        lyrics.song_sample(db, "Zedd - Spectrum.alc")


def test_add_from_a_file(library, fake_create, tmp_path):
    text = tmp_path / "words.txt"
    text.write_text("Hi there\n")
    lyrics.main(["add", "clarity", "--lyrics-file", str(text), "--no-separate"])
    [call] = fake_create
    assert call == {"song": SONG, "reference": "Hi there\n", "source": {"lyrics": "file"}, "separate": False}
    assert lyrics.read_sidecar(lyrics.sidecar_path(SONG))["source"] == {"lyrics": "file"}
    with pytest.raises(SystemExit, match="--force"):
        lyrics.main(["add", "clarity", "--no-lyrics"])
    lyrics.main(["add", "clarity", "--no-lyrics", "--force", "--separate"])
    assert fake_create[-1]["reference"] is None and fake_create[-1]["separate"] is True


def test_add_from_lrclib(library, fake_create, monkeypatch):
    found = [{"id": 9, "artistName": "Zedd", "trackName": "Clarity", "plainLyrics": "Hi there"}]
    monkeypatch.setattr(lyrics, "lrclib_search", lambda artist, title: found)
    lyrics.main(["add", "clarity"])
    assert fake_create[-1]["reference"] == "Hi there"
    assert fake_create[-1]["source"]["lyrics"] == "lrclib:9"
    assert fake_create[-1]["separate"] is None  # decided by name and tags

    found.clear()
    lyrics.main(["add", "clarity", "--force"])
    assert fake_create[-1]["source"] == {"lyrics": "none"}


def test_check_and_index(library, fake_create, capsys):
    lyrics.main(["add", "clarity", "--no-lyrics"])
    capsys.readouterr()
    lyrics.main(["check"])
    assert "ok" in capsys.readouterr().out
    library.write_bytes(b"RIFF re-exported audio")
    lyrics.main(["check"])
    out = capsys.readouterr().out
    assert "stale" in out and "1 need attention" in out
    lyrics.main(["index"])
    assert "1 songs in" in capsys.readouterr().out


def test_write_index_skips_unreadable(library, fake_create, capsys):
    lyrics.main(["add", "clarity", "--no-lyrics"])
    with open(lyrics.sidecar_path("Broken.alc"), "w") as f:
        f.write("{not json")
    assert [s["file"] for s in lyrics.write_index()["songs"]] == ["Zedd - Clarity.lyrics.json"]
    assert "Skipping unreadable Broken.lyrics.json" in capsys.readouterr().out


@pytest.fixture
def fake_la(monkeypatch):
    """lyrics_align's audio steps as no-ops on the sample itself."""
    monkeypatch.setattr(lyrics_align, "vocals_path", lambda s: s + ".vocals")
    monkeypatch.setattr(lyrics_align, "timeline_path", lambda s: s)
    monkeypatch.setattr(lyrics_align, "sample_shift", lambda s: 0.0)
    monkeypatch.setattr(lyrics_align, "Aligner", lambda audio: FakeAligner())
    transcribed = []

    def transcribe(audio, language=None):
        transcribed.append((audio, language))
        return [{"start": 1.0, "end": 3.0, "text": "high dive into frozen waves", "words": []}]

    monkeypatch.setattr(lyrics_align, "transcribe", transcribe)
    return transcribed


def test_create(library, fake_la):
    s = lyrics.create(SONG, str(library), "High dive into frozen waves\nWhere the past comes back to life",
                      {"lyrics": "file"}, log=lambda m: None)
    assert fake_la == [(str(library) + ".vocals", "en")]
    assert [l["text"] for l in s["lines"]] == ["High dive into frozen waves"]
    assert s["source"]["separated"] is True and s["source"]["lyrics"] == "file"
    assert s["duration"] == 300.0


def test_create_acapella_is_not_separated(library, fake_la):
    s = lyrics.create(SONG, str(library), None, {"lyrics": "none"}, tags=["vocal"], log=lambda m: None)
    assert fake_la == [(str(library), None)]
    assert s["source"]["separated"] is False
    assert s["lines"][0]["note"] == "Whisper's text (no lyrics)"


def test_realign_keeps_text_and_unreviews(library, fake_create, fake_la, capsys):
    lyrics.main(["add", "clarity", "--no-lyrics"])
    path = lyrics.sidecar_path(SONG)
    s = lyrics.read_sidecar(path)
    s["reviewed"] = True
    lyrics.save_sidecar(s, path)
    library.write_bytes(b"RIFF re-exported audio")
    lyrics.main(["realign", "clarity"])
    s = lyrics.read_sidecar(path)
    assert [l["text"] for l in s["lines"]] == ["Hi"]
    assert s["reviewed"] is False
    assert lyrics.sidecar_status(s) == "ok"


def _line(text, t0, t1, **extra):
    return dict(lyrics.timed_line(text, [{"t0": t0, "t1": t1, "text": text, "score": 1.0}]), **extra)


def test_add_force_keeps_hand_edits(library, fake_create, capsys):
    lyrics.main(["add", "clarity", "--no-lyrics"])
    path = lyrics.sidecar_path(SONG)
    s = lyrics.read_sidecar(path)
    created = s["created"]
    # the person retimed "Hi" (now theirs) and set an offset; another automatic line exists
    s["lines"] = [_line("Mine", 1.2, 1.4, edited=True), _line("Auto", 5.0, 6.0)]
    s["offset"] = 0.25
    lyrics.save_sidecar(s, path)
    capsys.readouterr()

    lyrics.main(["add", "clarity", "--no-lyrics", "--force"])
    s = lyrics.read_sidecar(path)
    # their line stays; the rebuilt "Hi" overlaps it so it is left out; "Auto" was rebuilt away
    assert [(l["text"], l.get("edited")) for l in s["lines"]] == [("Mine", True)]
    assert s["offset"] == 0.25 and s["created"] == created
    assert "Kept 1 edited line(s)" in capsys.readouterr().out


def test_add_force_does_not_bring_back_deleted_lines(library, fake_create):
    lyrics.main(["add", "clarity", "--no-lyrics"])
    path = lyrics.sidecar_path(SONG)
    s = lyrics.read_sidecar(path)
    s["lines"] = []
    s["removed"] = [{"t0": 1.0, "t1": 1.5, "text": "Hi"}]  # the person deleted the automatic "Hi"
    lyrics.save_sidecar(s, path)
    lyrics.main(["add", "clarity", "--no-lyrics", "--force"])
    s = lyrics.read_sidecar(path)
    assert s["lines"] == []
    assert s["removed"] == [{"t0": 1.0, "t1": 1.5, "text": "Hi"}]  # still remembered for next time


def test_add_force_leaves_reviewed_songs_alone(library, fake_create):
    lyrics.main(["add", "clarity", "--no-lyrics"])
    path = lyrics.sidecar_path(SONG)
    s = lyrics.read_sidecar(path)
    s["reviewed"] = True
    lyrics.save_sidecar(s, path)
    with pytest.raises(SystemExit, match="marked reviewed"):
        lyrics.main(["add", "clarity", "--no-lyrics", "--force"])
    assert len(fake_create) == 1  # nothing was rebuilt
    assert lyrics.read_sidecar(path)["reviewed"] is True


def test_realign_keeps_edited_marks(library, fake_create, fake_la):
    lyrics.main(["add", "clarity", "--no-lyrics"])
    path = lyrics.sidecar_path(SONG)
    s = lyrics.read_sidecar(path)
    s["lines"][0]["edited"] = True
    lyrics.save_sidecar(s, path)
    lyrics.main(["realign", "clarity"])
    assert lyrics.read_sidecar(path)["lines"][0].get("edited") is True


# ---------------------------------------------------------------- LRCLIB


def test_get_json_retries_when_busy(monkeypatch):
    answers = [
        urllib.error.HTTPError("u", 429, "busy", {"Retry-After": "3"}, None),  # type: ignore[arg-type]
        urllib.error.HTTPError("u", 503, "down", None, None),  # type: ignore[arg-type]
        io.BytesIO(b'{"ok": 1}'),
    ]

    def urlopen(req, timeout):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    slept = []
    monkeypatch.setattr(lyrics.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(lyrics.time, "sleep", slept.append)
    assert lyrics._get_json("https://example.invalid") == {"ok": 1}
    assert slept == [3.0, 4.0]


def test_get_json_gives_up_on_other_errors(monkeypatch):
    def urlopen(req, timeout):
        raise urllib.error.HTTPError("u", 404, "nope", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(lyrics.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        lyrics._get_json("https://example.invalid")


def test_lrclib_search_filters_and_ranks(monkeypatch):
    queries = []
    results = [
        {"id": 1, "artistName": "Zedd", "trackName": "Clarity", "plainLyrics": "a b c"},
        {"id": 2, "artistName": "Zedd", "trackName": "Clarity", "syncedLyrics": "[00:01.00] a b c"},
        {"id": 3, "artistName": "Zedd", "trackName": "Clarity", "instrumental": True, "plainLyrics": "x"},
        {"id": 4, "artistName": "Someone Else", "trackName": "Clarity", "plainLyrics": "a b c"},
        {"id": 5, "artistName": "Zedd", "trackName": "Clarity", "plainLyrics": "other words"},
        {"id": 1, "artistName": "Zedd", "trackName": "Clarity", "plainLyrics": "a b c"},  # duplicate
    ]

    def get_json(url):
        queries.append(url)
        return results

    monkeypatch.setattr(lyrics, "_get_json", get_json)
    got = lyrics.lrclib_search("Zedd & Foxes", "Clarity")
    # synced beats plain; the text two results agree on beats the odd one out
    assert [r["id"] for r in got] == [2, 1, 5]
    assert len(queries) == 1  # the first query found something


def test_lrclib_search_falls_back_and_survives_errors(monkeypatch):
    queries = []

    def get_json(url):
        queries.append(url)
        if len(queries) == 1:
            raise OSError("offline")
        return []

    monkeypatch.setattr(lyrics, "_get_json", get_json)
    assert lyrics.lrclib_search("Zedd & Foxes", "Clarity") == []
    assert len(queries) == 3  # as named, main artist only, free text
    assert "q=Zedd+Clarity" in queries[-1]


def test_lrclib_get(monkeypatch):
    monkeypatch.setattr(lyrics, "_get_json", lambda url: {"url": url})
    assert lyrics.lrclib_get(42) == {"url": "https://lrclib.net/api/get/42"}


def test_lrclib_source_round_trips_through_json():
    src = lyrics.lrclib_source({"id": 3, "artistName": "A", "trackName": "T", "syncedLyrics": "[00:01.00] x"})
    assert json.loads(json.dumps(src)) == {
        "lyrics": "lrclib:3",
        "lrclib": {"artist": "A", "track": "T", "album": "", "duration": 0, "synced": True},
    }


def test_describe_source_other_kinds():
    assert lyrics.describe_source({"source": {"lyrics": "none"}})["kind"] == "whisper"
    assert lyrics.describe_source({"source": {"lyrics": "file"}})["kind"] == "file"
    assert lyrics.describe_source({"source": {"lyrics": "manual"}})["kind"] == "manual"
    # text typed in the page with nothing looked up is not Whisper's hearing
    assert lyrics.describe_source({"source": {"lyrics": "none"}, "reference": "typed"})["kind"] == "manual"


def test_merge_rebuilt_keeps_hand_edits():
    def ln(text, t0, t1, **extra):
        return dict(lyrics.timed_line(text, [{"t0": t0, "t1": t1, "text": text, "score": 1.0}]), **extra)

    current = [ln("mine", 1, 2, edited=True), ln("auto", 3, 4)]
    rebuilt = [ln("overlaps mine", 1.5, 2.5), ln("deleted", 5, 6), ln("new", 7, 8, edited=True)]
    removed = [{"t0": 5.2, "t1": 5.8, "text": "Deleted!"}]
    merged = lyrics.merge_rebuilt(current, rebuilt, removed)
    assert [l["text"] for l in merged] == ["mine", "new"]
    assert "edited" not in merged[1]

