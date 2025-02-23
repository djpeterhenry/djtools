from __future__ import print_function

import sys

if sys.version_info[0] == 3:
    import tkinter as tk
else:
    import Tkinter as tk


class Checkbox(object):
    def __init__(self, parent, text, callback=None):
        self.var = tk.IntVar(parent)
        if callback is not None:
            self.var.trace("w", callback)
        self.button = tk.Checkbutton(parent, text=text, variable=self.var, takefocus=0)
        self.button.pack(side=tk.LEFT)

    def get(self):
        return self.var.get()

    def toggle(self):
        self.var.set(not bool(self.get()))
