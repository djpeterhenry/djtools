"""lyrics.py: the text logic and sidecar files (no machine learning: a fake aligner)."""

import json
import os

import pytest

import lyrics


class FakeAligner:
    """Spreads the words evenly over the window; path_score prefers texts containing `favor`."""

    def __init__(self, favor: str = "") -> None:
        self.favor = favor
        self.duration = 300.0

    def align_words(self, words, a, b):
        step = (b - a) / max(1, len(words))
        out = []
        for i, w in enumerate(words):
            t = lyrics.norm_words(w)
            out.append({"t0": None if not any(c.isalpha() for c in w) else round(a + i * step, 3),
                        "t1": None if not any(c.isalpha() for c in w) else round(a + (i + 1) * step, 3),
                        "text": w, "score": 0.5 if t else 0.0})
        return out

    def path_score(self, words, a, b):
        return 1.0 if self.favor and self.favor in " ".join(words).lower() else 0.0


LYRICS = """[Verse]
High dive into frozen waves
Where the past comes back to life

[Chorus]
If our love is tragedy, why are you my remedy?
If our love's insanity, why are you my clarity?
"""


def seg(start, end, text, words=None):
    if words is None:
        n = len(text.split())
        words = [{"start": start + i * (end - start) / n, "end": start + (i + 1) * (end - start) / n, "word": w}
                 for i, w in enumerate(text.split())]
    return {"start": start, "end": end, "text": text, "words": words}


def test_norm_words_folds_apostrophes_and_dropped_g():
    assert lyrics.norm_words("Dancin’ 'round, LOVE's") == ["dancing", "round", "love's"]


def test_lyric_lines_drop_labels_and_blanks():
    assert lyrics.lyric_lines(LYRICS)[0] == "High dive into frozen waves"
    assert len(lyrics.lyric_lines(LYRICS)) == 4


def test_units_include_pairs_and_comma_halves():
    units = lyrics.lyric_units(lyrics.lyric_lines(LYRICS))
    assert ["Why are you my remedy?"] in units
    assert ["High dive into frozen waves", "Where the past comes back to life"] in units


def test_choose_unit_fixes_misheard_words():
    units = lyrics.lyric_units(lyrics.lyric_lines(LYRICS))
    unit, _ = lyrics.choose_unit("If all love is tragedy, why are you my remedy", units)
    assert unit == ["If our love is tragedy, why are you my remedy?"]


def test_choose_unit_lets_audio_decide_equal_lengths():
    units = lyrics.lyric_units(lyrics.lyric_lines(LYRICS))
    text = "If all love's insanity, why are you my remedy"
    unit, cands = lyrics.choose_unit(text, units, lambda u: 1.0 if "tragedy" in " ".join(u) else 0.0)
    assert unit == ["If our love is tragedy, why are you my remedy?"]
    assert len(cands) == 2


def test_choose_unit_none_for_text_not_in_lyrics():
    units = lyrics.lyric_units(lyrics.lyric_lines(LYRICS))
    assert lyrics.choose_unit("Thank you.", units)[0] is None


def test_build_lines_drops_hallucinations_and_duplicates():
    segs = [
        seg(1.5, 7.7, "I dive into frozen waves where the past comes back to life"),
        seg(46.5, 53.9, "If all love is tragedy, why are you my remedy?"),
        # Whisper's duplicate: every word without length
        seg(54.0, 55.0, "Why are you my remedy?", [{"start": 54.0, "end": 54.0, "word": w} for w in "Why are you my remedy?".split()]),
        seg(248.9, 250.2, "Thank you."),
    ]
    lines = lyrics.build_lines(segs, LYRICS, FakeAligner(), 260.0, log=lambda m: None)
    assert [l["text"] for l in lines] == [
        "High dive into frozen waves",
        "Where the past comes back to life",
        "If our love is tragedy, why are you my remedy?",
    ]
    assert lines[0]["t1"] <= lines[1]["t0"]


def test_build_lines_joins_a_line_whisper_split():
    text = "Livin' in ruins of a palace within my dreams\nAnd you know, we're on each other's team"
    segs = [seg(55.5, 57.0, "Living in ruins"), seg(57.3, 60.0, "Silver past within my dreams")]
    lines = lyrics.build_lines(segs, text, FakeAligner(), 300.0, log=lambda m: None)
    assert [l["text"] for l in lines] == ["Livin' in ruins of a palace within my dreams"]


