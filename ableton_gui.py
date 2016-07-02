#!/usr/bin/env python

# for tags if installed
from mutagen.easyid3 import EasyID3

# dup import:
import sys, os, glob, stat
import cPickle
import shutil
import re
import random
import subprocess
from Tkinter import *
import tkSimpleDialog
import tkMessageBox
import ableton_aid
import time
import atexit
import datetime
import codecs
import json

# touches
import cPickle


class App:
    add_tag_string = 'add...'
    skip_key_check_string = 'ALL KEYS'
    skip_bpm_check_string = 'ALL BPM'
    extra_tag_list = ['x', 'vocal', 'SS', '-NN',
        skip_key_check_string, skip_bpm_check_string,
        'NEW']
    hidden_tag_list = []

    def get_order_list(self):
        # Supported?: 'sets' 'key'
        return ['name', 'bpm', 'alc', 'sample', 'date', 'num', 'random']

    def __init__(self, master, db_filename, include_extra):
        # window position
        window_x = 0
        window_y = 170
        # window size (note that 1 is different than 0.  So very very true.)
        listbox_width = 1
        listbox_height = 16

        # other dimensions
        search_width = 8
        tag_filter_width = 5
        init_bpm_range = 3
        init_key_range = 0

        # font (you dream of 'consolas')
        listbox_font = ('courier', 16)

        ##########
        # Actually start doing stuff
        master.geometry('+%d+%d' % (window_x, window_y))

        # keep values
        self.master = master
        self.db_filename = db_filename

        # core stuff
        self.db_dict = ableton_aid.read_db_file(db_filename)
        self.valid_alc_files = ableton_aid.get_valid_alc_files(self.db_dict)
        self.list_to_use = self.valid_alc_files

        # read cache files once
        t_cache = time.clock()
        print ("Updating and getting cache values...")
        self.dict_file_cache = ableton_aid.get_dict_file_cache(self.valid_alc_files)
        print ("Took: %f" % (time.clock() - t_cache))

        self.dict_date_alc = ableton_aid.get_dict_date_alc(self.valid_alc_files, self.dict_file_cache)

        self.dict_date_sample = ableton_aid.get_dict_date_sample(self.valid_alc_files, self.dict_file_cache)

        ########
        # gui

        # aux class for text
        class EntryText:
            def __init__(self, root, initial_value='', text_width=8, take_focus=False, int_only=False, int_min=0,
                         int_max=999, update_fun=lambda: None):
                self.int_only = int_only
                self.int_min = int_min
                self.int_max = int_max
                self.update_fun = update_fun
                if int_only: self.last_int_value = int(initial_value)

                self.stringvar = StringVar(root)
                self.stringvar.set(initial_value)
                self.stringvar.trace("w", lambda name, index, mode: self.update())
                if take_focus:
                    takefocus_num = 1
                else:
                    takefocus_num = 0
                self.entry = Entry(root, textvariable=self.stringvar, width=text_width, takefocus=takefocus_num)
                self.entry.bind("<Escape>", self.key_escape)
                # self.entry.bind("<Meta_L>", self.insert_space) #doesn't work anymore
                self.entry.bind("<X>", lambda _: self.insert_space())
                self.entry.bind("<Up>", self.key_uparrow)
                self.entry.bind("<Down>", self.key_downarrow)
                self.entry.pack(side=LEFT)

            def update(self):
                if self.int_only: self.update_int()
                self.update_fun()

            def update_int(self):
                int_value = self.get_int()
                if int_value is not None and int_value >= self.int_min and int_value <= self.int_max:
                    self.last_int_value = int_value
                else:
                    self.stringvar.set(self.last_int_value)

            def clear(self):
                self.stringvar.set('')

            def insert_space(self):
                self.entry.insert(INSERT, ' ')
                return self.key_break()

            def key_break(self):
                return "break"

            def key_escape(self, arg):
                self.clear()

            def key_uparrow(self, arg):
                self.int_plus()
                return self.key_break()

            def key_downarrow(self, arg):
                self.int_minus()
                return self.key_break()

            def int_plus(self):
                int_value = self.get_int()
                if int_value is not None:
                    if int_value < self.int_max:
                        self.stringvar.set(int_value + 1)

            def int_minus(self):
                int_value = self.get_int()
                if int_value is not None:
                    if int_value > self.int_min:
                        self.stringvar.set(int_value - 1)

            def get_int(self):
                try:
                    return int(self.stringvar.get())
                except:
                    return None

            def set(self, x):
                self.stringvar.set(x)

        # end aux class


        #######
        path_stem = os.path.split(os.path.abspath('.'))[1]
        print path_stem
        master.title("Ableton Aid (%s)" % path_stem)

        #################
        # first row
        frame_top = Frame(master)
        frame_top.pack(side=TOP, fill=X)

        self.entry_filter = EntryText(frame_top, text_width=search_width, take_focus=True,
                                      update_fun=self.update_listbox)
        self.entry_bpm = EntryText(frame_top, text_width=3, int_min=0, int_max=999, take_focus=True,
                                   update_fun=self.update_listbox)
        self.entry_bpm_range = EntryText(frame_top, take_focus=True, int_only=True, initial_value=str(init_bpm_range),
                                         text_width=1, int_min=0, int_max=9, update_fun=self.update_listbox)

        self.order_list = self.get_order_list()
        self.order_var = StringVar(frame_top)
        self.order_var.trace("w", lambda name, index, mode: self.generate_and_set_from_current_button())
        self.order_var.set(self.order_list[0])
        for s in self.order_list:
            b = Radiobutton(frame_top, text=s + ' ', variable=self.order_var, value=s, takefocus=0)
            b.pack(side=LEFT, anchor=W)

        #################
        # second row
        tag_list = self.get_tag_list()
        frame_edit = Frame(master)
        frame_edit.pack(side=TOP, fill=X)

        # extra stuff...put it first on line 2
        self.entry_bpm_edit = None
        self.entry_key_edit = None
        self.entry_tag_filter = None

        if include_extra:
            self.entry_bpm_edit = EntryText(frame_edit, int_only=True, initial_value='0', text_width=3,
                                            update_fun=self.update_bpm_edit)
            self.entry_key_edit = EntryText(frame_edit, text_width=4, update_fun=self.update_key_edit)

        self.entry_key_filter = EntryText(frame_edit, take_focus=True, text_width=4, int_min=1, int_max=12,
                                          update_fun=self.update_listbox)
        self.entry_key_filter_range = EntryText(frame_edit, take_focus=True, int_only=True,
                                                initial_value=str(init_key_range), text_width=1, int_min=0, int_max=6,
                                                update_fun=self.update_listbox)

        # new fun extra key bits
        self.key_var_1 = IntVar(master)
        self.key_var_1.trace('w', lambda a, b, c: self.update_listbox())
        self.key_button_1 = Checkbutton(frame_edit, text="1", variable=self.key_var_1, takefocus=0)
        self.key_button_1.pack(side=LEFT)

        self.key_var_2 = IntVar(master)
        self.key_var_2.trace('w', lambda a, b, c: self.update_listbox())
        self.key_button_2 = Checkbutton(frame_edit, text="2", variable=self.key_var_2, takefocus=0)
        self.key_button_2.pack(side=LEFT)

        self.key_var_4 = IntVar(master)
        self.key_var_4.trace('w', lambda a, b, c: self.update_listbox())
        self.key_button_4 = Checkbutton(frame_edit, text="4", variable=self.key_var_4, takefocus=0)
        self.key_button_4.pack(side=LEFT)

        self.key_var_star = IntVar(master)
        self.key_var_star.trace('w', lambda a, b, c: self.update_listbox())
        self.key_button_star = Checkbutton(frame_edit, text="*", variable=self.key_var_star, takefocus=0)
        self.key_button_star.pack(side=LEFT)

        # tag filter not extra????
        self.entry_tag_filter = EntryText(frame_edit, text_width=tag_filter_width, update_fun=self.update_listbox)

        self.tag_var = StringVar(master)
        self.tag_var.set(tag_list[0])  # needed?
        self.tag_var.trace('w', lambda a, b, c: self.update_listbox())
        self.tag_list_menu = OptionMenu(frame_edit, self.tag_var, *tag_list)
        self.tag_list_menu.pack(side=LEFT)

        self.tag_invert_var = IntVar(master)
        self.tag_invert_var.trace('w', lambda a, b, c: self.update_listbox())
        self.tag_invert_button = Checkbutton(frame_edit, text="Invert", variable=self.tag_invert_var, takefocus=0)
        self.tag_invert_button.pack(side=LEFT)

        self.tag_vocal_var = IntVar(master)
        self.tag_vocal_var.trace('w', lambda a, b, c: self.update_listbox())
        self.tag_vocal_button = Checkbutton(frame_edit, text="[Vocal]", variable=self.tag_vocal_var, takefocus=0)
        self.tag_vocal_button.pack(side=LEFT)

        self.tag_ss_var = IntVar(master)
        self.tag_ss_var.trace('w', lambda a, b, c: self.update_listbox())
        self.tag_ss_button = Checkbutton(frame_edit, text="[SS]", variable=self.tag_ss_var, takefocus=0)
        self.tag_ss_button.pack(side=LEFT)

        self.year_var = IntVar(master)
        self.year_var.trace('w', lambda a, b, c: self.update_listbox())
        self.year_button = Checkbutton(frame_edit, text="Year", variable=self.year_var, takefocus=0)
        # self.year_button.pack(side=LEFT)

        self.month_var = IntVar(master)
        self.month_var.trace('w', lambda a, b, c: self.update_listbox())
        self.month_button = Checkbutton(frame_edit, text="Mon", variable=self.month_var, takefocus=0)
        # self.month_button.pack(side=LEFT)

        self.day_var = IntVar(master)
        self.day_var.trace('w', lambda a, b, c: self.update_listbox())
        self.day_button = Checkbutton(frame_edit, text="Day", variable=self.day_var, takefocus=0)
        #self.day_button.pack(side=LEFT)

        self.day_3_var = IntVar(master)
        self.day_3_var.trace('w', lambda a, b, c: self.update_listbox())
        self.day_3_button = Checkbutton(frame_edit, text="3-Day", variable=self.day_3_var, takefocus=0)
        # self.day_3_button.pack(side=LEFT)

        self.reveal_var = IntVar(master)
        # no need for this:
        # self.day_3_var.trace('w', lambda a,b,c: self.update_listbox())
        self.reveal_button = Checkbutton(frame_edit, text="Reveal", variable=self.reveal_var, takefocus=0)
        # self.reveal_button.pack(side=LEFT)

        self.friends_var = IntVar(master)
        self.friends_var.trace('w', lambda a, b, c: self.update_listbox())
        self.friends_button = Checkbutton(frame_edit, text="Friends", variable=self.friends_var, takefocus=0)
        # self.friends_button.pack(side=LEFT)

        min_label = Label(frame_edit, text="M:")
        min_label.pack(side=LEFT)
        self.min_amount = EntryText(frame_edit, int_only=True, initial_value=str(0), text_width=1, int_min=0, int_max=9,
                                    update_fun=self.update_listbox)
        self.max_amount = EntryText(frame_edit, int_only=True, initial_value=str(0), text_width=1, int_min=0, int_max=9,
                                    update_fun=self.update_listbox)

        #################
        # last row (listbox)

        frame = Frame(master)
        frame.pack(fill=BOTH, expand=1)

        self.scrollbar = Scrollbar(frame, orient=VERTICAL)
        self.listbox = Listbox(frame, yscrollcommand=self.scrollbar.set, width=listbox_width, height=listbox_height,
                               font=listbox_font)
        self.scrollbar.config(command=self.listbox.yview)
        self.listbox.pack(side=LEFT, fill=BOTH, expand=1)
        self.scrollbar.pack(side=RIGHT, fill=Y)

        self.listbox_target_string = None
        self.listbox_target_filename = None
        self.listbox.bind("<<ListboxSelect>>", self.listbox_select)
        self.listbox.bind("<Double-Button-1>", lambda _: self.command_copy())
        self.listbox.bind("<Button-1>", lambda _: self.listbox.focus_set())
        self.listbox.bind("<Return>", lambda _: self.command_copy())
        self.listbox.bind("c", lambda _: self.command_clear())
        self.listbox.bind("m", lambda _: self.command_clear_min_max())
        self.listbox.bind("t", lambda _: self.command_touch())
        self.listbox.bind("a", lambda _: self.command_tag_add())
        self.listbox.bind("r", lambda _: self.command_tag_remove())
        self.listbox.bind("s", lambda _: self.command_save())
        # self.listbox.bind("x", lambda _ : self.command_x())
        self.listbox.bind("v", lambda _: self.command_v())
        self.listbox.bind("f", lambda _: self.command_f())
        self.listbox.bind("g", lambda _: self.command_g())
        self.listbox.bind("n", lambda _: self.command_n())
        self.listbox.bind("j", lambda _: self.command_order_down())
        self.listbox.bind("k", lambda _: self.command_order_up())
        self.listbox.bind("p", lambda _: self.command_print())
        self.listbox.bind("l", lambda _: self.command_print_samples())
        self.listbox.bind("0", lambda _: self.command_0())
        self.listbox.bind("1", lambda _: self.command_1())
        self.listbox.bind("2", lambda _: self.command_2())
        self.listbox.bind("3", lambda _: self.command_3())
        self.listbox.bind("4", lambda _: self.command_4())
        self.listbox.bind("u", lambda _: self.command_update_key())

        self.last_copied_filename = None

        # initial update
        self.update_listbox()

        atexit.register(self.quit_handler)

    def quit_handler(self):
        self.save_dialog()

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
            new_bpm = record['bpm']
            new_key = record['key']
        except KeyError:
            pass
        # only update if UI elements exist
        if self.entry_bpm_edit:
            self.entry_bpm_edit.stringvar.set(new_bpm)
        if self.entry_key_edit:
            self.entry_key_edit.stringvar.set(new_key)

    def get_tag_list(self):
        result = []
        result.append('')
        # result.append(self.add_tag_string)
        # result.extend([x for _,x in ableton_aid.tag_shorthand.iteritems()])
        result.extend(self.extra_tag_list)
        # also check the dictionary
        # want to sort those from the dictionary
        others = set()
        for record in self.db_dict.itervalues():
            for tag in record['tags']:
                if tag not in result: others.add(tag)
        for tag in sorted(others):
            result.append(tag)
        # remove hidden
        result = [x for x in result if x not in self.hidden_tag_list]
        return result

    def is_valid_tag(self, tag):
        return tag is not None and tag != '' and tag != self.add_tag_string

    def update_listbox(self):
        time_start = time.clock()

        try:
            self.listbox
        except AttributeError:
            return

        # ts_list stuff
        ts_now = time.time()  # get it once at the beginning
        day_seconds = 60 * 60 * 24
        month_seconds = day_seconds * 30
        year_seconds = day_seconds * 365

        self.listbox.delete(0, END)
        self.active_alc_files = []

        tag = self.tag_var.get()
        tag_invert = bool(self.tag_invert_var.get())
        vocal_selected = bool(self.tag_vocal_var.get())
        ss_selected = bool(self.tag_ss_var.get())
        year_selected = bool(self.year_var.get())
        month_selected = bool(self.month_var.get())
        day_selected = bool(self.day_var.get())
        day_3_selected = bool(self.day_3_var.get())
        friends_selected = bool(self.friends_var.get())

        # prepare min / max filters
        min_plays = self.min_amount.get_int()
        max_plays = self.max_amount.get_int()

        # prepare friends filter
        # TODO: BROKEN
        # NEEDS print "searching for:", self.listbox_target_string, "or", self.listbox_target_filename
        friends_set = None
        max_friend_diff = 60 * 5
        if friends_selected:
            selected_filename = self.get_selected_filename()
            print 'friends_selected: selected_filename: ', selected_filename
            if selected_filename:
                friends_set = set()  # empty will also be like "None"
                target_ts_list = ableton_aid.get_ts_list(self.db_dict[selected_filename])
                print 'selected_filename', selected_filename
                print 'target_ts_list', target_ts_list
                for ts in target_ts_list:
                    for ts_other, f_list in self.ts_db_dict.iteritems():
                        diff = abs(ts_other - ts)
                        if diff < max_friend_diff:
                            for f in f_list:
                                friends_set.add(f)

        # prepare key filter
        # split = self.key_filter_string.split()
        # key_filter = split[0] if split else ''
        key_filter = self.entry_key_filter.stringvar.get().strip()
        cam_filter = ableton_aid.get_camelot_key(key_filter)
        # direct camelot allowed as well
        if cam_filter is None and len(key_filter) > 0 and key_filter[0].isdigit():
            # possible_lower = [s.lower() for s in ableton_aid.camelot_dict.values()]
            possible_lower = [s.lower() for s in ableton_aid.reverse_camelot_dict.keys()]
            if key_filter.lower() in possible_lower:
                cam_filter = key_filter
            # since major/minor doesn't matter, also allow just camelot numbers
            if cam_filter is None:
                fake_key_filter = key_filter + 'A'
                if fake_key_filter.lower() in possible_lower:
                    cam_filter = fake_key_filter
        # create the numbers from the filter
        # currently just need acceptable camelot numbers (ignore major minor)
        cam_filter_numbers = []
        key_filter_range = self.entry_key_filter_range.get_int()
        do_key_filter = not self.key_var_star.get()
        if do_key_filter and cam_filter and key_filter_range is not None:
            cam_filter_num = int(cam_filter[:-1])
            cam_filter_numbers.append(cam_filter_num)
            # add range
            for i in range(0, key_filter_range + 1):
                # python % is always positive
                cam_filter_numbers.append(((cam_filter_num + i - 1) % 12) + 1)
                cam_filter_numbers.append(((cam_filter_num - i - 1) % 12) + 1)
            # add variables
            if self.key_var_1.get(): cam_filter_numbers.append(((cam_filter_num + 1 - 1) % 12) + 1)
            if self.key_var_2.get(): cam_filter_numbers.append(((cam_filter_num + 2 - 1) % 12) + 1)
            if self.key_var_4.get(): cam_filter_numbers.append(((cam_filter_num + 4 - 1) % 12) + 1)

        filter_string = self.entry_filter.stringvar.get()
        filter_bpm = self.entry_bpm.get_int()
        filter_bpm_range = self.entry_bpm_range.get_int()
        tag_filter = None
        if self.entry_tag_filter:
            tag_filter = self.entry_tag_filter.stringvar.get()

        # just in case this is expensive...
        # also to allow vocals through for sets
        do_vocal_check = True
        if self.order_var.get() == 'sets': do_vocal_check = False

        select_index = 0
        filename_pairs_list = []  # insert them all at the end for speed?
        last_filename = None
        for filename in self.list_to_use:
            # never repeat yourself
            if filename == last_filename: continue

            # print names of those not in db_dict
            try:
                record = self.db_dict[filename]
            except KeyError:
                last_filename = filename  # note dupe
                filename_pairs_list.append((filename, None))
                continue

            bpm, tag_list, key = (record['bpm'], record['tags'], record['key'])
            ts_list = ableton_aid.get_ts_list(record)

            keep = True

            if min_plays > 0 and len(ts_list) < min_plays: keep = False
            if max_plays > 0 and len(ts_list) >= max_plays: keep = False

            # vocal affects others
            is_vocal = 'vocal' in tag_list
            if do_vocal_check:
                if is_vocal != vocal_selected: keep = False

            if friends_set:
                if filename not in friends_set: keep = False

            if filter_string:
                for s in filter_string.split():
                    if s.lower() not in filename.lower(): keep = False

            if filter_bpm is not None and self.skip_bpm_check_string not in tag_list:
                any_success = False
                bpm_range = filter_bpm_range
                if is_vocal: bpm_range += 10
                for sub_bpm in [int(round(bpm / 2.0)), bpm, int(round(bpm * 2.0))]:
                    if (sub_bpm >= filter_bpm - bpm_range and sub_bpm <= filter_bpm + bpm_range):
                        any_success = True
                if not any_success: keep = False

            # changing this to: some tag must have all bits of my search
            if tag_filter:
                any_success = False
                for t in (x.upper() for x in tag_list):
                    found_all_split = True
                    for s in (x.upper() for x in tag_filter.split()):
                        if s not in t: found_all_split = False
                    if found_all_split: any_success = True
                if not any_success: keep = False

            if tag:
                if tag_invert:
                    if tag in tag_list: keep = False
                else:
                    if tag not in tag_list: keep = False

            do_ss_check = True
            if do_ss_check:
                is_ss = 'SS' in tag_list
                if is_ss != ss_selected: keep = False

            # used beyond filter check
            cam_song = ableton_aid.get_camelot_key(key)

            if key_filter == '-' and len(key) > 0: keep = False
            if key_filter == '*' and len(key) == 0: keep = False
            if self.skip_key_check_string not in tag_list:
                if cam_filter_numbers:
                    if cam_song is None:
                        keep = False
                    else:
                        cam_song_num = int(cam_song[:-1])
                        if cam_song_num not in cam_filter_numbers: keep = False

                        # This is the only way to see x tags
            is_x = 'x' in tag_list and tag != 'x'
            if is_x: keep = False

            # time stuff
            if len(ts_list) > 0:
                seconds = ts_now - ts_list[-1]
                # only filter down if older than 10 minutes
                if seconds > 60 * 10:
                    if year_selected and seconds < year_seconds: keep = False
                    if month_selected and seconds < month_seconds: keep = False
                    if day_selected and seconds < day_seconds: keep = False
                    if day_3_selected and seconds < 3 * day_seconds: keep = False

            # take action, fool!
            if not keep: continue

            last_filename = filename

            file = ableton_aid.get_base_filename(filename, record)
            key_display = key
            if cam_song is not None:
                # key_display = key + ' : ' + cam_song
                # key_display = '%3s:%3s' % (key, cam_song)
                # check this with edit
                key_display = '%3s' % (cam_song)
            # cool_filename = ' %03d|%s|%02d| %s' % (bpm, key_display, len(ts_list), file)
            cool_filename = ' %03d|%s|%02d| %s' % (bpm, key_display, min(99, len(ts_list)), file)
            filename_pairs_list.append((cool_filename, filename))
        # done looping over all filenames

        # fill out the important results
        from itertools import groupby
        if filename_pairs_list:
            files_display, filenames = zip(*filename_pairs_list)
            t = time.time()
            self.listbox.insert(END, *files_display)
            print "self.listbox.insert(END, *files_display) took:", (time.time() - t)
            self.active_alc_files = filenames

        # search for previous_name
        # NOTE THAT IF PLAY COUNT HAS CHANGED, IT WON'T FIND
        # or anything else (key, etc, when editing)
        print "searching for:", self.listbox_target_string, "or", self.listbox_target_filename
        for i, pair in enumerate(filename_pairs_list):
            activate = False
            if pair[0] == self.listbox_target_string:
                print "listbox_target_string:", self.listbox_target_string
                activate = True
            elif self.listbox_target_filename and self.listbox_target_filename == pair[1]:
                print "listbox_target_filename:", self.listbox_target_filename
                activate = True
            if activate:
                self.listbox.select_set(i)
                self.listbox.activate(i)
                self.listbox.see(i)
                print "found: ", self.listbox_target_string
                break

        # no matter what (in addition to select)
        self.refresh_edit()

        print "Listbox length:", len(filename_pairs_list)

        # timing
        time_end = time.clock()
        print "[time] update_listbox:", str(time_end - time_start)

    def update_bpm_edit(self):
        filename = self.get_selected_filename()
        if not filename: return
        record = self.db_dict[filename]
        record['bpm'] = self.entry_bpm_edit.get_int()

    def update_key_edit(self):
        filename = self.get_selected_filename()
        if not filename: return
        record = self.db_dict[filename]
        record['key'] = self.entry_key_edit.stringvar.get()

    def get_selected_index(self):
        selected_items = self.listbox.curselection()
        try:
            index = int(selected_items[0])
        except IndexError:
            return None
        return index

    def get_selected_string(self):
        index = self.get_selected_index()
        if index is None: return None
        return self.listbox.get(index)

    def get_selected_filename(self):
        index = self.get_selected_index()
        if index is None: return None
        return self.active_alc_files[index]

    def get_selected_filepath(self):
        filename = self.get_selected_filename()
        if not filename: return None
        return os.path.abspath(filename)

    def get_filename_for_index(self, index):
        result = None
        try:
            result = self.active_alc_files[index]
        except IndexError:
            pass
        return result

    def command_copy(self):
        filename_path = self.get_selected_filepath()
        if not filename_path: return
        command = 'osascript -e "set the clipboard to POSIX file \\"%s\\""' % filename_path
        print command
        subprocess.call(command, shell=True)
        # also record select in database
        filename = self.get_selected_filename()
        if not filename: return  # impossible
        if filename == self.last_copied_filename: return
        self.last_copied_filename = filename
        record = self.db_dict[filename]
        ts = time.time()
        try:
            record['ts_list'].append(ts)
        except KeyError:
            record['ts_list'] = [ts]
        # and finally reveal if wanted
        if bool(self.reveal_var.get()):
            print ("reveal:", filename)
            ableton_aid.reveal_file(filename)
        # and of course (recently) add in a cache variable
        self.last_copy_filename = filename

    def command_touch(self):
        filename_path = self.get_selected_filepath()
        if not filename_path: return
        os.utime(filename_path, None)
        filename = self.get_selected_filename()
        self.dict_date_alc[filename] = time.time()
        print 'touched', filename_path

    def command_tag_add(self):
        filename = self.get_selected_filename()
        if not filename: return
        tag = self.tag_var.get()
        self.add_tag_to_filename(filename, tag)

    def command_tag_remove(self):
        filename = self.get_selected_filename()
        if not filename: return
        tag = self.tag_var.get()
        if not self.is_valid_tag(tag): return
        record = self.db_dict[filename]
        try:
            record['tags'].remove(tag)
        except ValueError:
            pass
        self.update_listbox()

    def save_dialog(self):
        do_save = tkMessageBox.askokcancel("Confirm Save", 'Save database "%s"?' % self.db_filename)
        if (do_save):
            ableton_aid.write_db_file(self.db_filename, self.db_dict)

    def command_save(self):
        return self.save_dialog()

    def add_tag_to_filename(self, filename, tag):
        if not self.is_valid_tag(tag): return
        record = self.db_dict[filename]
        if tag not in record['tags']:
            record['tags'].append(tag)
        old_index = self.get_selected_index()
        self.update_listbox()
        self.listbox.activate(old_index)
        self.listbox.see(old_index)

    def command_x(self):
        filename = self.get_selected_filename()
        if not filename: return
        tag = 'x'
        self.add_tag_to_filename(filename, tag)

    def command_key_unused(self):
        filepath = self.get_selected_filepath()
        if not filepath: return
        found_key = ableton_aid.get_key_from_alc(filepath)
        if not ableton_aid.get_camelot_key(found_key): return
        self.stringvar_key.set(found_key)

    def command_v(self):
        self.tag_vocal_var.set(not bool(self.tag_vocal_var.get()))

    def command_0(self):
        self.key_var_star.set(not bool(self.key_var_star.get()))

    def command_1(self):
        self.key_var_1.set(not bool(self.key_var_1.get()))

    def command_2(self):
        self.key_var_2.set(not bool(self.key_var_2.get()))

    def command_3(self):
        pass

    def command_4(self):
        self.key_var_4.set(not bool(self.key_var_4.get()))

    def command_update_key(self):
        filename = self.get_selected_filename()
        if not filename: return
        record = self.db_dict[filename]
        record['key'] = ''

    def command_f(self):
        self.friends_var.set(not bool(self.friends_var.get()))

    def command_g(self):
        filename = self.get_selected_filename()
        if not filename: return
        tag = 'GOOD'
        self.add_tag_to_filename(filename, tag)

    def command_n(self):
        filename = self.get_selected_filename()
        if not filename: return
        tag = '-NN'
        self.add_tag_to_filename(filename, tag)

    def command_print(self):
        index = self.get_selected_index()
        if index is None: return
        count = 100
        reverse = True
        result = []
        for i in xrange(index, index + count):
            filename = self.get_filename_for_index(i)
            result.append(filename)
        if reverse:
            result.reverse()
        for f in result:
            print f

    def command_print_samples(self):
        output_filename = 'print_samples.m3u'
        # file_output = open(output_filename, 'w')
        file_output = codecs.open(output_filename, 'w', 'utf-8')
        for i, filename in enumerate(self.active_alc_files):
            cache_dict = self.dict_file_cache[filename]
            # print filename
            # print cache_dict
            file_output.write(cache_dict['sample_file'] + '\n')

    def command_clear_min_max(self):
        print 'clear min max'
        self.min_amount.set(0)
        self.max_amount.set(0)

    def command_order_down(self):
        print ("command_order_down")
        var = self.order_var.get()
        which = self.order_list.index(var)
        which -= 1
        if which < 0: which = len(self.order_list) - 1
        self.order_var.set(self.order_list[which])

    def command_order_up(self):
        print ("command_order_up")
        var = self.order_var.get()
        which = self.order_list.index(var)
        which += 1
        if which >= len(self.order_list): which = 0
        self.order_var.set(self.order_list[which])

    def command_clear(self):
        self.command_clear_min_max()
        self.entry_filter.clear()
        self.entry_bpm.clear()
        self.entry_key_filter.clear()
        self.entry_tag_filter.clear()

    def generate_and_set_from_current_button(self):
        t = time.time()
        self.list_to_use = self.valid_alc_files
        # ignore 'name'...it's the default
        if (self.order_var.get() == 'bpm'):
            self.list_to_use = self.generate_bpm()
        elif (self.order_var.get() == 'date'):
            self.list_to_use = self.generate_date()
        elif (self.order_var.get() == 'sample'):
            self.list_to_use = self.generate_sample()
        elif (self.order_var.get() == 'alc'):
            self.list_to_use = self.generate_alc()
        elif (self.order_var.get() == 'random'):
            self.list_to_use = self.generate_random()
        elif (self.order_var.get() == 'key'):
            self.list_to_use = self.generate_key()
        elif (self.order_var.get() == 'num'):
            self.list_to_use = self.generate_num()
        elif (self.order_var.get() == 'sets'):
            self.list_to_use = self.generate_sets
        print "[time] generate_and_set_from_current_button:", str(time.time() - t)
        self.update_listbox()

    def generate_random(self):
        files = list(self.valid_alc_files)
        random.shuffle(files)
        return files

    def generate_date(self):
        return ableton_aid.generate_date(self.valid_alc_files, self.db_dict)

    def generate_alc(self):
        return ableton_aid.generate_alc(self.valid_alc_files, self.dict_date_alc)

    def generate_sample(self):
        return ableton_aid.generate_sample(self.valid_alc_files, self.dict_date_sample)

    def generate_bpm(self):
        bpm_file_tuples = []
        for file in self.valid_alc_files:
            record = self.db_dict[file]
            bpm_file_tuples.append((record['bpm'], file))
        bpm_file_tuples.sort()
        return [file for _, file in bpm_file_tuples]

    def generate_key(self):
        key_file_tuples = []
        for file in self.valid_alc_files:
            record = self.db_dict[file]
            key_song = record['key']
            cam_song = ableton_aid.get_camelot_key(key_song)
            if cam_song is not None:
                cam_sort = ('%02d' % int(cam_song[:-1])) + cam_song[-1]
                key_file_tuples.append((cam_sort, file))
            else:
                key_file_tuples.append(('Z', file))
        key_file_tuples.sort()
        return [file for _, file in key_file_tuples]

    def generate_num(self):
        return ableton_aid.get_files_by_num(self.valid_alc_files, self.db_dict)

    def generate_sets(self):
        ts_db_dict = ableton_aid.get_db_by_ts(self.db_dict)
        result = []
        ts_last = time.time()
        for ts, file_list in sorted(ts_db_dict.iteritems(), reverse=True):
            if not file_list: continue
            if ts_last - ts > 10 * 60:
                pretty_date = datetime.date.fromtimestamp(ts).isoformat()
                result.append('--- %s' % pretty_date)
            ts_last = ts
            for f in file_list:
                result.append(f)

        return result


if __name__ == '__main__':
    # get db filename
    argv_iter = iter(sys.argv)
    _ = argv_iter.next()
    db_filename = argv_iter.next()
    always_on_top = False
    include_extra = False
    try:
        while (True):
            flag = argv_iter.next()
            if flag == '-t': always_on_top = True
            if flag == '-e': include_extra = True
    except StopIteration:
        pass

    master = Tk()
    app = App(master, db_filename, include_extra)
    if always_on_top: master.call('wm', 'attributes', '.', '-topmost', '1')
    master.mainloop()
