import os

import pytest

import ableton_aid as aa
from db_types import DbDict

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