def test_overlapping_same_line_keeps_one_and_trims_others():
    a = lyrics.timed_line("We live in cities", [{"t0": 10.0, "t1": 12.0, "text": "w", "score": 0.6}])
    b = lyrics.timed_line("We live in cities", [{"t0": 11.0, "t1": 13.0, "text": "w", "score": 0.2}])
    c = lyrics.timed_line("Something else", [{"t0": 11.8, "t1": 14.0, "text": "w", "score": 0.2}])
    out = lyrics.drop_overlaps([a, b, c], log=lambda m: None)
    assert [l["text"] for l in out] == ["We live in cities", "Something else"]
    assert out[0]["t1"] <= out[1]["t0"]


def test_without_reference_whisper_text_is_used():
    lines = lyrics.build_lines([seg(1, 3, "hello there")], None, FakeAligner(), 10.0, log=lambda m: None)
    assert lines[0]["text"] == "hello there"


def test_fill_untimed_spreads_numbers_between_neighbors():
    words = [{"t0": 1.0, "t1": 2.0}, {"t0": None, "t1": None}, {"t0": 3.0, "t1": 4.0}]
    lyrics.fill_untimed(words, 0.0, 5.0)
    assert words[1]["t0"] == 2.0 and words[1]["t1"] == 3.0


def test_line_window_stays_between_neighbors():
    lines = [{"t0": 1.0, "t1": 2.0}, {"t0": 2.5, "t1": 4.0}, {"t0": 4.2, "t1": 5.0}]
    a, b = lyrics.line_window(lines, 1, 10.0)
    assert 1.9 <= a <= 2.5 and 4.0 <= b <= 4.3


def test_search_terms_main_artist_and_bare_title():
    assert lyrics.search_terms("Zedd & Foxes - Clarity (Acapella).als") == ("Zedd & Foxes", "Clarity")
    assert lyrics.main_artist("Zedd & Foxes") == "Zedd"
    assert lyrics.main_artist("Above & Beyond") == "Above"   # hence the artist as named is searched first
    assert lyrics.search_terms("Lorde - Team (Elephante Remix).alc") == ("Lorde", "Team")


def test_vocal_only_names():
    assert lyrics.is_vocal_only("Kesha - Tik Tok (Acapella).als")
    assert lyrics.is_vocal_only("Kissy Sell Out - You're Not The One (Acappella).alc")
    assert not lyrics.is_vocal_only("Lorde - Team (Elephante Remix).alc")
    assert lyrics.is_vocal_only("Dr Dre - The Next Episode.als", ["vocal", "GOOD"])   # the tag says acapella


def test_guess_language():
    assert lyrics.guess_language(LYRICS) == "en"
    assert lyrics.guess_language("Je t'aime moi non plus") is None
    assert lyrics.guess_language(None) is None


def test_sidecar_index_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("DJTOOLS_LYRICS_DIR", str(tmp_path / "Lyrics"))
    sample = tmp_path / "Zedd & Foxes - Clarity (Acapella).wav"
    sample.write_bytes(b"RIFF....fake audio")
    line = lyrics.timed_line("Hello", [{"t0": 1.0, "t1": 1.5, "text": "Hello", "score": 0.9}])
    s = lyrics.new_sidecar("Zedd & Foxes - Clarity (Acapella).als", str(sample), 260.0, [line], "Hello", {"lyrics": "file"})
    path = lyrics.save_sidecar(s)
    assert path.endswith("Lyrics/Zedd & Foxes - Clarity (Acapella).lyrics.json")
    index = json.loads((tmp_path / "Lyrics" / "index.json").read_text())
    assert index["songs"] == [{"artist": "Zedd & Foxes", "title": "Clarity (Acapella)",
                               "file": "Zedd & Foxes - Clarity (Acapella).lyrics.json", "reviewed": False}]
    assert lyrics.sidecar_status(lyrics.read_sidecar(path)) == "ok"
    sample.write_bytes(b"RIFF....other audio")
    assert lyrics.sidecar_status(lyrics.read_sidecar(path)) == "stale"
    os.remove(sample)
    assert lyrics.sidecar_status(lyrics.read_sidecar(path)) == "missing"


