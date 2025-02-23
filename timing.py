from functools import wraps
import time

def timing(f, show_args=False):
    @wraps(f)
    def wrap(*args, **kw):
        ts = time.time()
        result = f(*args, **kw)
        te = time.time()
        args_str = ""
        if show_args:
            args_str = "args:[%r, %r]" % (args, kw)
        print('func:%r %s took: %2.4f sec' % \
          (f.__name__, args_str, te-ts))
        return result
    return wrap
