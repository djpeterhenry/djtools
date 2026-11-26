import tkinter as tk
from collections.abc import Callable


class Checkbox:
    def __init__(
        self, parent: tk.Misc, text: str, callback: Callable[[str, str, str], object] | None = None
    ) -> None:
        self.var = tk.IntVar(parent)
        if callback is not None:
            self.var.trace_add("write", callback)
        self.button = tk.Checkbutton(parent, text=text, variable=self.var, takefocus=0)
        self.button.pack(side=tk.LEFT)

    def get(self) -> int:
        return self.var.get()

    def toggle(self) -> None:
        self.var.set(0 if self.get() else 1)
