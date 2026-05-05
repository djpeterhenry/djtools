#!/usr/bin/env python3.11
"""Serves the most recent Rekordbox history as a live-updating web page."""

import json
import logging
import os
import re
import signal
import subprocess
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrekordbox import Rekordbox6Database

# We know Rekordbox is running; we only read, never commit, so this is safe.
logging.getLogger("pyrekordbox.db6.database").setLevel(logging.ERROR)

PORT = 8888
POLL_INTERVAL = 1  # seconds
TAG_SEPARATOR = "   "  # triple-space delimiter before tag suffixes like [Techno]

# Now Playing page settings
NOW_WIDTH = 1920
NOW_HEIGHT = 1080
NOW_FONT_SIZE = "48px"
NOW_ARTIST_SIZE = "1.2em"
NOW_TITLE_SIZE = "1.1em"
NOW_YEAR_SIZE = "0.9em"
NOW_LEFT_PAD = 20
NOW_BOTTOM_PAD = 20
NOW_VOCAL_GAP = 48  # px between vocal and main track
NOW_STALE_MINUTES = 10  # show "Waiting for update" if last track is older than this

# Message overlay settings
MSG_FONT_MAX = 100       # px, font size for short messages
MSG_FONT_MIN = 36        # px, minimum font size
MSG_SCALE_CHARS = 20     # messages longer than this shrink the font
MSG_DISPLAY_SECONDS = 30 # seconds to show message before fade-out begins
MSG_FADE_SECONDS = 2     # fade-out duration in seconds
MSG_VERTICAL_PCT = 35    # % from top of screen (35 = just above centre)
MSG_COLOR = "white"
MSG_MAX_WIDTH_PCT = 85   # max width as % of screen width


_message_state = {"text": "", "set_at": None}


def process_title(raw_title):
    """Strip tag suffixes and extract vocal info from a raw title."""
    is_vocal = "[#vocal]" in raw_title
    title = raw_title
    if TAG_SEPARATOR in title:
        title = title[: title.index(TAG_SEPARATOR)].strip()
    # Remove parenthesised blocks starting with "original" or "extended"
    title = re.sub(r"\s*\((?:original|extended)\b[^)]*\)", "", title, flags=re.IGNORECASE).strip()
    # Remove trailing "fixed" or trailing number (e.g. "2", "03")
    title = re.sub(r"\s+(?:fixed|\d+)$", "", title, flags=re.IGNORECASE).strip()
    vocal_title = (title.split("(")[0].strip() or title) + " (Vocal)" if is_vocal else ""
    return title, is_vocal, vocal_title


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
        title, is_vocal, vocal_title = process_title(c.Title)
        artist = c.Artist.Name if c.Artist else ""
        result["songs"].append(
            {
                "track_no": s.TrackNo,
                "title": title,
                "artist": artist,
                "played_at": str(s.created_at),
                "year": c.ReleaseYear,
                "is_vocal": is_vocal,
                "vocal_title": vocal_title,
            }
        )
    db.close()
    return result


def get_test_history_songs():
    now = datetime.now()
    raw_songs = [
        {
            "track_no": 1,
            "raw_title": "Dreaming Of Better Days   [#deep] [#actual_house]",
            "artist": "Deep House Collective",
            "played_at": str(now - timedelta(seconds=30)),
            "year": 2023,
        },
        {
            "track_no": 2,
            "raw_title": "Midnight Runner (Extended Mix)   [#tech_house]",
            "artist": "Groove Assembly",
            "played_at": str(now - timedelta(seconds=20)),
            "year": 2024,
        },
        {
            "track_no": 3,
            "raw_title": "Say My Name (Original Mix)   [#actual_house] [#vocal]",
            "artist": "Luna Vox",
            "played_at": str(now - timedelta(seconds=10)),
            "year": 2022,
        },
        {
            "track_no": 4,
            "raw_title": "Neon Lights (DJ Tool Mix)   [#progressive]",
            "artist": "Pulse Unit",
            "played_at": str(now - timedelta(seconds=8)),
            "year": 2024,
        },
        {
            "track_no": 5,
            "raw_title": "Sunset (The Original)   [#afro]",
            "artist": "Sol Rivera",
            "played_at": str(now - timedelta(seconds=7)),
            "year": 2021,
        },
        {
            "track_no": 6,
            "raw_title": "Lost Signal fixed   [#acid]",
            "artist": "Static Echo",
            "played_at": str(now - timedelta(seconds=6)),
            "year": 2023,
        },
        {
            "track_no": 7,
            "raw_title": "Warehouse Dub 2   [#disco]",
            "artist": "Depth Charge",
            "played_at": str(now - timedelta(seconds=4)),
            "year": 2025,
        },
    ]
    songs = []
    for s in raw_songs:
        title, is_vocal, vocal_title = process_title(s["raw_title"])
        songs.append(
            {
                "track_no": s["track_no"],
                "title": title,
                "artist": s["artist"],
                "played_at": s["played_at"],
                "year": s["year"],
                "is_vocal": is_vocal,
                "vocal_title": vocal_title,
            }
        )
    return {
        "name": "Test Session",
        "songs": songs,
    }


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
  #vocal { margin-left: 40px; margin-bottom: %(now_vocal_gap)dpx; display: none; }
  #vocal p { margin: 2px 0; }
  #vocal-artist { font-size: %(now_artist_size)s; font-weight: bold; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #vocal-title { font-size: %(now_title_size)s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #message {
    position: absolute;
    top: %(msg_vertical_pct)d%%;
    left: 50%%;
    transform: translateX(-50%%);
    max-width: %(msg_max_width_pct)d%%;
    text-align: center;
    color: %(msg_color)s;
    font-weight: bold;
    opacity: 0;
    pointer-events: none;
    line-height: 1.2;
  }
  .fade { animation: fadein 0.5s ease-in; }
  @keyframes fadein { from { opacity: 0; } to { opacity: 1; } }
