import tkinter as tk


class Checkbox(object):
    def __init__(self, parent, text, callback=None):
        self.var = tk.IntVar(parent)
        if callback is not None:
            self.var.trace_add("write", callback)
        self.button = tk.Checkbutton(parent, text=text, variable=self.var, takefocus=0)
        self.button.pack(side=tk.LEFT)

    def get(self):
        return self.var.get()

    def toggle(self):
        self.var.set(not bool(self.get()))
