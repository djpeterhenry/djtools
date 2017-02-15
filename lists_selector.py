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
        # print
        if self.song_list:
            for s in self.song_list:
                print s