</style>
</head>
<body>
<div id="message"></div>
<div id="now">
  <div id="vocal">
    <p id="vocal-artist"></p>
    <p id="vocal-title"></p>
  </div>
  <p id="artist"></p>
  <p id="title"></p>
  <p id="year"></p>
</div>
<script>
let lastTitle = "";
let lastVocalTitle = "";
const STALE_MS = %(now_stale_minutes)d * 60 * 1000;
async function poll() {
  try {
    const resp = await fetch("%(api_url)s");
    const data = await resp.json();
    if (!data.songs || !data.songs.length) return;
    const nonVocals = data.songs.filter(s => !s.is_vocal);
    if (!nonVocals.length) return;
    const s = nonVocals[nonVocals.length - 1];
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
    // Show vocal info if the most recent song overall is a vocal
    const latest = data.songs[data.songs.length - 1];
    const vocalEl = document.getElementById("vocal");
    if (latest.is_vocal && !stale) {
      document.getElementById("vocal-artist").textContent = latest.artist;
      document.getElementById("vocal-title").textContent = latest.vocal_title;
      if (latest.title !== lastVocalTitle) {
        vocalEl.style.display = "block";
        vocalEl.classList.remove("fade");
        void vocalEl.offsetWidth;
        vocalEl.classList.add("fade");
        lastVocalTitle = latest.title;
      }
    } else {
      vocalEl.style.display = "none";
      lastVocalTitle = "";
    }
  } catch (e) {
    console.error(e);
  }
}

const MSG_FONT_MAX = %(msg_font_max)d;
const MSG_FONT_MIN = %(msg_font_min)d;
const MSG_SCALE_CHARS = %(msg_scale_chars)d;
const MSG_DISPLAY_SECONDS = %(msg_display_seconds)d;
const MSG_FADE_SECONDS = %(msg_fade_seconds)d;
let lastMsgSetAt = null;
let msgFadeTimer = null;

async function pollMessage() {
  try {
    const resp = await fetch("/api/message");
    const data = await resp.json();
    if (data.set_at !== lastMsgSetAt) {
      lastMsgSetAt = data.set_at;
      if (!data.text) {
        showMessage("");
      } else {
        const age = Date.now() - new Date(data.set_at).getTime();
        const remaining = MSG_DISPLAY_SECONDS * 1000 - age;
        if (remaining > 0) showMessage(data.text, remaining);
      }
    }
  } catch(e) {}
}

function showMessage(text, displayMs) {
  if (msgFadeTimer) { clearTimeout(msgFadeTimer); msgFadeTimer = null; }
  const el = document.getElementById("message");
  if (!text) { el.style.opacity = "0"; return; }
  if (displayMs === undefined) displayMs = MSG_DISPLAY_SECONDS * 1000;
  const size = Math.max(MSG_FONT_MIN, Math.round(MSG_FONT_MAX * Math.sqrt(MSG_SCALE_CHARS / Math.max(text.length, MSG_SCALE_CHARS))));
  el.style.fontSize = size + "px";
  el.textContent = text;
  el.style.transition = "opacity 0.3s ease-in";
  el.style.opacity = "1";
  msgFadeTimer = setTimeout(() => {
    el.style.transition = "opacity " + MSG_FADE_SECONDS + "s ease-out";
    el.style.opacity = "0";
  }, displayMs);
}

