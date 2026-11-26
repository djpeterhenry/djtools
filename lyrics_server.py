#!/usr/bin/env python3.11
"""Review and correct the word-timed lyrics reforce shows (lyrics.py), and add new ones.

    python3.11 lyrics_server.py --dir ~/Music/Ableton/MyProject/Songs

Then open http://localhost:8766

Every edit is saved straight to the song's sidecar (and index.json), so a
running reforce shows it on its next look (about a second).  Re-timing a line
(new text, or "re-align") loads the forced aligner for that song once (a few
seconds), then takes well under a second per line.
"""

import argparse
import os
import subprocess
import threading
import time
import traceback
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import ableton_aid as aa
import lyrics
from server_util import kill_existing_server

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "lyrics_web")
PEAKS_PER_SECOND = 100

app = FastAPI()


class State:
    db_dict: dict[str, Any] = {}
    lock = threading.Lock()          # one machine learning job at a time (memory)
    aligner_key: tuple[str, float] | None = None
    aligner: Any = None
    peaks: dict[tuple[str, float], list[int]] = {}
    jobs: dict[str, dict[str, Any]] = {}


state = State()


def sidecar_file(name: str) -> str:
    """The sidecar for a file name from the list (no paths)."""
    if os.path.basename(name) != name or not name.endswith(lyrics.SUFFIX):
        raise HTTPException(status_code=400, detail="bad sidecar name")
    path = os.path.join(lyrics.lyrics_dir(), name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="no such lyrics")
    return path


def vocals_cached(sample: str) -> str | None:
    import lyrics_align as la

    p = os.path.join(la.cache_dir(sample), "vocals-timeline.wav")
    return p if os.path.isfile(p) else None


