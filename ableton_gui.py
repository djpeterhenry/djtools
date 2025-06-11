#!/usr/bin/env python3.11

from __future__ import print_function

import sys


if sys.version_info[0] == 3:
    import tkinter as tk
    import tkinter.messagebox as tkm
else:
    import Tkinter as tk
    import tkMessageBox as tkm

# My helper UI classes
from entry_text import EntryText
from lists_selector import ListsSelector
from check_box import Checkbox


import os
import argparse
import random
import subprocess
import time

import ableton_aid as aa
from tag import Tag
from timing import timing


LOCK_FILEPATH = "/tmp/ableton_gui.lock"


class App:
    hidden_tag_pattern_list = [
        "-gc",
        "-mr",
        "-ji",
        "-pe",
        "northfield",
        "shawna",
        "(weidner)",
    ]

    def get_order_list(self):
        # Supported: 'key' 'name'
        # return ['bpm', 'alc', 'sample', 'date', 'date+alc', 'num', 'random']
        return ["date+alc", "num", "alc", "random"]

    def __init__(self, master, include_extra):
        if os.path.exists(LOCK_FILEPATH):
            raise RuntimeError("Locked: {}".format(LOCK_FILEPATH))
        open(LOCK_FILEPATH, "a").close()

        ####
        # Constants

        SEARCH_WIDTH = 10
        TAG_WIDTH = 20

        # window position
        window_x = 0
        window_y = 225
        # window size (note that 1 is different than 0.  So very very true.)
        listbox_width = 78
        listbox_height = 14

        # other dimensions

        init_bpm_range = 3

        # font (you dream of 'consolas')
        listbox_font = ("courier", 16)

        ##########
        # Actually start doing stuff
        master.geometry("+%d+%d" % (window_x, window_y))

        # keep values
        self.master = master

        # core stuff
        self.db_dict = aa.read_db_file()
        self.valid_alc_files = aa.get_valid_alc_files(self.db_dict)
        self.list_to_use = self.valid_alc_files

        # update clips on load
        aa.update_db_clips(self.valid_alc_files, self.db_dict)

        ########
        # gui
        path_stem = os.path.split(os.path.abspath("."))[1]
        print(path_stem)
        master.title("Ableton Aid (%s)" % path_stem)

        #################
        # first row
        frame_top = tk.Frame(master)
        frame_top.pack(side=tk.TOP, fill=tk.X)

        def just_update(a, b, c):
            self.update_listbox()

        self.entry_filter = EntryText(
            frame_top,
            text_width=SEARCH_WIDTH,
            take_focus=True,
            update_fun=self.update_listbox,
        )
        self.entry_bpm = EntryText(
            frame_top,
            text_width=3,
            take_focus=True,
            int_only=True,
            int_min=0,
            int_max=999,
            update_fun=self.update_listbox,
        )
        self.entry_bpm_range = EntryText(
            frame_top,
            text_width=1,
            take_focus=True,
            int_only=True,
            initial_value=str(init_bpm_range),
            int_min=0,
            int_max=9,
            update_fun=self.update_listbox,
        )

        self.bpm_star = Checkbox(frame_top, "*", just_update)

        self.order_list = self.get_order_list()
        self.order_var = tk.StringVar(frame_top)
        self.order_var.trace(
            "w", lambda name, index, mode: self.generate_and_set_from_current_button()
        )
        self.order_var.set(self.order_list[0])
        for s in self.order_list:
            b = tk.Radiobutton(
                frame_top, text=s + " ", variable=self.order_var, value=s, takefocus=0
            )
            b.pack(side=tk.LEFT, anchor=tk.W)

        self.lists_selector = ListsSelector(
            frame_top, aa.LISTS_FOLDER, self.update_listbox
        )

        # key Label
        self.key_label_var = tk.StringVar()
        key_label = tk.Label(frame_top, textvariable=self.key_label_var)
        key_label.pack(side=tk.LEFT)

        # count Label
        self.count_label_var = tk.StringVar()
        count_label = tk.Label(frame_top, textvariable=self.count_label_var)
        count_label.pack(side=tk.LEFT)

        #################
        # second row
        tag_list = self.get_tag_list()
        frame_edit = tk.Frame(master)
        frame_edit.pack(side=tk.TOP, fill=tk.X)

        # extra stuff...put it first on line 2
        self.entry_bpm_edit = None
        self.entry_key_edit = None

        if include_extra:
            self.entry_bpm_edit = EntryText(
                frame_edit,
                int_only=True,
                initial_value="0",
                text_width=3,
                update_fun=self.update_bpm_edit,
            )
            self.entry_key_edit = EntryText(
                frame_edit, text_width=4, update_fun=self.update_key_edit
            )

        self.entry_key_filter = EntryText(
            frame_edit,
            take_focus=True,
            text_width=4,
            int_only=True,
            int_min=1,
            int_max=12,
            update_fun=self.update_listbox,
        )

        # new fun extra key bits
        self.key_1 = Checkbox(frame_edit, "-1", just_update)
        self.key_2 = Checkbox(frame_edit, "1", just_update)
        self.key_3 = Checkbox(frame_edit, "2", just_update)
        self.key_4 = Checkbox(frame_edit, "4", just_update)
        self.key_star = Checkbox(frame_edit, "*", just_update)

        self.tag_var = tk.StringVar(master)
        self.tag_var.trace("w", just_update)
        self.tag_list_menu = tk.OptionMenu(frame_edit, self.tag_var, *tag_list)
        self.tag_list_menu.config(width=TAG_WIDTH)
        self.tag_list_menu.pack(side=tk.LEFT)

        self.tag_invert = Checkbox(frame_edit, "Invert", just_update)
        self.tag_vocal = Checkbox(frame_edit, "[Vocal]", just_update)
        self.tag_ss = Checkbox(frame_edit, "[SS]", just_update)

        self.reveal_var = tk.IntVar(master)
        self.reveal_button = tk.Checkbutton(
            frame_edit, text="Reveal", variable=self.reveal_var, takefocus=0
        )
        self.reveal_button.pack(side=tk.LEFT)

        min_label = tk.Label(frame_edit, text="M:")
        min_label.pack(side=tk.LEFT)
        self.min_amount = EntryText(
            frame_edit,
            int_only=True,
            initial_value=str(0),
            text_width=1,
            int_min=0,
            int_max=9,
            update_fun=self.update_listbox,
        )
        self.max_amount = EntryText(
            frame_edit,
            int_only=True,
            initial_value=str(0),
            text_width=1,
            int_min=0,
            int_max=9,
            update_fun=self.update_listbox,
        )

        #################
        # last row (listbox)

        frame = tk.Frame(master)
        frame.pack(fill=tk.BOTH, expand=1)

        self.scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(
            frame,
            yscrollcommand=self.scrollbar.set,
            width=listbox_width,
            height=listbox_height,
            font=listbox_font,
        )
        self.scrollbar.config(command=self.listbox.yview)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=1)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # TODO(peter): bind to master
        self.listbox_target_string = None
        self.listbox_target_filename = None
        self.listbox.bind("<<ListboxSelect>>", self.listbox_select)
        self.listbox.bind("<Double-Button-1>", lambda _: self.command_copy())
        self.listbox.bind("<Button-1>", lambda _: self.listbox.focus_set())
        self.listbox.bind("<Return>", lambda _: self.command_copy())
        self.listbox.bind("c", lambda _: self.command_clear())
        self.listbox.bind("m", lambda _: self.command_clear_min_max())
        self.listbox.bind("a", lambda _: self.command_tag_add())
        self.listbox.bind("r", lambda _: self.command_tag_remove())
        self.listbox.bind("s", lambda _: self.command_save())
        self.listbox.bind("v", lambda _: self.tag_vocal.toggle())
        self.listbox.bind("f", lambda _: self.command_copy_filename())
        self.listbox.bind("p", lambda _: self.command_play_filename())
        self.listbox.bind("e", lambda _: self.command_export_list())
        self.listbox.bind("g", lambda _: self.command_g())
        self.listbox.bind("l", lambda _: self.command_l())
        self.listbox.bind("j", lambda _: self.command_order_down())
        self.listbox.bind("k", lambda _: self.command_order_up())
        self.listbox.bind("1", lambda _: self.key_1.toggle())
        self.listbox.bind("2", lambda _: self.key_2.toggle())
        self.listbox.bind("3", lambda _: self.key_3.toggle())
        self.listbox.bind("4", lambda _: self.key_4.toggle())
        self.listbox.bind("9", lambda _: self.bpm_star.toggle())
        self.listbox.bind("0", lambda _: self.key_star.toggle())

        self.last_copied_filename = None

        # initial update
        self.update_listbox()

    def quit_handler(self):
        os.remove(LOCK_FILEPATH)
        self.save_dialog()
        sys.exit(0)

    def listbox_select(self, ignore):
        self.listbox_target_string = self.get_selected_string()
        self.listbox_target_filename = self.get_selected_filename()
        self.refresh_edit()

    def refresh_edit(self):
        selected_filename = self.get_selected_filename()
        new_bpm = None
        new_key = None
        try:
            record = self.db_dict[selected_filename]
            new_bpm = record["bpm"]
            new_key = record["key"]
        except KeyError:
            pass
        # only update if UI elements exist
        if self.entry_bpm_edit:
            self.entry_bpm_edit.stringvar.set(new_bpm)
        if self.entry_key_edit:
            self.entry_key_edit.stringvar.set(new_key)

    def get_tag_list(self):
        result = []
        result.append("")
        result.extend(Tag.list())

        # also check the dictionary
        # want to sort those from the dictionary
        others = set()
        for record in self.db_dict.values():
            for tag in record["tags"]:
                if tag not in result:
                    others.add(tag)
        result.extend(sorted(others))
        # remove hidden

        def exclude(tag):
            for pattern in self.hidden_tag_pattern_list:
                if pattern in tag:
                    return True
            return False

        result = [tag for tag in result if not exclude(tag)]
        return result

    @timing
    def update_listbox(self):

        try:
            self.listbox
        except AttributeError:
            return

        # start by clearing
        self.listbox.delete(0, tk.END)
        self.active_alc_files = []

        tag = self.tag_var.get()
        tag_invert = bool(self.tag_invert.get())
        vocal_selected = bool(self.tag_vocal.get())
        ss_selected = bool(self.tag_ss.get())

        # prepare min / max filters
        min_plays = self.min_amount.get_int()
        max_plays = self.max_amount.get_int()

        # prepare key filter
        # split = self.key_filter_string.split()
        # key_filter = split[0] if split else ''
        key_filter = self.entry_key_filter.stringvar.get().strip()
        cam_filter = aa.get_camelot_key(key_filter)
        # direct camelot allowed as well
        if cam_filter is None and len(key_filter) > 0 and key_filter[0].isdigit():
            possible_lower = [s.lower() for s in aa.reverse_camelot_dict.keys()]
            if key_filter.lower() in possible_lower:
                cam_filter = key_filter
            # since major/minor doesn't matter, also allow just camelot numbers
            if cam_filter is None:
                fake_key_filter = key_filter + "A"
                if fake_key_filter.lower() in possible_lower:
                    cam_filter = fake_key_filter

        if cam_filter is not None:
            keys = aa.get_keys_for_camelot_number(cam_filter[:-1])
            keys_as_str = " ".join(keys)
            self.key_label_var.set(keys_as_str)

        # create the numbers from the filter
        # currently just need acceptable camelot numbers (ignore major minor)
        cam_filter_numbers = []
        key_filter_range = 0
        do_key_filter = not self.key_star.get()
        if do_key_filter and cam_filter and key_filter_range is not None:
            cam_filter_num = int(cam_filter[:-1])
            cam_filter_numbers.append(cam_filter_num)
            # add range
            for i in range(0, key_filter_range + 1):
                # python % is always positive
                cam_filter_numbers.append(
                    aa.get_relative_camelot_key(cam_filter_num, i)
                )
                cam_filter_numbers.append(
                    aa.get_relative_camelot_key(cam_filter_num, -i)
                )
            # add variables
            if self.key_1.get():
                cam_filter_numbers.append(
                    aa.get_relative_camelot_key(cam_filter_num, -1)
                )
            if self.key_2.get():
                cam_filter_numbers.append(
                    aa.get_relative_camelot_key(cam_filter_num, 1)
                )
            if self.key_3.get():
                cam_filter_numbers.append(
                    aa.get_relative_camelot_key(cam_filter_num, 2)
                )
            if self.key_4.get():
                cam_filter_numbers.append(
                    aa.get_relative_camelot_key(cam_filter_num, 4)
                )

        filter_string = self.entry_filter.stringvar.get()
        filter_bpm = self.entry_bpm.get_int()
        filter_bpm_range = self.entry_bpm_range.get_int() or 0
        filter_bpm_star = self.bpm_star.get()

        # just in case this is expensive...
        do_vocal_check = True

        # possibly override list to use with selected song list
        list_to_use = self.list_to_use
        lists_selector_song_list = self.lists_selector.get_song_list(self.db_dict)
        if lists_selector_song_list:
            list_to_use = lists_selector_song_list
            do_vocal_check = False

        filename_pairs_list = []  # insert them all at the end for speed?
        last_filename = None
        for filename in list_to_use:
            # never repeat yourself
            if filename == last_filename:
                continue

            try:
                record = self.db_dict[filename]
            except KeyError:
                last_filename = filename  # note dupe
                filename_pairs_list.append((filename, None))
                continue

            bpm, tag_list, key = (record["bpm"], record["tags"], record["key"])
            play_count = aa.get_ts_date_count(record)

            keep = True

            if min_plays > 0 and play_count < min_plays:
                keep = False
            if max_plays > 0 and play_count >= max_plays:
                keep = False

            # vocal affects others
            is_vocal = aa.is_vocal(record)
            if do_vocal_check:
                if is_vocal != vocal_selected:
                    keep = False

            if filter_string:
                for s in filter_string.split():
                    if s.lower() not in filename.lower():
                        keep = False

            if filter_bpm is not None and Tag.SKIP_BPM.value not in tag_list:
                # TODO: could move this filter change outside loop, as well as
                # other range math
                bpm_range = filter_bpm_range
                if is_vocal:
                    bpm_range += 10
                if filter_bpm_star:
                    bpm_range += 10
                if not aa.matches_bpm_filter(filter_bpm, bpm_range, bpm):
                    keep = False

            if tag:
                if tag_invert:
                    if tag in tag_list:
                        keep = False
                else:
                    if tag not in tag_list:
                        keep = False

            do_ss_check = True
            if do_ss_check:
                is_ss = Tag.SS_TAG.value in tag_list
                if is_ss != ss_selected:
                    keep = False

            # used beyond filter check
            cam_song = aa.get_camelot_key(key)

            if key_filter == "-" and len(key) > 0:
                keep = False
            if key_filter == "*" and len(key) == 0:
                keep = False
            if Tag.SKIP_KEY.value not in tag_list:
                if cam_filter_numbers:
                    if cam_song is None:
                        keep = False
                    else:
                        cam_song_num = int(cam_song[:-1])
                        if cam_song_num not in cam_filter_numbers:
                            keep = False

            # This is the only way to see x tags
            is_x = "x" in tag_list and tag != "x"
            if is_x:
                keep = False

            # take action, fool!
            if not keep:
                continue

            last_filename = filename

            file = aa.get_base_filename(filename, record)
            key_display = key
            if cam_song is not None:
                # key_display = key + ' : ' + cam_song
                # key_display = '%3s:%3s' % (key, cam_song)
                # check this with edit
                key_display = "%3s" % (cam_song)
            cool_filename = " %03d|%s|%02d| %s" % (
                bpm,
                key_display,
                min(99, play_count),
                file,
            )
            filename_pairs_list.append((cool_filename, filename))
        # done looping over all filenames

        # reasonable size
        MAX_LENGTH = 1000
        ALPHA = 0.9
        DIVIDER = "-" * 20
        if len(filename_pairs_list) > MAX_LENGTH:
            first = filename_pairs_list[: int(MAX_LENGTH * ALPHA)]
            last = filename_pairs_list[-int(MAX_LENGTH * (1 - ALPHA)) :]
            filename_pairs_list = first + [(DIVIDER, DIVIDER)] + last

        # fill out the important results
        if filename_pairs_list:
            files_display, filenames = zip(*filename_pairs_list)
            self.listbox.insert(tk.END, *files_display)
            self.active_alc_files = filenames

        # search for previous_name
        # NOTE THAT IF PLAY COUNT HAS CHANGED, IT WON'T FIND
        # or anything else (key, etc, when editing)
        print(
            "searching for:",
            self.listbox_target_string,
            "or",
            self.listbox_target_filename,
        )
        for i, pair in enumerate(filename_pairs_list):
            activate = False
            if pair[0] == self.listbox_target_string:
                print("listbox_target_string:", self.listbox_target_string)
                activate = True
            elif (
                self.listbox_target_filename and self.listbox_target_filename == pair[1]
            ):
                print("listbox_target_filename:", self.listbox_target_filename)
                activate = True
            if activate:
                self.listbox.select_set(i)
                self.listbox.activate(i)
                self.listbox.see(i)
                print("found: ", self.listbox_target_string)
                break

        # no matter what (in addition to select)
        self.refresh_edit()

        self.count_label_var.set(str(len(filename_pairs_list)))
        print("Listbox length:", len(filename_pairs_list))

    def update_bpm_edit(self):
        filename = self.get_selected_filename()
        if not filename:
            return
        record = self.db_dict[filename]
        record["bpm"] = self.entry_bpm_edit.get_int()

    def update_key_edit(self):
        filename = self.get_selected_filename()
        if not filename:
            return
        record = self.db_dict[filename]
        record["key"] = self.entry_key_edit.stringvar.get()

    def get_selected_index(self):
        selected_items = self.listbox.curselection()
        try:
            index = int(selected_items[0])
        except IndexError:
            return None
        return index

    def get_selected_string(self):
        index = self.get_selected_index()
        if index is None:
            return None
        return self.listbox.get(index)

    def get_selected_filename(self):
        index = self.get_selected_index()
        if index is None:
            return None
        return self.active_alc_files[index]

    def get_filename_for_index(self, index):
        result = None
        try:
            result = self.active_alc_files[index]
        except IndexError:
            pass
        return result

    def ts_filename(self, filename):
        record = self.db_dict[filename]
        ts = time.time()
        aa.add_ts(record, ts)

    # deprecated:
    def command_copy(self):
        filename = self.get_selected_filename()
        if not filename:
            return
        self.file_action_copy_ableton(filename)
        # and finally reveal if wanted
        if bool(self.reveal_var.get()):
            self.file_action_reveal(filename)

    def file_action(self):
        filename = self.get_selected_filename()
        if not filename:
            return
        # switch here
        self.file_action_copy_ableton(filename)

    def add_ts_from_copy(self, filename):
        if filename == self.last_copied_filename:
            return
        self.last_copied_filename = filename
        self.ts_filename(filename)

    def file_action_copy_ableton(self, filename):
        filename_path = os.path.abspath(filename)
        command = (
            'osascript -e "set the clipboard to POSIX file \\"%s\\""' % filename_path
        )
        subprocess.call(command, shell=True)
        self.add_ts_from_copy(filename)

    def file_action_reveal(self, filename):
        # sample = aa.get_sample(self.db_dict[filename])
        record = self.db_dict[filename]
        sample = aa.get_existing_rekordbox_sample(
            record, sample_key=aa.REKORDBOX_LOCAL_SAMPLE_KEY
        )
        if sample is None:
            return
        aa.reveal_file(sample)
        self.add_ts_from_copy(filename)

    def file_action_copy_filename(self, filename):
        self.set_clipboard_data(filename)

    def file_action_play_vlc(self, filename):
        sample = aa.get_sample(self.db_dict[filename])
        command = ["open", sample]
        subprocess.call(command)

    # should be classmethod
    def set_clipboard_data(self, data):
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.stdin.write(data)
        p.stdin.close()
        retcode = p.wait()

    # for use with f shortcut key
    def command_copy_filename(self):
        filename = self.get_selected_filename()
        if not filename:
            return
        self.file_action_copy_filename(filename)

    # for use with p shortcut key
    def command_play_filename(self):
        filename = self.get_selected_filename()
        if not filename:
            return
        self.file_action_play_vlc(filename)

    def command_export_list(self):
        for filename in self.active_alc_files:
            print(filename)

    def command_tag_add(self):
        filename = self.get_selected_filename()
        if not filename:
            return
        tag = self.tag_var.get()
        self.add_tag_to_filename(filename, tag)

    def command_tag_remove(self):
        filename = self.get_selected_filename()
        if not filename:
            return
        tag = self.tag_var.get()
        if not tag:
            return
        record = self.db_dict[filename]
        try:
            record["tags"].remove(tag)
        except ValueError:
            pass
        self.update_listbox()

    def save_dialog(self):
        do_save = tkm.askokcancel("Confirm Save", "Save database?")
        if do_save:
            aa.write_db_file(self.db_dict)

    def command_save(self):
        return self.save_dialog()

    def add_tag_to_filename(self, filename, tag):
        if not tag:
            return
        record = self.db_dict[filename]
        if tag not in record["tags"]:
            record["tags"].append(tag)
        # timestamp every time we tag
        self.ts_filename(filename)
        # some old indexing code
        old_index = self.get_selected_index()
        self.update_listbox()
        self.listbox.activate(old_index)
        self.listbox.see(old_index)

    def command_g(self):
        filename = self.get_selected_filename()
        if not filename:
            return
        tag = Tag.GOOD_TAG.value
        self.add_tag_to_filename(filename, tag)

    def command_l(self):
        filename = self.get_selected_filename()
        if not filename:
            return
        tag = Tag.LOOK_TAG.value
        self.add_tag_to_filename(filename, tag)

    def command_clear_min_max(self):
        print("clear min max")
        self.min_amount.set(0)
        self.max_amount.set(0)

    def command_order_down(self):
        print("command_order_down")
        var = self.order_var.get()
        which = self.order_list.index(var)
        which -= 1
        if which < 0:
            which = len(self.order_list) - 1
        self.order_var.set(self.order_list[which])

    def command_order_up(self):
        print("command_order_up")
        var = self.order_var.get()
        which = self.order_list.index(var)
        which += 1
        if which >= len(self.order_list):
            which = 0
        self.order_var.set(self.order_list[which])

    def command_clear(self):
        self.command_clear_min_max()
        self.entry_filter.clear()
        self.entry_bpm.clear()
        self.entry_key_filter.clear()
        # TODO CLEAR TAG DROPDOWN

    def generate_and_set_from_current_button(self):
        t = time.time()
        self.list_to_use = self.valid_alc_files
        # ignore 'name'...it's the default
        if self.order_var.get() == "bpm":
            self.list_to_use = self.generate_bpm()
        elif self.order_var.get() == "date":
            self.list_to_use = self.generate_date()
        elif self.order_var.get() == "date+alc":
            self.list_to_use = self.generate_date_plus_alc()
        elif self.order_var.get() == "sample":
            self.list_to_use = self.generate_sample()
        elif self.order_var.get() == "alc":
            self.list_to_use = self.generate_alc()
        elif self.order_var.get() == "random":
            self.list_to_use = self.generate_random()
        elif self.order_var.get() == "key":
            self.list_to_use = self.generate_key()
        elif self.order_var.get() == "num":
            self.list_to_use = self.generate_num()
        print("[time] generate_and_set_from_current_button:", str(time.time() - t))
        self.update_listbox()

    def generate_random(self):
        files = list(self.valid_alc_files)
        random.shuffle(files)
        return files

    def generate_date(self):
        return aa.generate_date(self.valid_alc_files, self.db_dict)

    def generate_alc(self):
        return aa.generate_alc(self.valid_alc_files, self.db_dict)

    def generate_date_plus_alc(self):
        return aa.generate_date_plus_alc(self.valid_alc_files, self.db_dict)

    def generate_sample(self):
        return aa.generate_sample(self.valid_alc_files, self.db_dict)

    def generate_bpm(self):
        bpm_file_tuples = []
        for file in self.valid_alc_files:
            record = self.db_dict[file]
            bpm_file_tuples.append((record["bpm"], file))
        bpm_file_tuples.sort()
        return [file for _, file in bpm_file_tuples]

    def generate_key(self):
        key_file_tuples = []
        for file in self.valid_alc_files:
            record = self.db_dict[file]
            key_song = record.get("key")
            cam_song = aa.get_camelot_key(key_song)
            if cam_song is not None:
                cam_sort = ("%02d" % int(cam_song[:-1])) + cam_song[-1]
                key_file_tuples.append((cam_sort, file))
            else:
                key_file_tuples.append(("Z", file))
        key_file_tuples.sort()
        return [file for _, file in key_file_tuples]

    def generate_num(self):
        return aa.generate_num(self.valid_alc_files, self.db_dict)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--always_on_top", "-t", action="store_true")
    parser.add_argument("--include_extra", "-e", action="store_true")
    return parser.parse_args()


def main(args):
    master = tk.Tk()
    app = App(master, args.include_extra)
    on_top_str = "1" if args.always_on_top else "0"
    master.call("wm", "attributes", ".", "-topmost", on_top_str)
    # Intercept mac quit "command-q" because previous atexit no longer triggers for this on my new mac.
    # This does not catch "command-w" but I'm not going to worry about that for now.
    master.createcommand("tk::mac::Quit", app.quit_handler)
    master.mainloop()


if __name__ == "__main__":
    main(parse_args())