poll();
setInterval(poll, %(poll_ms)d);
pollMessage();
setInterval(pollMessage, %(poll_ms)d);
</script>
</body>
</html>
"""

MESSAGE_INPUT_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Send Message</title>
<style>
  body {
    background: #1a1a2e; color: #eee; font-family: -apple-system, sans-serif;
    margin: 0; padding: 20px; max-width: 480px;
  }
  h1 { color: #e94560; font-size: 1.2em; margin-bottom: 16px; }
  input[type=text] {
    width: 100%; box-sizing: border-box;
    background: #2a2a3e; color: #eee; border: 1px solid #444;
    padding: 12px; font-size: 1.1em; border-radius: 4px; margin-bottom: 10px;
  }
  .buttons { display: flex; gap: 10px; }
  button {
    flex: 1; padding: 12px; font-size: 1em; border: none;
    border-radius: 4px; cursor: pointer; font-weight: bold;
  }
  #send-btn { background: #e94560; color: white; }
  #clear-btn { background: #444; color: #eee; }
  #status { margin-top: 12px; font-size: 0.85em; color: #888; min-height: 1.2em; }
</style>
</head>
<body>
<h1>Overlay message</h1>
<input type="text" id="msg" placeholder="Type message..." autofocus>
<div class="buttons">
  <button id="send-btn" onclick="send()">Send</button>
  <button id="clear-btn" onclick="clearMsg()">Clear</button>
</div>
<p id="status"></p>
<script>
document.getElementById("msg").addEventListener("keydown", e => {
  if (e.key === "Enter") send();
});
async function send() {
  const text = document.getElementById("msg").value.trim();
  if (!text) return;
  await post(text);
  document.getElementById("msg").value = "";
  setStatus("Sent: " + text);
}
async function clearMsg() {
  await post("");
  setStatus("Cleared.");
}
async function post(text) {
  await fetch("/api/message", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({text}),
  });
}
function setStatus(msg) {
  const el = document.getElementById("status");
  el.textContent = msg;
  setTimeout(() => { el.textContent = ""; }, 3000);
}
</script>
</body>
</html>
"""


def render_now_playing(now_bg, api_url):
    return (NOW_PLAYING_HTML % {
        "poll_ms": POLL_INTERVAL * 1000,
        "now_width": NOW_WIDTH,
        "now_height": NOW_HEIGHT,
        "now_font_size": NOW_FONT_SIZE,
        "now_bg": now_bg,
        "now_artist_size": NOW_ARTIST_SIZE,
        "now_title_size": NOW_TITLE_SIZE,
        "now_year_size": NOW_YEAR_SIZE,
        "now_left_pad": NOW_LEFT_PAD,
        "now_bottom_pad": NOW_BOTTOM_PAD,
        "now_vocal_gap": NOW_VOCAL_GAP,
        "now_stale_minutes": NOW_STALE_MINUTES,
        "api_url": api_url,
        "msg_font_max": MSG_FONT_MAX,
        "msg_font_min": MSG_FONT_MIN,
        "msg_scale_chars": MSG_SCALE_CHARS,
        "msg_display_seconds": MSG_DISPLAY_SECONDS,
        "msg_fade_seconds": MSG_FADE_SECONDS,
        "msg_vertical_pct": MSG_VERTICAL_PCT,
        "msg_color": MSG_COLOR,
        "msg_max_width_pct": MSG_MAX_WIDTH_PCT,
    }).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/api/history", "/api/history-test"):
            if self.path == "/api/history-test":
                data = get_test_history_songs()
            else:
                data = get_latest_history_songs()
            payload = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_no_cache()
            self.end_headers()
            self.write(payload)
        elif self.path == "/api/message":
            payload = json.dumps(_message_state).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_no_cache()
            self.end_headers()
            self.write(payload)
        elif self.path in ("/now", "/now-debug", "/now-debug-test"):
            api_url = "/api/history-test" if self.path == "/now-debug-test" else "/api/history"
            now_bg = "transparent" if self.path == "/now" else "black"
            page = render_now_playing(now_bg, api_url)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_no_cache()
            self.end_headers()
            self.write(page)
            return
        elif self.path == "/message-input":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_no_cache()
            self.end_headers()
            self.write(MESSAGE_INPUT_HTML.encode())
        elif self.path == "/":
            page = (HTML % {"poll_ms": POLL_INTERVAL * 1000}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_no_cache()
            self.end_headers()
            self.write(page)
        else:
            self.send_error(404, f"Unknown endpoint: {self.path}")

    def do_POST(self):
        if self.path == "/api/message":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                text = data.get("text", "").strip()
            except (json.JSONDecodeError, AttributeError):
                self.send_error(400, "Invalid JSON")
                return
            _message_state["text"] = text
            _message_state["set_at"] = datetime.now().isoformat() if text else None
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.write(json.dumps({"ok": True}).encode())
        else:
            self.send_error(404, f"Unknown endpoint: {self.path}")

    def send_no_cache(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")

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
        ("/",                 "History page"),
        ("/message-input",    "Send overlay message"),
        ("/now",              "Now-playing overlay (transparent bg)"),
        ("/now-debug",        "Now-playing overlay (black bg)"),
        ("/now-debug-test",   "Now-playing overlay (black bg, test data)"),
        ("/api/history",      "JSON API"),
        ("/api/history-test", "JSON API (test data)"),
        ("/api/message",      "Message API (GET/POST)"),
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
