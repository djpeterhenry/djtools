from Tkinter import Checkbutton, IntVar, LEFT

class Checkbox(object):
    def __init__(self, parent, text, callback=None):
        self.var = IntVar(parent)
        if callback is not None:
            self.var.trace('w', callback)
        self.button = Checkbutton(
            parent, text=text, variable=self.var, takefocus=0)
        self.button.pack(side=LEFT)

    def get(self):
        return self.var.get()

    def toggle(self):
        self.var.set(not bool(self.get()))

# do some sort of enum menu
# self.which_files_var = StringVar(master)
# self.which_files_var.trace('w', just_update)
# self.which_files_menu = OptionMenu(
#     frame_edit, self.which_files_var, *[x.name for x in WhichFiles])
# self.which_files_menu.config(width=10)
# self.which_files_menu.pack(side=LEFT)