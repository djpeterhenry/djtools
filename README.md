# djtools
Tools for managing my DJ library: an Ableton project of `.alc` clips / `.als`
sets with a `database.json` of bpm, key, tags and play history, exported to
rekordbox.

Run everything from the songs folder (where `database.json` lives) with
`python3.11`.

| Script | What it does |
| --- | --- |
| `actions.py` | CLI for database chores: `add_bpms`, `add_keys`, `rekordbox_xml`, release-date lookup, tag edits, … (`actions.py --help`) |
| `ableton_gui.py` | Tk browser: filter by bpm/key/tag/list, copy a clip to paste into Ableton |
| `song_server.py` | Web version of the browser (`--dir <songs folder>`, then http://localhost:8765) |
| `history_server.py` | Live rekordbox history + now-playing overlay at http://localhost:8888 (also launched by `History Server.app`) |
| `silence.py` | Copy a song with silence prepended, for beat grids that start before 0 |
| `convert_to_aiff.py`, `demucs.py` | ffmpeg / demucs wrappers |

Shared logic lives in `ableton_aid.py` (database, Ableton XML, camelot keys,
ordering) and `export_rekordbox.py` (sample export and the rekordbox XML).

## Setup

```sh
python3.11 -m pip install -r requirements.txt -r requirements-dev.txt
```

Release-date lookup needs a [discogs token](https://www.discogs.com/settings/developers)
in `$DISCOGS_TOKEN` or `~/.config/djtools/discogs_token`.

## Checks

```sh
python3.11 -m pytest     # tests (never touch the real library)
python3.11 -m pyright --pythonpath "$(command -v python3.11)"   # types
```

The database record shape is described in `db_types.py`.

`tests/golden/rekordbox.xml` is a snapshot of a full export; after an
intended change to the export, regenerate it with
`UPDATE_GOLDEN=1 python3.11 -m pytest -k golden` and review the diff.
