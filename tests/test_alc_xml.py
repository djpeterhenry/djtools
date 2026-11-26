import os

import pytest

import ableton_aid as aa
from db_types import ClipInfo, DbDict

SAMPLE = os.path.join("..", "Samples", "Imported", "Artist - Track.aiff")


@pytest.mark.parametrize("new_format", [True, False])
def test_get_audioclip_from_alc(make_alc, new_format):
    fn = make_alc(
        warp_markers=[(0.25, 0.0), (8.25, 16.0)],
        loop={"loop_start": 4.0, "loop_end": 20.0, "start_relative": 1.0, "loop_on": True},
        new_format=new_format,
    )
    clip = aa.get_audioclip_from_alc(fn)
    assert clip["warp_markers"] == [
        {"sec_time": 0.25, "beat_time": 0.0},
        {"sec_time": 8.25, "beat_time": 16.0},
    ]
    assert clip["loop_start"] == 4.0
    assert clip["loop_end"] == 20.0
    assert clip["start_relative"] == 1.0
    assert clip["loop_on"] is True
    assert clip["hidden_loop_start"] == 0.0
    assert clip["hidden_loop_end"] == 16.0
    assert clip["sample"] == SAMPLE
    assert clip["sample_ts"] == os.path.getmtime(SAMPLE)
    assert clip["sample_filepath_is_new_format"] is new_format
    assert clip["is_warped"] is True


def test_unwarped_clip(make_alc):
    assert aa.get_audioclip_from_alc(make_alc(is_warped=False))["is_warped"] is False


def test_clip_without_is_warped_counts_as_warped(make_alc):
    fn = make_alc()
    root = aa.alc_to_xml(fn)
    xml_clip = aa._find(root, ".//AudioClip")
    xml_clip.remove(aa._find(xml_clip, "IsWarped"))
    aa.write_xml_to_alc(root, fn)
    assert aa.get_audioclip_from_alc(fn)["is_warped"] is True


def test_missing_sample_gives_none(make_alc):
    assert aa.get_audioclip_from_alc(make_alc(create_sample=False)) is None


def test_no_audioclip_gives_none(songs_dir):
    import gzip

    with gzip.open("empty.alc", "wb") as f:
        f.write(b"<Ableton />")
    assert aa.get_audioclip_from_alc("empty.alc") is None


def test_relative_path_without_value_gives_none(make_alc):
    fn = make_alc()
    root = aa.alc_to_xml(fn)
    del root.find(".//FileRef/RelativePath").attrib["Value"]
    aa.write_xml_to_alc(root, fn)
    assert aa.get_audioclip_from_alc(fn) is None


def test_get_audioclips_from_als(make_alc):
    fn = make_alc("Set.als", num_clips=3)
    clips = aa.get_audioclips_from_als(fn)
    assert len(clips) == 3
    assert all(c["sample"].endswith("Set.aiff") for c in clips)


def test_alc_to_str_round_trip(make_alc):
    fn = make_alc()
    assert "<AudioClip" in aa.alc_to_str(fn)
    aa.write_xml_to_alc(aa.alc_to_xml(fn), "copy.alc")
    assert aa.get_audioclip_from_alc("copy.alc") == aa.get_audioclip_from_alc(fn)


def test_replace_audioclip_path(make_alc, songs_dir):
    fn = make_alc()
    new_sample = songs_dir.parent / "Samples" / "Demucs" / "vocals.wav"
    new_sample.parent.mkdir()
    new_sample.write_bytes(b"v")
    assert aa.replace_audioclip_path(fn, "Artist - Track (Vocal).alc", str(new_sample))

    root = aa.alc_to_xml("Artist - Track (Vocal).alc")
    assert root.find(".//AudioClip/Name").get("Value") == "Artist - Track (Vocal)"
    assert root.find(".//FileRef/RelativePath").get("Value") == "Samples/Demucs/vocals.wav"
    assert root.find(".//FileRef/Path").get("Value") == str(new_sample)
    clip = aa.get_audioclip_from_alc("Artist - Track (Vocal).alc")
    assert clip["sample"] == os.path.join("..", "Samples", "Demucs", "vocals.wav")


def test_replace_audioclip_path_requires_alc(make_alc):
    with pytest.raises(ValueError):
        aa.replace_audioclip_path(make_alc(), "x.als", "s.wav")


def test_write_silenced_alc(make_alc, songs_dir):
    fn = make_alc(warp_markers=[(-0.5, 0.0), (7.5, 16.0)])
    new_sample = songs_dir.parent / "Samples" / "Imported" / "silenced.aiff"
    new_sample.write_bytes(b"s")
    assert aa.write_silenced_alc(fn, "silenced.alc", str(new_sample), 2.0)

    clip = aa.get_audioclip_from_alc("silenced.alc")
    assert clip["warp_markers"] == [
        {"sec_time": 1.5, "beat_time": 0.0},
        {"sec_time": 9.5, "beat_time": 16.0},
    ]
    root = aa.alc_to_xml("silenced.alc")
    assert root.find(".//DefaultDuration").get("Value") == str(441000 + 2 * 44100)


