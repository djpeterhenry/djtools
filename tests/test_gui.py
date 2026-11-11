import tkinter as tk

import pytest

import ableton_aid as aa
from conftest import DAY, make_record


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    r.destroy()


# ---------------------------------------------------------------- widgets


def test_entry_text_int_only(root):
    from entry_text import EntryText

    calls = []
    e = EntryText(root, int_only=True, int_min=1, int_max=12, update_fun=lambda: calls.append(1))
    e.set("5")
    assert e.get_int() == 5
    e.set("abc")
    assert e.stringvar.get() == "5"
    e.set("13")
    assert e.stringvar.get() == "5"
    e.key_uparrow(None)
    assert e.get_int() == 6
    e.set("12")
    e.int_plus()
    assert e.get_int() == 12
    e.set("1")
    e.key_downarrow(None)
    assert e.get_int() == 1
    e.clear()
    assert e.stringvar.get() == "" and e.get_int() is None
    assert calls


def test_entry_text_free_text(root):
    from entry_text import EntryText

    e = EntryText(root, initial_value="hi")
    e.set("anything goes")
    assert e.stringvar.get() == "anything goes"
    assert e.get_int() is None


def test_checkbox(root):
    from check_box import Checkbox

    calls = []
    c = Checkbox(root, "x", lambda *a: calls.append(a))
    assert c.get() == 0
    c.toggle()
    assert c.get() == 1
    c.toggle()
    assert c.get() == 0
    assert len(calls) == 2


def test_lists_selector(root, tmp_path):
    from lists_selector import ListsSelector

    (tmp_path / "warmup.txt").write_text("A - Song\nB - Set\nUnknown\n")
    (tmp_path / ".hidden").write_text("")
    updates = []
    s = ListsSelector(root, str(tmp_path), lambda: updates.append(1))
    assert s.update_and_get_names() == ["", "warmup"]
    assert s.get_song_list({}) is None

    s.string_var.set("warmup")
    assert s.song_list == ["A - Song", "B - Set", "Unknown"]
    db = {"A - Song.alc": {}, "B - Set.als": {}}
    assert s.get_song_list(db) == ["A - Song.alc", "B - Set.als", "Unknown"]

    s.disabled_var.set(1)
    assert s.get_song_list(db) is None
    assert updates


def test_lists_selector_missing_folder(root, tmp_path):
    from lists_selector import ListsSelector

    s = ListsSelector(root, str(tmp_path / "nope"))
    assert s.get_song_list({}) is None


# -------------------------------------------------------------------- App


@pytest.fixture
def gui_env(make_alc, write_db, tmp_path, monkeypatch, fixed_now):
    import ableton_gui

    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "warmup.txt").write_text("B - New One\n")
    monkeypatch.setattr(aa, "LISTS_FOLDER", str(lists))
    lock = tmp_path / "gui.lock"
    monkeypatch.setattr(ableton_gui, "LOCK_FILEPATH", str(lock))

    db = {
        "A - Old Favorite.alc": make_record(
            bpm=122,
            key="8A",
            tags=["GOOD", "DISCO"],
            ts_list=[fixed_now - 400 * DAY, fixed_now - 30 * DAY],
            alc_ts=fixed_now - 1000 * DAY,
        ),
        "B - New One.alc": make_record(bpm=126, key="Db", ts_list=[fixed_now - 2 * DAY]),
        "C - Vocal.alc": make_record(bpm=90, key="F#m", tags=["vocal"]),
        "D - Hidden.alc": make_record(tags=["x"]),
    }
    for f in db:
        make_alc(f)
    write_db(db)
    return lock


@pytest.fixture
def app(root, gui_env):
    import ableton_gui

    a = ableton_gui.App(root, include_extra=True)
    yield a
    if gui_env.exists():
        gui_env.unlink()


def rows(app):
    return [r.rstrip() for r in app.listbox.get(0, tk.END)]


def test_app_default_listing(app, gui_env):
    assert gui_env.exists()
    # vocals and x-tagged songs are hidden by default; date+alc order
    assert rows(app) == [
        " 126| 3B|01| B - New One",
        " 122| 8A|02| (g) A - Old Favorite        [#DISCO]",
    ]
    assert app.count_label_var.get() == "2"


