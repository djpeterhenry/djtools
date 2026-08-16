#!/usr/bin/env python3.11
"""Web UI backend for browsing / searching / tagging the song database.

Thin FastAPI wrapper over ableton_aid: all the hard logic (camelot keys, tag
add/remove, play-count aggregation) lives in ableton_aid.py -- this only serves
JSON and persists edits.

Run from the songs directory (where database.json lives), or point at it:

    python3.11 song_server.py --dir "/Users/peter/Music/Ableton/djpeterhenry/Songs"

Then open http://localhost:8765
"""

import argparse
import io
import json
import os
import subprocess
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import ableton_aid as aa
from server_util import kill_existing_server
from tag import Tag, HIDDEN_TAG_VALUES


HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "song_web")

# Rotate a fresh numbered backup at most this often, so a session of many small
# edits doesn't churn the whole 50-deep backup history away. The current file
# is still written atomically on every single edit.
BACKUP_MIN_INTERVAL_SEC = 5 * 60

RELEASE_YEAR_KEYS = [
    "release_year_manual",
    "release_year_discogs",
    "release_year_beatport",
    "release_year_bandcamp",
    "release_year_soundcloud",
    "release_year_youtube",
]


class State:
    db_dict = {}
    order = []  # filenames, in a stable base order (alpha)
    last_backup = 0.0


state = State()


def best_year(record):
    for k in RELEASE_YEAR_KEYS:
        v = record.get(k)
        if v:
            return v
    return None


def song_view(filename):
    """Build the JSON view of one song from its db record."""
    record = state.db_dict[filename]
    key = record.get("key", "") or ""
    camelot = aa.get_camelot_key(key)
    cam_num = int(camelot[:-1]) if camelot else None
    # Name and extension stay separate: the UI shows the extension only on the
    # few names that two files share.
    stem, ext = os.path.splitext(filename)
    return {
        "id": filename,
        "name": stem,
        "ext": ext[1:].upper(),
        "bpm": record.get("bpm", 0),
        "key": key,
        "camelot": camelot or "",
        "camelot_num": cam_num,
        "plays": aa.get_ts_date_count(record),
        "tags": list(record.get("tags", [])),
        "year": best_year(record),
        "vocal": aa.is_vocal(record),
        "good": aa.has_tag(record, Tag.GOOD_TAG.value),
        # sort keys
        "recency": aa.get_alc_or_last_ts(record),
        "sample_ts": (record.get("clip") or {}).get("sample_ts", 0),
        "has_sample": bool(record.get(aa.REKORDBOX_LOCAL_SAMPLE_KEY)),
    }


def known_tags():
    """Tags offered in the ui: defined in code, plus any others found in the
    db, sorted -- minus the hidden ones."""
    result = [t for t in Tag.list() if t not in HIDDEN_TAG_VALUES]
    extra = set()
    for record in state.db_dict.values():
        for t in record.get("tags", []):
            if t not in result and t not in HIDDEN_TAG_VALUES:
                extra.add(t)
    result.extend(sorted(extra))
    return result


def save_db():
    """Atomically write database.json; rotate a backup at most every few min."""
    now = time.time()
    if (
        now - state.last_backup > BACKUP_MIN_INTERVAL_SEC
        and os.path.exists(aa.DATABASE_JSON)
    ):
        aa.rotate_file(aa.DATABASE_JSON)  # moves current -> .1 (current now gone)
        state.last_backup = now
    tmp = aa.DATABASE_JSON + ".tmp"
    data = json.dumps(state.db_dict, ensure_ascii=False)
    with io.open(tmp, "w", encoding="utf8") as f:
        f.write(data)
    os.replace(tmp, aa.DATABASE_JSON)


app = FastAPI()


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/api/data")
def get_data():
    return {
        "songs": [song_view(f) for f in state.order],
        "known_tags": known_tags(),
        "camelot_dict": aa.camelot_dict,
    }


class TagEdit(BaseModel):
    id: str
    tag: str
    action: str  # "add" | "remove"


@app.post("/api/tag")
def edit_tag(edit: TagEdit):
    if edit.id not in state.db_dict:
        raise HTTPException(status_code=404, detail="unknown song")
    tag = edit.tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="empty tag")
    record = state.db_dict[edit.id]
    if edit.action == "add":
        aa.add_tag(record, tag)
    elif edit.action == "remove":
        aa.remove_tag(record, tag)
    else:
        raise HTTPException(status_code=400, detail="bad action")
    save_db()
    return song_view(edit.id)


class SongRef(BaseModel):
    id: str


@app.post("/api/reveal")
def reveal(ref: SongRef):
    record = state.db_dict.get(ref.id)
    if record is None:
        raise HTTPException(status_code=404, detail="unknown song")
    sample = aa.get_existing_rekordbox_sample(
        record, sample_key=aa.REKORDBOX_LOCAL_SAMPLE_KEY
    )
    if not sample:
        raise HTTPException(status_code=404, detail="no sample on disk")
    aa.reveal_file(sample)
    return {"ok": True}


@app.post("/api/copy")
def copy_ableton(ref: SongRef):
    """Copy the .alc file to the clipboard as a file (for pasting into Ableton)."""
    if ref.id not in state.db_dict:
        raise HTTPException(status_code=404, detail="unknown song")
    path = os.path.abspath(ref.id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="alc not on disk")
    cmd = 'osascript -e "set the clipboard to POSIX file \\"%s\\""' % path
    subprocess.call(cmd, shell=True)
    return {"ok": True}


@app.post("/api/play")
def play(ref: SongRef):
    record = state.db_dict.get(ref.id)
    if record is None:
        raise HTTPException(status_code=404, detail="unknown song")
    sample = aa.get_sample(record)
    if not sample or not os.path.exists(sample):
        raise HTTPException(status_code=404, detail="no sample on disk")
    subprocess.call(["open", sample])
    return {"ok": True}


def load(directory):
    if directory:
        os.chdir(directory)
    if not os.path.exists(aa.DATABASE_JSON):
        raise SystemExit(
            "No %s in %s -- run from the songs dir or pass --dir"
            % (aa.DATABASE_JSON, os.getcwd())
        )
    state.db_dict = aa.read_db_file()
    valid = aa.get_valid_alc_files(state.db_dict)
    state.order = valid
    print("Loaded %d songs (%d valid alc) from %s" % (
        len(state.db_dict), len(valid), os.getcwd()))


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dir", help="songs directory containing database.json")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    return p.parse_args()


def main():
    args = parse_args()
    kill_existing_server(args.port)
    load(args.dir)
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    import uvicorn

    print("Open http://localhost:%d" % args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
