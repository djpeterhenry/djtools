from Tkinter import *

class EntryText:
    def __init__(self, root, initial_value='', text_width=8, take_focus=False, int_only=False, int_min=0,
                 int_max=999, update_fun=lambda: None):
        self.last_int_value = None
        self.int_only = int_only
        self.int_min = int_min
        self.int_max = int_max

        self.update_fun = update_fun

        # TODO: callback before set?
        self.stringvar = StringVar(root)
        self.stringvar.set(initial_value)
        self.stringvar.trace("w", lambda name, index, mode: self.update())

        if take_focus:
            takefocus_num = 1
        else:
            takefocus_num = 0
        self.entry = Entry(root, textvariable=self.stringvar, width=text_width, takefocus=takefocus_num)

        self.entry.bind("<Escape>", self.key_escape)
        self.entry.bind("<X>", lambda _: self.insert_space())
        self.entry.bind("<Up>", self.key_uparrow)
        self.entry.bind("<Down>", self.key_downarrow)

        self.entry.pack(side=LEFT)

    def update(self):
        print 'update'
        self.update_int()
        self.update_fun()

    def update_int(self):
        if not self.int_only:
            return
        parse_int = self.parse_int()

        # if invalid, set to last
        # otherwise we have a valid int!
        if parse_int is None or parse_int < self.int_min or parse_int > self.int_max:
            self.stringvar.set(self.last_int_value or '')
        else:
            self.last_int_value = parse_int

    def clear(self):
        self.last_int_value = None
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

    def parse_int(self):
        try:
            return int(self.stringvar.get())
        except:
            return None

    def set(self, x):
        self.stringvar.set(x)
