import ableton_aid as aa
from conftest import DAY


def files(db):
    return sorted(db)


def test_generate_alc(db_dict):
    assert aa.generate_alc(files(db_dict), db_dict) == [
        "D - Hidden.alc",
        "B - New One.alc",
        "C - Vocal.alc",
        "E - No Key.alc",
        "F - Missing Clip.alc",
        "A - Old Favorite.alc",
    ]


def test_generate_date(db_dict):
    # never-played songs tie at 0 and fall back to reverse filename order
    assert aa.generate_date(files(db_dict), db_dict) == [
        "B - New One.alc",
        "A - Old Favorite.alc",
        "F - Missing Clip.alc",
        "E - No Key.alc",
        "D - Hidden.alc",
        "C - Vocal.alc",
    ]


def test_generate_date_plus_alc(db_dict):
    assert aa.generate_date_plus_alc(files(db_dict), db_dict) == [
        "B - New One.alc",
        "D - Hidden.alc",
        "C - Vocal.alc",
        "E - No Key.alc",
        "A - Old Favorite.alc",
        "F - Missing Clip.alc",
    ]


def test_generate_num_breaks_ties_on_recency(db_dict, fixed_now):
    assert aa.generate_num(files(db_dict), db_dict) == [
        "A - Old Favorite.alc",
        "B - New One.alc",
        "D - Hidden.alc",
        "C - Vocal.alc",
        "E - No Key.alc",
        "F - Missing Clip.alc",
    ]
    pairs = aa.generate_num_alc_pairs(files(db_dict), db_dict, ts_after=fixed_now - 100 * DAY)
    assert pairs[:2] == [(1, "B - New One.alc"), (1, "A - Old Favorite.alc")]


def test_generate_recent_and_old(db_dict):
    recent, old = aa.generate_recent_and_old(files(db_dict), db_dict, years=0.1)
    assert old == ["F - Missing Clip.alc"]
    assert recent[0] == "B - New One.alc"
    assert len(recent) == 5


def test_generate_random_keeps_input():
    original = ["a", "b", "c"]
    shuffled = aa.generate_random(original)
    assert sorted(shuffled) == original
    assert original == ["a", "b", "c"]


def test_generate_sets(db_dict, fixed_now):
    result = aa.generate_sets(files(db_dict), db_dict)
    assert result == [
        "B - New One.alc",
        "-" * 12 + " " + aa.get_date_from_ts(fixed_now - 30 * DAY + 60),
        "A - Old Favorite.alc",
        "-" * 12 + " " + aa.get_date_from_ts(fixed_now - 400 * DAY),
    ]


def test_generate_sets_only_listed_files(db_dict):
    result = aa.generate_sets(["A - Old Favorite.alc"], db_dict)
    assert "B - New One.alc" not in result
    assert "A - Old Favorite.alc" in result


def test_generate_sample():
    db = {
        "a.alc": {"clip": {"sample_ts": 1}},
        "b.alc": {"clip": {"sample_ts": 3}},
        "c.alc": {},
    }
    assert aa.generate_sample(["a.alc", "b.alc", "c.alc"], db) == ["b.alc", "a.alc"]


def test_get_song_in_db():
    db = {"Song.als": {}, "Song.alc": {}, "Other.alc": {}, "Exact": {}}
    assert aa.get_song_in_db("Song", db) == ("Song", "Song.als")
    assert aa.get_song_in_db("Other", db) == ("Other", "Other.alc")
    assert aa.get_song_in_db("Exact", db) == ("Exact", "Exact")
    assert aa.get_song_in_db("Nope", db) == ("Nope", None)


def test_get_list_from_file(tmp_path, db_dict):
    list_file = tmp_path / "list.txt"
    list_file.write_text("[01:02:03] A - Old Favorite\nUnknown Song\nB - New One\n")
    assert aa.get_list_from_file(str(list_file), db_dict) == [
        ("A - Old Favorite", "A - Old Favorite.alc"),
        ("Unknown Song", None),
        ("B - New One", "B - New One.alc"),
    ]


def test_get_list_name_to_file(tmp_path):
    for name in ["a.txt", "b", ".hidden", "c.md"]:
        (tmp_path / name).write_text("")
    (tmp_path / "subdir").mkdir()
    result = aa.get_list_name_to_file(str(tmp_path))
    assert result == {"a": str(tmp_path / "a.txt"), "b": str(tmp_path / "b")}


def test_get_filename_unidecode_matching(db_dict):
    db_dict["Röyksopp - Éclair.alc"] = {}
    assert aa.get_filename_unidecode_matching("A", "Old Favorite", db_dict) == "A - Old Favorite.alc"
    assert aa.get_filename_unidecode_matching(" Royksopp", "Eclair ", db_dict) == "Röyksopp - Éclair.alc"
    assert aa.get_filename_unidecode_matching("A", "Nope", db_dict) is None


def test_stamp_song(db_dict, fixed_now):
    aa.stamp_song(db_dict, fixed_now + 1, "B", "New One")
    assert fixed_now + 1 in db_dict["B - New One.alc"]["ts_list"]
    aa.stamp_song(db_dict, fixed_now + 1, "Nobody", "Nothing")  # just prints


def test_file_discovery(songs_dir, db_dict):
    (songs_dir / "sub").mkdir()
    for name in ["B - New One.alc", "A - Old Favorite.alc", "sub/Z - Set.als", "notes.txt", "Unknown.alc"]:
        (songs_dir / name).write_bytes(b"")
    assert aa.get_ableton_files() == [
        "A - Old Favorite.alc",
        "B - New One.alc",
        "sub/Z - Set.als",
        "Unknown.alc",
    ]
    assert aa.get_valid_alc_files(db_dict) == ["A - Old Favorite.alc", "B - New One.alc"]

    (songs_dir / "D - Hidden.alc").write_bytes(b"")
    assert aa.get_rekordbox_files(db_dict) == ["A - Old Favorite.alc", "B - New One.alc"]
    assert aa.filter_recordbox_files(["D - Hidden.alc", "zzz"], db_dict) == []


def test_generate_lists(songs_dir, db_dict, tmp_path):
    for f in db_dict:
        (songs_dir / f).write_text("")
    aa.write_db_file(db_dict)
    out = tmp_path / "collection"
    out.mkdir()
    aa.generate_lists(str(out), push=False)
    assert sorted(p.name for p in out.iterdir()) == ["add.txt", "date_or_add.txt", "name.txt", "num.txt", "sets.txt"]
    # x-tagged songs are left out, extensions dropped
    assert (out / "name.txt").read_text().splitlines() == [
        "A - Old Favorite",
        "B - New One",
        "C - Vocal",
        "E - No Key",
        "F - Missing Clip",
    ]
    assert (out / "num.txt").read_text().splitlines()[0] == "A - Old Favorite"
