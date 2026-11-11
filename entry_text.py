import tkinter as tk
from collections.abc import Callable


class EntryText:
    def __init__(
        self,
        root: tk.Misc,
        initial_value: str = "",
        text_width: int = 8,
        take_focus: bool = False,
        int_only: bool = False,
        int_min: int = 0,
        int_max: int = 999,
        update_fun: Callable[[], object] = lambda: None,
    ) -> None:
        self.last_int_value: int | None = None
        self.int_only = int_only
        self.int_min = int_min
        self.int_max = int_max

        self.update_fun = update_fun

        # TODO: callback before set?
        self.stringvar = tk.StringVar(root)
        self.stringvar.set(initial_value)
        self.stringvar.trace_add("write", lambda name, index, mode: self.update())

        self.entry = tk.Entry(
            root, textvariable=self.stringvar, width=text_width, takefocus=take_focus
        )

        self.entry.bind("<Escape>", self.key_escape)
        self.entry.bind("<X>", lambda _: self.insert_space())
        self.entry.bind("<Up>", self.key_uparrow)
        self.entry.bind("<Down>", self.key_downarrow)

        self.entry.pack(side=tk.LEFT)

    def update(self) -> None:
        self.update_int()
        self.update_fun()

    def update_int(self) -> None:
        if not self.int_only:
            return
        parse_int = self.get_int()

        # if invalid, set to last
        # otherwise we have a valid int!
        if parse_int is None or parse_int < self.int_min or parse_int > self.int_max:
            last = self.last_int_value
            self.stringvar.set("" if last is None else str(last))
        else:
            self.last_int_value = parse_int

    def clear(self) -> None:
        self.last_int_value = None
        self.stringvar.set("")

    def insert_space(self) -> str:
        self.entry.insert(tk.INSERT, " ")
        return self.key_break()

    def key_break(self) -> str:
        return "break"

    def key_escape(self, arg: object) -> None:
        self.clear()

    def key_uparrow(self, arg: object) -> str:
        self.int_plus()
        return self.key_break()

    def key_downarrow(self, arg: object) -> str:
        self.int_minus()
        return self.key_break()

    def int_plus(self) -> None:
        int_value = self.get_int()
        if int_value is not None:
            if int_value < self.int_max:
                self.stringvar.set(str(int_value + 1))

    def int_minus(self) -> None:
        int_value = self.get_int()
        if int_value is not None:
            if int_value > self.int_min:
                self.stringvar.set(str(int_value - 1))

    def get_int(self) -> int | None:
        try:
            return int(self.stringvar.get())
        except ValueError:
            return None

    def set(self, x: str | int) -> None:
        self.stringvar.set(str(x))
