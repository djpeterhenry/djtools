from Tkinter import *

import os

class ListsSelector:
    def __init__(self, root, path, update_function=None):
        self.update_function = update_function

        files = [os.path.join(path, f) for f in os.listdir(path)]
        self.name_to_file = {os.path.splitext(os.path.split(f)[1])[0]:f for f in files}
        names_to_list = [''] + sorted(list(self.name_to_file.iterkeys()))

        self.string_var = StringVar(root)
        self.string_var.trace('w', lambda a, b, c: self.update())
        # self.string_var.set(names_to_list[0])
        self.option_menu = OptionMenu(root, self.string_var, *names_to_list)
        self.option_menu.pack(side=LEFT)

        self.song_list = None


    def update(self):
        print 'ListsSelector update'
        try:
            with open(self.name_to_file[self.string_var.get()]) as f:
                self.song_list = [song.strip() for song in f.readlines()]
        except:
            self.song_list = None
        if self.update_function:
            self.update_function()
        # debug print
        if self.song_list:
            for s in self.song_list:
                print s


    def get_song_list(self, db_dict):
        if not self.song_list:
            return None
        result = []
        for s in self.song_list:
            alc_filename = s + '.alc'
            als_filename = s + '.als'
            if alc_filename in db_dict:
                result.append(alc_filename)
            elif als_filename in db_dict:
                result.append(als_filename)
            else:
                result.append(s)
        return result
