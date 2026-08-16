"""Shared helpers for the little local web servers (history_server, song_server)."""

import os
import signal
import subprocess
import time


def kill_existing_server(port, wait=1):
    """Kill any other process listening on port, so only one copy ever runs.

    The port itself is the lock -- no pidfile to go stale. Returns the pids
    that were signalled.
    """
    result = subprocess.run(
        ["lsof", "-ti", ":%d" % port, "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
    )
    pids = [int(p) for p in result.stdout.split() if int(p) != os.getpid()]
    for pid in pids:
        print("Stopping previous server (PID %d)..." % pid)
        os.kill(pid, signal.SIGTERM)
    if pids:
        time.sleep(wait)
    return pids