def test_lrclib_lyrics_text_strips_time_stamps():
    assert lyrics.lyrics_text({"syncedLyrics": "[00:09.19] High dive\n[00:12.61] Where"}) == "High dive\nWhere"


@pytest.mark.parametrize("q,first", [("clarity", "Zedd - Clarity.alc"), ("zedd clarity remix", "Zedd - Clarity (Remix).alc")])
def test_find_songs(q, first):
    db = {"Zedd - Clarity.alc": {}, "Zedd - Clarity (Remix).alc": {}, "Other.alc": {}}
    assert lyrics.find_songs(db, q)[0] == first


def test_rekordbox_shift_puts_back_what_ffmpeg_trims_from_gapless_mp3s():
    import lyrics_align as la

    # LAME header: delay 1105 samples (ffprobe start_time) + the header frame (1152) = 51.2 ms at 44.1 kHz.
    assert la.rekordbox_shift(".mp3", 1105 / 44100, 44100) == pytest.approx(2257 / 44100)
    assert la.rekordbox_shift(".MP3", 0.025057, 48000) == pytest.approx(0.025057 + 1152 / 48000)
    assert la.rekordbox_shift(".mp3", 0.05, 22050) == pytest.approx(0.05 + 576 / 22050)
    assert la.rekordbox_shift(".mp3", 0.0, 44100) == 0.0      # no gapless header: nothing trimmed
    assert la.rekordbox_shift(".wav", 0.025, 44100) == 0.0


def test_describe_source_kinds_and_other_versions():
    song = "Darlyn Vlys & Forrest - Colours (Tim Engelhardt Remix).alc"
    src = lyrics.lrclib_source({"id": 7, "artistName": "Darlyn Vlys", "trackName": "Colours (Ruede Hagelstein Remix)",
                                "albumName": "Colours", "duration": 400, "syncedLyrics": "[00:01.00] x"})
    d = lyrics.describe_source({"song": song, "source": src})
    assert d["kind"] == "lrclib" and d["other_version"] and "Ruede Hagelstein" in d["label"]
    src["lrclib"]["trackName"] = src["lrclib"]["track"] = "Colours (feat. Someone) - Radio Edit"
    assert not lyrics.describe_source({"song": song, "source": src})["other_version"]
    assert lyrics.describe_source({"song": song, "source": {"lyrics": "none"}})["kind"] == "whisper"
    assert lyrics.describe_source({"song": song, "source": {"lyrics": "manual"}, "reference": "x"})["kind"] == "manual"


@pytest.mark.parametrize("artist,title,r_artist,r_track,ok", [
    ("Pretty Pink, Gracie Thunder", "Echo", "Echo & the Bunnymen", "Bring on the Dancing Horses", False),
    ("Kidnap", "Moments", "Kidnap Kid", "Moments", True),
    ("Kaskade, deadmau5", "Escape", "HAYLA; Kaskade; Kx5; deadmau5", "Escape", True),
    ("Hugel, Stefy De Cicco, Hugo Cantarra", "Four to the Floor",
     "Stefy de Cicco  Hugel& Hugo Cantarra feat Nikol Apatini", "Four to floor 03 (Extended Mix)", True),
    ("Gorgon City", "You've Done Enough", "Gorgon City", "32.You've Done Enough", True),
    ("RUFUS DU SOL", "Make It Happen", "RÜFÜS DU SOL", "Make It Happen", True),
    ("Zedd & Foxes", "Clarity", "Zedd", "Clarity", True),
    ("Zedd", "Clarity", "Someone Else", "Clarity", False),
])
def test_lrclib_matches(artist, title, r_artist, r_track, ok):
    assert lyrics.lrclib_matches({"artistName": r_artist, "trackName": r_track}, artist, title) is ok


