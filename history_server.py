#!/usr/bin/env python3.11
"""Serves the most recent Rekordbox history as a live-updating web page."""

import json
import logging
import os
import signal
import subprocess
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrekordbox import Rekordbox6Database

# We know Rekordbox is running; we only read, never commit, so this is safe.
logging.getLogger("pyrekordbox.db6.database").setLevel(logging.ERROR)

PORT = 8888
POLL_INTERVAL = 1  # seconds

# Now Playing page settings
NOW_WIDTH = 1920
NOW_HEIGHT = 1080
NOW_FONT_SIZE = "48px"
NOW_ARTIST_SIZE = "1.2em"
NOW_TITLE_SIZE = "1.1em"
NOW_YEAR_SIZE = "0.9em"
NOW_LEFT_PAD = 20
NOW_BOTTOM_PAD = 20
NOW_STALE_MINUTES = 10  # show "Waiting for update" if last track is older than this


def get_latest_history_songs():
    db = Rekordbox6Database()
    histories = list(db.get_history())
    if not histories:
        db.close()
        return []
    latest = histories[-1]
    songs = list(db.get_history_songs(HistoryID=latest.ID))
    result = {
        "name": latest.Name,
        "songs": [],
    }
    for s in songs:
        c = s.Content
        # Strip the tag suffixes from title (everything after many spaces)
        title = c.Title
        if "   " in title:
            title = title[: title.index("   ")].strip()
        artist = c.Artist.Name if c.Artist else ""
        result["songs"].append(
            {
                "track_no": s.TrackNo,
                "title": title,
                "artist": artist,
                "played_at": str(s.created_at),
                "year": c.ReleaseYear,
            }
        )
    db.close()
    return result


HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Rekordbox History</title>
<style>
  body {
    background: #1a1a2e; color: #eee; font-family: -apple-system, sans-serif;
    margin: 0; padding: 20px;
  }
  h1 { color: #e94560; margin-bottom: 4px; }
  h2 { color: #999; font-weight: normal; margin-top: 0; }
  table { border-collapse: collapse; width: 100%%; max-width: 900px; }
  th { text-align: left; color: #e94560; border-bottom: 2px solid #333; padding: 8px; }
  td { padding: 8px; border-bottom: 1px solid #2a2a3e; }
  tr:hover { background: #2a2a3e; }
  .track-no { color: #666; width: 40px; }
  .year { color: #888; font-size: 0.9em; }
  .time { color: #888; font-size: 0.9em; }
  .new-row { animation: flash 1s ease-out; }
  @keyframes flash { from { background: #e9456033; } to { background: transparent; } }
</style>
</head>
<body>
<h1>Rekordbox History</h1>
<h2 id="history-name"></h2>
<table>
  <thead><tr><th>#</th><th>Title</th><th>Artist</th><th>Year</th><th>Played At</th></tr></thead>
  <tbody id="songs"></tbody>
</table>
<script>
let lastCount = 0;
async function poll() {
  try {
    const resp = await fetch("/api/history");
    const data = await resp.json();
    document.getElementById("history-name").textContent = data.name;
    const tbody = document.getElementById("songs");
    const newCount = data.songs.length;
    tbody.innerHTML = "";
    data.songs.forEach((s, i) => {
      const tr = document.createElement("tr");
      if (i >= lastCount && lastCount > 0) tr.className = "new-row";
      tr.innerHTML =
        '<td class="track-no">' + s.track_no + "</td>" +
        "<td>" + esc(s.title) + "</td>" +
        "<td>" + esc(s.artist) + "</td>" +
        '<td class="year">' + (s.year || "") + "</td>" +
        '<td class="time">' + fmtTime(s.played_at) + "</td>";
      tbody.appendChild(tr);
    });
    lastCount = newCount;
  } catch (e) {
    console.error(e);
  }
}
function esc(s) {
  const d = document.createElement("div"); d.textContent = s; return d.innerHTML;
}
function fmtTime(s) {
  if (!s) return "";
  const d = new Date(s);
  return d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
}
poll();
setInterval(poll, %(poll_ms)d);
</script>
</body>
</html>
"""

NOW_PLAYING_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Now Playing</title>
<style>
  body {
    background: %(now_bg)s; color: white; font-family: -apple-system, sans-serif;
    margin: 0; padding: 0; text-transform: uppercase;
    width: %(now_width)dpx; height: %(now_height)dpx;
    font-size: %(now_font_size)s; overflow: hidden;
  }
  #now {
    position: absolute; bottom: %(now_bottom_pad)dpx; left: %(now_left_pad)dpx;
  }
  #now { max-width: %(now_width)dpx; }
  #artist { font-size: %(now_artist_size)s; font-weight: bold; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #title { font-size: %(now_title_size)s; margin: 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #year { font-size: %(now_year_size)s; margin: 4px 0; }
  .fade { animation: fadein 0.5s ease-in; }
  @keyframes fadein { from { opacity: 0; } to { opacity: 1; } }
</style>
</head>
<body>
<div id="now">
  <p id="artist"></p>
  <p id="title"></p>
  <p id="year"></p>
</div>
<script>
let lastTitle = "";
const STALE_MS = %(now_stale_minutes)d * 60 * 1000;
async function poll() {
  try {
    const resp = await fetch("/api/history");
    const data = await resp.json();
    if (!data.songs || !data.songs.length) return;
    const s = data.songs[data.songs.length - 1];
    const age = Date.now() - new Date(s.played_at).getTime();
    const stale = age > STALE_MS;
    const display = stale ? "" : s.title;
    if (display !== lastTitle) {
      const el = document.getElementById("now");
      el.classList.remove("fade");
      void el.offsetWidth;
      el.classList.add("fade");
      document.getElementById("artist").textContent = stale ? "" : s.artist;
      document.getElementById("title").textContent = stale ? "" : s.title;
      document.getElementById("year").textContent = stale ? "" : (s.year || "");
      lastTitle = display;
    }
  } catch (e) {
    console.error(e);
  }
}
poll();
setInterval(poll, %(poll_ms)d);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/history":
            data = get_latest_history_songs()
            payload = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.write(payload)
        elif self.path in ("/now", "/now-debug"):
            page = (NOW_PLAYING_HTML % {
                "poll_ms": POLL_INTERVAL * 1000,
                "now_width": NOW_WIDTH,
                "now_height": NOW_HEIGHT,
                "now_font_size": NOW_FONT_SIZE,
                "now_bg": "black" if self.path == "/now-debug" else "transparent",
                "now_artist_size": NOW_ARTIST_SIZE,
                "now_title_size": NOW_TITLE_SIZE,
                "now_year_size": NOW_YEAR_SIZE,
                "now_left_pad": NOW_LEFT_PAD,
                "now_bottom_pad": NOW_BOTTOM_PAD,
                "now_stale_minutes": NOW_STALE_MINUTES,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.write(page)
            return
        elif self.path == "/":
            page = (HTML % {"poll_ms": POLL_INTERVAL * 1000}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.write(page)
        else:
            self.send_error(404, f"Unknown endpoint: {self.path}")

    def write(self, data):
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass  # quiet


def kill_existing_server():
    """Kill any existing process on our port."""
    result = subprocess.run(
        ["lsof", "-ti", f":{PORT}"], capture_output=True, text=True
    )
    for pid in result.stdout.split():
        print(f"Stopping previous server (PID {pid})...")
        os.kill(int(pid), signal.SIGTERM)
    if result.stdout.strip():
        time.sleep(1)


if __name__ == "__main__":
    kill_existing_server()
    server = HTTPServer(("", PORT), Handler)
    base = f"http://localhost:{PORT}"
    print(f"Serving Rekordbox history at {base}")
    print(f"Polling every {POLL_INTERVAL}s. Ctrl+C to stop.")
    print()
    endpoints = [
        ("/",            "History page"),
        ("/now",         "Now-playing overlay (transparent bg)"),
        ("/now-debug",   "Now-playing overlay (black bg)"),
        ("/api/history", "JSON API"),
    ]
    print("Endpoints:")
    for path, desc in endpoints:
        url = f"{base}{path}"
        print(f"  {url:<40} {desc}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
