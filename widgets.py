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