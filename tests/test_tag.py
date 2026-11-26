"""The known tags and their properties: tag.py's default table, or the config's [tags] table."""

import importlib

import pytest

import config
import tag


@pytest.fixture
def configured(monkeypatch):
    """tag, rebuilt from the given [tags] table (None: no table); restored afterward."""

    def build(table):
        monkeypatch.setattr(config, "TAGS_SETTING", table)
        return importlib.reload(tag)

    yield build
    monkeypatch.undo()
    importlib.reload(tag)


def test_default_table(configured):
    t = configured(None)
    genres = t.REKORDBOX_GENRE_TAGS
    assert genres[0] == "JAZZ" and genres[-1] == "HIDE_GENRE" and len(genres) == 14
    assert t.REKORDBOX_PLAYLIST_TAGS == genres + ["GOOD"]
    assert t.REKORDBOX_FILENAME_TAGS == genres + ["GOOD", "vocal", "lyrics", "no_lyrics"]
    assert t.HIDDEN_TAG_VALUES == {"HIDE_GENRE", "x", "x_rekordbox", "ALL KEYS", "ALL BPM"}
    assert t.MENU_TAGS[: len(genres)] == genres
    assert set(t.Tag.list()) <= set(t.MENU_TAGS)


def test_each_property_on_its_own(configured):
    t = configured({
        "TECHNO": ["genre", "playlist"],  # a genre without a mark
        "DAY_VENUE": ["mark", "playlist"],
        "LOOPS": ["playlist"],
        "vocal": ["mark"],
        "old": ["hidden"],
        "ONLY_A_GENRE": ["genre"],
    })
    assert t.REKORDBOX_GENRE_TAGS == ["TECHNO", "ONLY_A_GENRE", "HIDE_GENRE"]  # HIDE_GENRE: always a genre
    assert t.REKORDBOX_FILENAME_TAGS == ["DAY_VENUE", "vocal"]
    assert t.REKORDBOX_PLAYLIST_TAGS == ["TECHNO", "DAY_VENUE", "LOOPS"]
    assert t.HIDDEN_TAG_VALUES == {"old"}
    assert "DISCO" not in t.MENU_TAGS  # the table is the whole list
    # table order first, then built-ins the table left out
    assert t.MENU_TAGS[:6] == ["TECHNO", "DAY_VENUE", "LOOPS", "vocal", "old", "ONLY_A_GENRE"]
    assert "GOOD" in t.MENU_TAGS and "x" in t.MENU_TAGS


def test_hide_genre_keeps_its_place_when_listed(configured):
    t = configured({"HIDE_GENRE": ["genre"], "TECHNO": ["genre", "mark"]})
    assert t.REKORDBOX_GENRE_TAGS == ["HIDE_GENRE", "TECHNO"]
    assert t.REKORDBOX_FILENAME_TAGS == ["TECHNO"]


def test_unknown_property_is_an_error(configured):
    with pytest.raises(SystemExit, match="tags.DISCO: unknown property playlists"):
        configured({"DISCO": ["genre", "playlists"]})


def test_find_tag(configured):
    t = configured({"Mixed_Case": ["playlist"], "BIG_ROOM": ["genre"]})
    assert t.find_tag("big_room") == "BIG_ROOM"
    assert t.find_tag("Good") == "GOOD"  # built in, though not in the table
    assert t.find_tag("VOCAL") == "vocal"
    assert t.find_tag("mixed_case") == "Mixed_Case"
    assert t.find_tag("nothing") is None