def playable(path: str) -> str:
    """A file the browser plays: Chrome has no AIFF, so an AIFF is converted once to FLAC (lossless, same samples
    and start, so the same timeline), cached beside the song's other derived files."""
    if os.path.splitext(path)[1].lower() not in (".aif", ".aiff", ".aifc"):
        return path
    import lyrics_align as la

    out = os.path.join(la.cache_dir(path), "play.flac")
    if not os.path.isfile(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + ".part.flac"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-map", "0:a:0", "-c:a", "flac", tmp], check=True)
        os.replace(tmp, out)
    return out


def audio_for(s: lyrics.Sidecar, vocals: bool) -> str:
    sample = s.get("sample", "")
    if not os.path.isfile(sample):
        raise HTTPException(status_code=404, detail="the sample is gone: " + sample)
    if vocals:
        v = vocals_cached(sample)
        if v:
            return v
    import lyrics_align as la

    return la.timeline_path(sample)   # what the lyrics are timed in (rekordbox's timeline)


def align_audio(s: lyrics.Sidecar) -> str:
    """What the song was aligned on: its vocal stem when it was separated."""
    sample = s["sample"]
    if s.get("source", {}).get("separated"):
        v = vocals_cached(sample)
        if v:
            return v
        import lyrics_align as la

        return la.vocals_path(sample)
    import lyrics_align as la

    return la.timeline_path(sample)


def get_aligner(audio: str) -> Any:
    key = (audio, os.path.getmtime(audio))
    if state.aligner_key != key:
        import lyrics_align as la

        state.aligner = la.Aligner(audio)
        state.aligner_key = key
    return state.aligner


def summary(path: str) -> dict[str, Any]:
    s = lyrics.read_sidecar(path)
    return {
        "file": os.path.basename(path),
        "song": s.get("song", ""),
        "artist": s.get("artist", ""),
        "title": s.get("title", ""),
        "reviewed": bool(s.get("reviewed")),
        "lines": len(s.get("lines", [])),
        "edited": sum(1 for l in s.get("lines", []) if l.get("edited")),
        "status": lyrics.sidecar_status(s),
        "modified": s.get("modified", 0),
        "source": lyrics.describe_source(s),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(WEB_DIR, "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/api/songs")
def songs() -> list[dict[str, Any]]:
    return [summary(p) for p in lyrics.list_sidecars()]


@app.get("/api/lyrics/{name}")
def get_lyrics(name: str) -> dict[str, Any]:
    s = lyrics.read_sidecar(sidecar_file(name))
    s["status"] = lyrics.sidecar_status(s)
    s["source_info"] = lyrics.describe_source(s)
    s["has_vocals"] = bool(os.path.isfile(s.get("sample", "")) and vocals_cached(s["sample"]))
    return s


class Edit(BaseModel):
    lines: list[dict[str, Any]]
    offset: float = 0.0
    reviewed: bool = False
    reference: str | None = None
    base_modified: float | None = None   # the version the edit started from (lost-update check)


def clean_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for l in lines:
        words = []
        for w in l.get("words", []):
            t0, t1 = float(w["t0"]), float(w["t1"])
            text = str(w["text"]).strip()
            if not text:
                continue
            words.append({"t0": round(t0, 3), "t1": round(max(t1, t0 + 0.01), 3), "text": text,
                          "score": float(w.get("score", 0.0))})
        if not words:
            continue
        words.sort(key=lambda w: w["t0"])
        line = {"t0": words[0]["t0"], "t1": words[-1]["t1"], "text": " ".join(w["text"] for w in words), "words": words}
        if l.get("note"):
            line["note"] = str(l["note"])
        out.append(line)
    out.sort(key=lambda l: l["t0"])
    return out


@app.put("/api/lyrics/{name}")
def put_lyrics(name: str, edit: Edit) -> dict[str, Any]:
    path = sidecar_file(name)
    s = lyrics.read_sidecar(path)
    if edit.base_modified is not None and abs(s.get("modified", 0) - edit.base_modified) > 1e-3:
        raise HTTPException(status_code=409, detail="changed elsewhere since you opened it; reload")
    lines = clean_lines(edit.lines)
    removed = s.get("removed", [])
    lyrics.mark_hand_edits(s.get("lines", []), lines, removed)   # per line: an edit is not acceptance
    s["lines"] = lines
    if removed:
        s["removed"] = removed
    s["offset"] = round(float(edit.offset), 3)
    s["reviewed"] = bool(edit.reviewed)
    s.pop("edited", None)
    if edit.reference is not None:
        if edit.reference != s.get("reference"):
            s["source"] = dict(s.get("source", {}), lyrics="manual")   # the text is now the reviewer's
        s["reference"] = edit.reference
    lyrics.save_sidecar(s, path)
    return {"modified": s["modified"], "lines": s["lines"], "source_info": lyrics.describe_source(s)}


@app.delete("/api/lyrics/{name}")
def delete_lyrics(name: str) -> dict[str, Any]:
    path = sidecar_file(name)
    os.remove(path)
    lyrics.write_index()
    return {"ok": True}


@app.get("/api/audio/{name}")
def audio(name: str, vocals: int = 0, play: int = 0) -> FileResponse:
    s = lyrics.read_sidecar(sidecar_file(name))
    # no-cache: browsers kept the AIFF this used to send (Chrome cannot play it) across restarts
    return FileResponse(playable(audio_for(s, bool(vocals))), headers={"Cache-Control": "no-cache"})


@app.get("/api/peaks/{name}")
def peaks(name: str, vocals: int = 0) -> dict[str, Any]:
    """The waveform: max |sample| per 1/100 s, 0..255."""
    s = lyrics.read_sidecar(sidecar_file(name))
    path = audio_for(s, bool(vocals))
    key = (path, os.path.getmtime(path))
    if key not in state.peaks:
        sr = 8000
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                             capture_output=True, check=True).stdout
        x = np.abs(np.frombuffer(raw, dtype=np.float32))
        hop = sr // PEAKS_PER_SECOND
        n = len(x) // hop
        p = x[:n * hop].reshape(n, hop).max(axis=1) if n else np.zeros(0)
        top = float(np.percentile(p, 99.5)) if n else 1.0
        state.peaks[key] = [int(v) for v in np.clip(p / max(top, 1e-6) * 255, 0, 255)]
    return {"rate": PEAKS_PER_SECOND, "peaks": state.peaks[key]}


class Realign(BaseModel):
    text: str
    a: float
    b: float


@app.post("/api/realign/{name}")
def realign(name: str, req: Realign) -> dict[str, Any]:
    """One line's words timed inside [a, b] (sample seconds, before the offset)."""
    s = lyrics.read_sidecar(sidecar_file(name))
    if not lyrics.norm_words(req.text):
        raise HTTPException(status_code=400, detail="no words")
    with state.lock:
        aligner = get_aligner(align_audio(s))
        line = lyrics.realign_line(aligner, {}, req.text, max(0.0, req.a), min(aligner.duration, req.b))
    return line


# ---------------------------------------------------------------- adding songs

@app.get("/api/search")
def search(q: str) -> list[dict[str, Any]]:
    if len(q.strip()) < 2:
        return []
    have = {lyrics.read_sidecar(p).get("song") for p in lyrics.list_sidecars()}
    out = []
    for f in lyrics.find_songs(state.db_dict, q)[:40]:
        rec = state.db_dict[f]
        out.append({"song": f, "has_lyrics": f in have, "has_sample": bool(aa.get_existing_rekordbox_sample(rec)),
                    "vocal_only": lyrics.is_vocal_only(f, rec.get("tags", [])), "tags": rec.get("tags", [])})
    return out


@app.get("/api/lrclib")
def lrclib(song: str) -> dict[str, Any]:
    artist, title = lyrics.search_terms(song)
    results = lyrics.lrclib_search(artist, title)
    return {"artist": artist, "title": title, "results": [{
        "id": r["id"], "artist": r.get("artistName", ""), "track": r.get("trackName", ""),
        "album": r.get("albumName", ""), "duration": r.get("duration", 0), "synced": bool(r.get("syncedLyrics")),
        "text": lyrics.lyrics_text(r)} for r in results[:12]]}


class Add(BaseModel):
    song: str
    reference: str | None = None    # None: Whisper's own text
    source: str = "manual"          # "lrclib:<id>" | "file" | "manual" | "none"
    separate: bool | None = None    # None: by name (acapellas are not separated)
    replace: bool = False


def run_job(job_id: str, req: Add) -> None:
    job = state.jobs[job_id]

    def log(m: str) -> None:
        job["log"].append(m)

    try:
        with state.lock:
            sample = aa.get_existing_rekordbox_sample(state.db_dict[req.song])
            if sample is None:
                raise RuntimeError("no exported sample (export to rekordbox first)")
            source: dict[str, Any] = {"lyrics": req.source}
            if req.source.startswith("lrclib:"):
                try:   # what the picked result was, for the page's source line
                    source = lyrics.lrclib_source(lyrics.lrclib_get(int(req.source.split(":", 1)[1])))
                except (OSError, ValueError) as e:
                    log("LRCLIB details not found: {}".format(e))
            s = lyrics.create(req.song, sample, req.reference, source, separate=req.separate, log=log,
                              tags=state.db_dict[req.song].get("tags", []))
            path = lyrics.save_sidecar(s)
        job["file"] = os.path.basename(path)
        job["state"] = "done"
    except Exception as e:  # shown in the page
        log("".join(traceback.format_exception_only(type(e), e)).strip())
        job["state"] = "failed"


@app.post("/api/add")
def add(req: Add) -> dict[str, Any]:
    if req.song not in state.db_dict:
        raise HTTPException(status_code=404, detail="unknown song")
    if os.path.exists(lyrics.sidecar_path(req.song)) and not req.replace:
        raise HTTPException(status_code=409, detail="already has lyrics")
    job_id = "{:.0f}".format(time.time() * 1000)
    state.jobs[job_id] = {"id": job_id, "song": req.song, "state": "running", "log": [], "file": None}
    threading.Thread(target=run_job, args=(job_id, req), daemon=True).start()
    return state.jobs[job_id]


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict[str, Any]:
    if job_id not in state.jobs:
        raise HTTPException(status_code=404, detail="no such job")
    return state.jobs[job_id]


def load(directory: str | None) -> None:
    if directory:
        os.chdir(directory)
    if not os.path.exists(aa.DATABASE_JSON):
        raise SystemExit("No {} in {} -- run from the songs dir or pass --dir".format(aa.DATABASE_JSON, os.getcwd()))
    state.db_dict = aa.read_db_file()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", help="songs directory containing database.json")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args()
    kill_existing_server(args.port)
    load(args.dir)
    import uvicorn

    print("Open http://localhost:{}".format(args.port))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
