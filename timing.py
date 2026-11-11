from collections.abc import Callable
from functools import wraps
import time
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def timing(f: Callable[P, R], show_args: bool = False) -> Callable[P, R]:
    @wraps(f)
    def wrap(*args: P.args, **kw: P.kwargs) -> R:
        ts = time.time()
        result = f(*args, **kw)
        te = time.time()
        args_str = ""
        if show_args:
            args_str = "args:[%r, %r]" % (args, kw)
        print("func:%r %s took: %2.4f sec" % (f.__name__, args_str, te - ts))
        return result

    return wrap
