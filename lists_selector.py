from Tkinter import *

import os

class ListsSelector:
    def __init__(self, root, path, update_function=None):
        self.update_function = update_function

        # update with file contents:
        self.song_list = None

        files = [os.path.join(path, f) for f in os.listdir(path)]
        self.name_to_file = {os.path.splitext(os.path.split(f)[1])[0]:f
            for f in files if os.path.splitext(f)[1] == '.txt'}
        names_to_list = [''] + sorted(list(self.name_to_file.iterkeys()))

        self.string_var = StringVar(root)
        self.string_var.trace('w', lambda a, b, c: self.update())
        # self.string_var.set(names_to_list[0])
        self.option_menu = OptionMenu(root, self.string_var, *names_to_list)
        self.option_menu.pack(side=LEFT)

        #self.disabled_var =
        self.disabled_var = IntVar(root)
        self.disabled_var.trace('w', lambda a, b, c: self.update())
        disabled_key_button = Checkbutton(root, text="*", variable=self.disabled_var, takefocus=0)
        disabled_key_button.pack(side=LEFT)


    def update(self):
        if self.disabled_var.get():
            self.song_list = None
        else:
            try:
                with open(self.name_to_file[self.string_var.get()]) as f:
                    self.song_list = [song.strip() for song in f.readlines()]
            except:
                self.song_list = None
        # inform of update
        if self.update_function:
            self.update_function()
        # debug print (useful for copying too)
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
            if s in db_dict:
                result.append(s)
            elif als_filename in db_dict:
                result.append(als_filename)
            elif alc_filename in db_dict:
                result.append(alc_filename)
            else:
                result.append(s)
        return result