def test_update_db_clips(make_alc):
    alc = make_alc("A - B.alc")
    als = make_alc("Set.als", num_clips=2)
    db: DbDict = {alc: {}, als: {}}
    aa.update_db_clips([alc, als], db)
    assert db[alc]["clip"]["sample"].endswith("A - B.aiff")
    assert db[alc]["alc_ts"] == os.path.getmtime(alc)
    assert "clips" not in db[alc]
    assert len(db[als]["clips"]) == 2
    assert db[als]["als_ts"] == os.path.getmtime(als)

    # up to date records are left alone
    db[alc]["clip"]["loop_start"] = 99.0
    aa.update_db_clips([alc], db)
    assert db[alc]["clip"]["loop_start"] == 99.0
    aa.update_db_clips([alc], db, force_alc=True)
    assert db[alc]["clip"]["loop_start"] == 0.0


def test_project_path_from_alc_filename(songs_dir):
    assert aa.project_path_from_alc_filename("x.alc") == str(songs_dir.parent)


def _clip(markers, loop_start=0.0, loop_end=0.0, start_relative=0.0, is_warped=True) -> ClipInfo:
    """A ClipInfo with (sec, beat) warp markers; loop_end <= start means "whole marker range"."""
    return {
        "warp_markers": [{"sec_time": sec, "beat_time": beat} for sec, beat in markers],
        "loop_start": loop_start,
        "loop_end": loop_end,
        "start_relative": start_relative,
        "loop_on": False,
        "hidden_loop_start": 0.0,
        "hidden_loop_end": 0.0,
        "sample": SAMPLE,
        "sample_ts": 0.0,
        "sample_filepath_is_new_format": True,
        "is_warped": is_warped,
    }


@pytest.mark.parametrize(
    "bpm, expected",
    [(86.5, 86), (86.49, 86), (86.51, 87), (86.5 + 1e-9, 86), (86.5 - 1e-9, 86), (128.0, 128)],
)
def test_round_bpm_halves_round_down(bpm, expected):
    assert aa.round_bpm(bpm) == expected


def test_clip_tempo_steady():
    tempo = aa.get_clip_tempo(_clip([(0.5, 0.0), (8.5, 16.0)], loop_end=64.0))
    assert tempo.bpm == pytest.approx(120.0)
    assert tempo.section_bpms == [pytest.approx(120.0)]
    assert tempo.is_steady


def test_clip_tempo_extends_outer_tempo_past_markers():
    # markers only cover beats 16..32; played part 0..64 keeps their 120 bpm
    tempo = aa.get_clip_tempo(_clip([(8.0, 16.0), (16.0, 32.0)], loop_end=64.0))
    assert tempo.bpm == pytest.approx(120.0)


def test_clip_tempo_change_is_not_steady():
    # 64 beats at 120, then 64 beats at 128
    clip = _clip([(0.0, 0.0), (32.0, 64.0), (62.0, 128.0)], loop_end=128.0)
    tempo = aa.get_clip_tempo(clip)
    assert tempo.section_bpms == [pytest.approx(120.0), pytest.approx(128.0)]
    assert tempo.bpm == pytest.approx(128 / (62.0 / 60))
    assert not tempo.is_steady


def test_clip_tempo_change_outside_played_part_is_ignored():
    clip = _clip([(0.0, 0.0), (32.0, 64.0), (62.0, 128.0)], loop_start=8.0, loop_end=56.0)
    tempo = aa.get_clip_tempo(clip)
    assert tempo.section_bpms == [pytest.approx(120.0)]
    assert tempo.bpm == pytest.approx(120.0)
    assert tempo.is_steady


def test_clip_tempo_start_relative_moves_start():
    clip = _clip([(0.0, 0.0), (32.0, 64.0), (62.0, 128.0)], loop_start=0.0, start_relative=64.0, loop_end=128.0)
    assert aa.get_clip_tempo(clip).bpm == pytest.approx(128.0)


def test_clip_tempo_jitter_averages_out():
    # a marker every 4 beats, alternating 118 and 122 bpm: segments differ by 4, sections don't
    markers, sec = [(0.0, 0.0)], 0.0
    for i in range(32):
        sec += 4 * 60 / (118.0 if i % 2 else 122.0)
        markers.append((sec, 4.0 * (i + 1)))
    tempo = aa.get_clip_tempo(_clip(markers))
    assert tempo.is_steady
    assert aa.round_bpm(tempo.bpm) == 120


def test_clip_tempo_unwarped_is_not_steady():
    tempo = aa.get_clip_tempo(_clip([(0.5, 0.0), (8.5, 16.0)], is_warped=False))
    assert tempo.bpm == pytest.approx(120.0)
    assert not tempo.is_steady


def test_clip_tempo_cached_clip_without_is_warped():
    clip = _clip([(0.5, 0.0), (8.5, 16.0)])
    del clip["is_warped"]
    assert aa.get_clip_tempo(clip).is_steady


def test_clip_tempo_skips_backward_markers():
    tempo = aa.get_clip_tempo(_clip([(0.0, 0.0), (0.0, 4.0), (8.0, 16.0)]))
    assert tempo.bpm == pytest.approx(120.0)


@pytest.mark.parametrize("markers", [[], [(0.0, 0.0)], [(1.0, 0.0), (0.5, 4.0)]])
def test_clip_tempo_none_without_two_usable_markers(markers):
    assert aa.get_clip_tempo(_clip(markers)) is None