def test_choose_unit_by_sound_only_when_no_words_match():
    units = lyrics.lyric_units(["This is house arrest", "And come hold me babe", "Come catch me babe", "Thirsty"])
    assert lyrics.choose_unit("This is how to rest.", units)[0] == ["This is house arrest"]
    assert lyrics.choose_unit("Thank you.", units)[0] is None
    # matched by words: sound does not add near-ties for the audio to break
    unit, cands = lyrics.choose_unit("Come and hold me baby", units, lambda u: 1.0 if "catch" in u[0] else 0.0)
    assert unit == ["And come hold me babe"] and len(cands) == 1


def test_build_lines_does_not_join_when_the_next_segment_is_the_line():
    text = "And colours are not colours when they're old.\nAll I know."
    segs = [seg(334.3, 337.9, "And colors are not colors"), seg(337.9, 339.6, "When they're over"), seg(341.5, 343.9, "All I know")]

    class Dragging(FakeAligner):
        """The first word at the window's start, the rest at its end (as MMS_FA did on Colours)."""

        def align_words(self, words, a, b):
            out = super().align_words(words, b - 0.4 * len(words), b)
            if len(words) > 1 and b - a > 4:
                out[0]["t0"], out[0]["t1"] = round(a + 0.1, 3), round(a + 0.3, 3)
            return out

    lines = lyrics.build_lines(segs, text, Dragging(), 400.0, log=lambda m: None)
    assert [l["text"] for l in lines][-1] == "All I know." and lines[-1]["t0"] > 340.0


def test_without_reference_whisper_fillers_are_dropped():
    segs = [seg(0.3, 1.5, "Thank you."), seg(93.7, 95.0, "I wanna believe you")]
    lines = lyrics.build_lines(segs, None, FakeAligner(), 300.0, log=lambda m: None)
    assert [l["text"] for l in lines] == ["I wanna believe you"]


def test_whisper_fillers_and_other_scripts():
    assert lyrics.is_whisper_filler("Thank you.")
    assert lyrics.is_whisper_filler("Closed Captioning by foundationla.com")
    assert lyrics.is_whisper_filler("ご視聴ありがとうございました")
    assert not lyrics.is_whisper_filler("Thank you for loving me")
    assert lyrics.mostly_other_script(["はい", "ご視聴ありがとうございました", "Oh"])
    assert not lyrics.mostly_other_script(["Under the milky way tonight", "はい"])


def test_without_reference_other_scripts_in_a_latin_song_are_dropped():
    segs = [seg(31.0, 32.0, "はい"), seg(82.6, 85.0, "I live a milky way tonight"), seg(90.0, 92.0, "The milky way tonight")]
    lines = lyrics.build_lines(segs, None, FakeAligner(), 300.0, log=lambda m: None)
    assert [l["text"] for l in lines] == ["I live a milky way tonight", "The milky way tonight"]


def _ln(text, t0, t1):
    ws = text.split()
    step = (t1 - t0) / len(ws)
    return {"t0": t0, "t1": t1, "text": text,
            "words": [{"t0": round(t0 + i * step, 3), "t1": round(t0 + (i + 1) * step, 3), "text": w} for i, w in enumerate(ws)]}


def test_hand_edits_are_per_line():
    auto = [_ln("Come hold me babe", 10, 12), _ln("Free fallin baby", 20, 22), _ln("Wrong line here", 30, 32)]
    saved = [dict(auto[0]), _ln("Free falling baby", 20, 22)]    # one fixed, one deleted, one untouched
    removed: list = []
    lyrics.mark_hand_edits(auto, saved, removed)
    assert "edited" not in saved[0] and saved[1]["edited"]
    assert [r["text"] for r in removed] == ["Free fallin baby", "Wrong line here"]
    # a later save keeps the mark on the fixed line
    again = [dict(l) for l in saved]
    lyrics.mark_hand_edits(saved, again, removed)
    assert again[1]["edited"] and "edited" not in again[0]
    # a rebuild improves the untouched part, keeps the fix, and does not bring the deleted line back
    rebuilt = [_ln("And come hold me babe", 9.5, 12), _ln("Free fallin baby", 20.1, 22), _ln("Wrong line here", 30.2, 32),
               _ln("A new line", 40, 42)]
    merged = lyrics.merge_rebuilt(again, rebuilt, removed)
    assert [l["text"] for l in merged] == ["And come hold me babe", "Free falling baby", "A new line"]
    assert [bool(l.get("edited")) for l in merged] == [False, True, False]
