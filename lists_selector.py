import os
import tkinter as tk

import ableton_aid as aa


class ListsSelector:
    def __init__(self, root, path, update_function=None):
        self.path = path
        self.update_function = update_function

        # update with file contents:
        self.song_list = None

        # safe to early exit contructor here if path isn't valid
        if not os.path.exists(path):
            return

        self.string_var = tk.StringVar(root)
        self.string_var.trace_add("write", lambda a, b, c: self.update())
        self.option_menu = tk.OptionMenu(
            root, self.string_var, *self.update_and_get_names()
        )
        self.option_menu.pack(side=tk.LEFT)

        self.disabled_var = tk.IntVar(root)
        self.disabled_var.trace_add("write", lambda a, b, c: self.update())
        disabled_key_button = tk.Checkbutton(
            root, text="*", variable=self.disabled_var, takefocus=0
        )
        disabled_key_button.pack(side=tk.LEFT)

    def update_and_get_names(self):
        self.name_to_file = aa.get_list_name_to_file(self.path)
        names_to_list = [""] + sorted(self.name_to_file.keys(), key=lambda x: x.lower())
        return names_to_list

    def update(self):
        if self.disabled_var.get():
            self.song_list = None
        else:
            # the blank "no list" entry has no file
            list_file = self.name_to_file.get(self.string_var.get())
            if list_file is None:
                self.song_list = None
            else:
                with open(list_file) as f:
                    self.song_list = [song.strip() for song in f.readlines()]
        # inform of update
        if self.update_function:
            self.update_function()
        # debug print (useful for copying too)
        if self.song_list:
            for s in self.song_list:
                print(s)

    def get_song_list(self, db_dict):
        if not self.song_list:
            return None
        # Songs not in the db stay as their raw line
        result = []
        for s in self.song_list:
            _, filename = aa.get_song_in_db(s, db_dict)
            result.append(filename or s)
        return result
