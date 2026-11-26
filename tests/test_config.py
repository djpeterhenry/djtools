import os

import pytest

import config


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('lists_folder = "~/lists"\ncollection_folder = "/abs/collection"\n')
    return path


def test_defaults_without_a_file(tmp_path):
    settings = config.load({"DJTOOLS_CONFIG": str(tmp_path / "missing.toml")})
    assert settings["lists_folder"] is None
    assert settings["collection_folder"] is None
    assert "active_list" not in settings  # the Active playlist is gone
    assert settings["rekordbox_local_sample_path"] == os.path.expanduser("~/Music/PioneerDJ/LocalSamples")


def test_file_values_are_expanded(config_file):
    settings = config.load({"DJTOOLS_CONFIG": str(config_file)})
    assert settings["lists_folder"] == os.path.expanduser("~/lists")
    assert settings["collection_folder"] == "/abs/collection"


def test_environment_wins_over_the_file(config_file):
    settings = config.load({"DJTOOLS_CONFIG": str(config_file), "DJTOOLS_LISTS_FOLDER": "/env/lists"})
    assert settings["lists_folder"] == "/env/lists"
    assert settings["collection_folder"] == "/abs/collection"


def test_unknown_setting_is_an_error(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('list_folder = "typo"\n')
    with pytest.raises(SystemExit, match="list_folder"):
        config.load({"DJTOOLS_CONFIG": str(path)})


def test_list_settings(tmp_path):
    path = tmp_path / "config.toml"
    assert config.load_lists({"DJTOOLS_CONFIG": str(path)}) == {"hidden_tags": []}
    path.write_text('hidden_tags = ["-ab", "(venue)"]\n')
    assert config.load_lists({"DJTOOLS_CONFIG": str(path)})["hidden_tags"] == ["-ab", "(venue)"]
    env = {"DJTOOLS_CONFIG": str(path), "DJTOOLS_HIDDEN_TAGS": " a, b ,,"}
    assert config.load_lists(env)["hidden_tags"] == ["a", "b"]
    # a list setting is no path setting, and is known to both loaders
    assert "hidden_tags" not in config.load({"DJTOOLS_CONFIG": str(path)})


def test_list_setting_must_be_strings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('hidden_tags = "-ab"\n')
    with pytest.raises(SystemExit, match="hidden_tags must be a list"):
        config.load_lists({"DJTOOLS_CONFIG": str(path)})
    path.write_text("hidden_tags = [1]\n")
    with pytest.raises(SystemExit, match="hidden_tags must be a list"):
        config.load_lists({"DJTOOLS_CONFIG": str(path)})


def test_tags_table(tmp_path):
    path = tmp_path / "config.toml"
    assert config.load_tags({"DJTOOLS_CONFIG": str(path)}) is None  # no table: tag.py's default
    path.write_text('hidden_tags = []\n[tags]\nZED = ["playlist"]\n"ALL KEYS" = ["hidden"]\nSS = []\n')
    table = config.load_tags({"DJTOOLS_CONFIG": str(path)})
    assert table == {"ZED": ["playlist"], "ALL KEYS": ["hidden"], "SS": []}
    assert table is not None and list(table) == ["ZED", "ALL KEYS", "SS"]  # the file's order


@pytest.mark.parametrize("text", ['tags = ["DISCO"]\n', '[tags]\nDISCO = "genre"\n', "[tags]\nDISCO = [1]\n"])
def test_tags_table_shape(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    with pytest.raises(SystemExit, match="djtools config: tags"):
        config.load_tags({"DJTOOLS_CONFIG": str(path)})


def test_tests_run_without_the_users_settings():
    # conftest points DJTOOLS_CONFIG at nothing before anything imports config
    assert config.get("lists_folder") is None
    assert config.get("collection_folder") is None
    assert config.get_list("hidden_tags") == []
    assert config.get_tags() is None
