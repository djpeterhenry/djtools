import pytest

import ableton_aid as aa


def test_camelot_dict_covers_all_keys_and_sharps():
    # 24 flat/natural spellings plus 10 sharp aliases
    assert len(aa.camelot_dict) == 34
    assert len(aa.reverse_camelot_dict) == 24
    assert aa.camelot_dict["Abm"] == "1A"
    assert aa.camelot_dict["G#m"] == "1A"
    assert aa.camelot_dict["B"] == "1B"
    assert aa.camelot_dict["Am"] == "8A"
    assert aa.camelot_dict["C"] == "8B"
    assert aa.camelot_dict["F#m"] == "11A"
    assert aa.camelot_dict["E"] == "12B"
    assert aa.reverse_camelot_dict["8A"] == "Am"
    assert aa.reverse_camelot_dict["2B"] == "Gb"


@pytest.mark.parametrize(
    "key, expected",
    [
        ("Am", "8A"),
        ("Db", "3B"),
        ("C#", "3B"),
        ("8A", "8A"),
        ("8a", "8A"),
        ("12b", "12B"),
        ("", None),
        ("H", None),
    ],
)
def test_get_camelot_key(key, expected):
    assert aa.get_camelot_key(key) == expected


@pytest.mark.parametrize("key", ["1|", "13A", "0A", "8Ax"])
def test_get_camelot_key_rejects_invalid(key):
    assert aa.get_camelot_key(key) is None


def test_get_camelot_key_none():
    assert aa.get_camelot_key(None) is None


def test_get_camelot_num():
    assert aa.get_camelot_num("Am") == 8
    assert aa.get_camelot_num("11B") == 11
    assert aa.get_camelot_num("nope") is None


@pytest.mark.parametrize(
    "num, offset, expected", [(12, 1, 1), (1, -1, 12), (8, 2, 10), (5, 0, 5), (3, -4, 11)]
)
def test_get_relative_camelot_key(num, offset, expected):
    assert aa.get_relative_camelot_key(num, offset) == expected


def test_get_keys_for_camelot_number():
    assert aa.get_keys_for_camelot_number(8) == ["Am", "C"]
    assert aa.get_keys_for_camelot_number(None) == []