def test_app_filters(app):
    app.entry_filter.set("old")
    assert len(rows(app)) == 1
    app.entry_filter.clear()

    app.tag_vocal.toggle()
    assert [r.split("|")[-1] for r in rows(app)] == [" C - Vocal [Vocal]"]
    app.tag_vocal.toggle()

    app.entry_bpm.set("122")
    assert [r[:4] for r in rows(app)] == [" 122"]
    app.bpm_star.toggle()  # widens the range by 10
    assert len(rows(app)) == 2
    app.bpm_star.toggle()
    app.entry_bpm.clear()

    app.entry_key_filter.set("8")
    assert app.key_label_var.get() == "Am C"
    assert len(rows(app)) == 1
    app.key_star.toggle()  # key filter off
    assert len(rows(app)) == 2
    app.key_star.toggle()
    app.entry_key_filter.clear()

    app.tag_var.set("GOOD")
    assert len(rows(app)) == 1
    app.tag_invert.toggle()
    assert rows(app)[0].endswith("B - New One")
    app.tag_invert.toggle()
    app.tag_var.set("x")
    assert rows(app)[0].endswith("D - Hidden")
    app.tag_var.set("")

    app.min_amount.set(2)
    assert len(rows(app)) == 1
    app.command_clear_min_max()
    assert len(rows(app)) == 2


def test_app_orders(app):
    app.order_var.set("num")
    assert rows(app)[0].endswith("[#DISCO]")
    app.command_order_up()
    assert app.order_var.get() == "alc"
    app.command_order_down()
    app.command_order_down()
    assert app.order_var.get() == "date+alc"
    app.lists_selector.string_var.set("warmup")
    assert len(rows(app)) == 1


def test_app_tagging(app, fixed_now):
    app.listbox.selection_set(0)
    app.listbox_select(None)
    assert app.get_selected_filename() == "B - New One.alc"
    assert app.entry_bpm_edit.get_int() == 126

    app.command_g()
    record = app.db_dict["B - New One.alc"]
    assert "GOOD" in record["tags"]
    assert record["ts_list"][-1] == fixed_now
    app.command_l()
    assert "lyrics" in record["tags"]
    app.command_n()
    assert "no_lyrics" in record["tags"] and "lyrics" not in record["tags"]
    app.command_b()
    assert "GOOD" not in record["tags"]

    # the tag menu is also the filter: invert it so B (without DISCO) shows
    app.tag_invert.toggle()
    app.tag_var.set("DISCO")
    app.listbox.selection_set(0)
    assert app.get_selected_filename() == "B - New One.alc"
    app.command_tag_add()
    assert "DISCO" in record["tags"]
    app.tag_invert.toggle()
    app.listbox.selection_clear(0, tk.END)
    app.listbox.selection_set(0)
    assert app.get_selected_filename() == "B - New One.alc"
    app.command_tag_remove()
    assert "DISCO" not in record["tags"]


def test_app_edit_bpm_and_key(app):
    app.listbox.selection_set(0)
    app.listbox_select(None)
    app.entry_bpm_edit.set("127")
    app.entry_key_edit.set("9A")
    assert app.db_dict["B - New One.alc"]["bpm"] == 127
    assert app.db_dict["B - New One.alc"]["key"] == "9A"


def test_app_copy_stamps_once(app, monkeypatch, fixed_now):
    import subprocess

    calls = []
    monkeypatch.setattr(subprocess, "call", lambda *a, **k: calls.append(a))
    app.listbox.selection_set(0)
    app.command_copy()
    app.command_copy()
    assert len(calls) == 2
    assert app.db_dict["B - New One.alc"]["ts_list"].count(fixed_now) == 1


def test_app_quit_removes_lock_and_saves(app, gui_env, monkeypatch):
    import ableton_gui

    monkeypatch.setattr(ableton_gui.tkm, "askokcancel", lambda *a: True)
    app.db_dict["B - New One.alc"]["bpm"] = 100
    with pytest.raises(SystemExit):
        app.quit_handler()
    assert not gui_env.exists()
    assert aa.read_db_file()["B - New One.alc"]["bpm"] == 100


def test_app_refuses_second_instance(app, root):
    import ableton_gui

    with pytest.raises(RuntimeError):
        ableton_gui.App(root, include_extra=False)


def test_app_failed_startup_releases_lock(root, gui_env, monkeypatch):
    import ableton_gui

    def broken():
        raise ValueError("bad db")

    monkeypatch.setattr(aa, "read_db_file", broken)
    with pytest.raises(ValueError):
        ableton_gui.App(root, include_extra=False)
    assert not gui_env.exists()


def test_app_bpm_edit_rejects_empty(app):
    app.listbox.selection_set(0)
    app.listbox_select(None)
    app.entry_bpm_edit.set("")
    assert app.entry_bpm_edit.stringvar.get() == "126"
    assert app.db_dict["B - New One.alc"]["bpm"] == 126


def test_app_record_without_key(app):
    del app.db_dict["B - New One.alc"]["key"]
    app.update_listbox()
    assert len(rows(app)) == 2
