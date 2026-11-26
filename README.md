# djtools
Tools for a DJ library kept in Ableton Live and played from rekordbox. Each song is
an Ableton clip (`.alc`; `.als` sets work too) with its warping and loop set up; a
`database.json` next to the clips holds each song's bpm, key, tags and play
history; and the export turns it all into a rekordbox library: the samples, beat
grids from the warp markers, and playlists by tag, bpm, key, play count and age.

This is the maintainer's own toolkit, shared as is: it fits one way of working
rather than offering options for every other. Run everything from the songs folder
(where `database.json` lives) with `python3.11`.

| Script | What it does |
| --- | --- |
| `actions.py` | CLI for database chores: `add-bpms`, `add-keys`, `rekordbox-xml`, release-date lookup, tag edits, … (`actions.py --help`) |
| `ableton_gui.py` | Tk browser: filter by bpm/key/tag/list, copy a clip to paste into Ableton |
| `song_server.py` | Web version of the browser (`--dir <songs folder>`, then http://localhost:8765) |
| `history_server.py` | Live rekordbox history + now-playing overlay at http://localhost:8888 (also launched by `History Server.app`) |
| `lyrics.py` | Word-timed lyrics for [reforce](https://github.com/djpeterhenry/reforce)'s karaoke: `add` (LRCLIB text, Demucs vocals, Whisper, forced alignment), `realign`, `check`, `index`; sidecars in `LocalSamples/Lyrics/` |
| `lyrics_server.py` | Review and correct those lyrics at http://localhost:8766 (waveform, drag words, tap timing, re-align a line), and add new ones |
| `silence.py` | Copy a song with silence prepended, for beat grids that start before 0 |
| `convert_to_aiff.py`, `demucs.py` | ffmpeg / demucs wrappers |

Shared logic lives in `ableton_aid.py` (database, Ableton XML, camelot keys,
ordering) and `export_rekordbox.py` (sample export and the rekordbox XML).

## Setup

You need macOS, Python 3.11, Ableton Live and rekordbox 6 or 7 (the export reads
rekordbox's play history). Then:

```sh
python3.11 -m pip install -r requirements.txt -r requirements-dev.txt
```

Release-date lookup needs a [discogs token](https://www.discogs.com/settings/developers)
in `$DISCOGS_TOKEN` or `~/.config/djtools/discogs_token`.

External programs used by some commands: `ffmpeg`/`ffprobe` (sample export,
`silence.py`, the lyrics tools), [`keyfinder-cli`](https://github.com/EvanPurkhiser/keyfinder-cli)
(`add-keys`) and `demucs`. The tools are written for macOS (`open`, `osascript`,
`lsof`, rekordbox's database location).

## Getting started

The library is an Ableton project with the clips in one folder, each named
`Artist - Title.alc`:

```
MyProject/
  Songs/             the clips, and database.json (run the tools here)
  Samples/Imported/  the audio the clips play
```

```sh
cd MyProject/Songs
echo '{}' > database.json                         # a new, empty library
python3.11 ~/djtools/actions.py add-bpms           # asks each new clip's bpm (empty line: stop and save)
python3.11 ~/djtools/actions.py add-keys           # keys by keyfinder-cli
python3.11 ~/djtools/actions.py rekordbox-xml ~/rekordbox.xml
```

`rekordbox-xml` links or copies each song's sample into the sample folder
(below), converting what DJ hardware can't play, and writes the XML; in rekordbox,
choose it under Preferences > Advanced > Database > rekordbox xml, then import
from the "rekordbox xml" section of the browser. Its playlists sit in a folder
named for `VERSION` in `export_rekordbox.py` (`V02`); bump that to start a fresh
folder when the playlist layout changes.

## Configuration

Folders outside the songs folder are set in `~/.config/djtools/config.toml`
(or the file named by `$DJTOOLS_CONFIG`); each can also be set by an environment
variable `DJTOOLS_<NAME>`, which wins over the file:

```toml
lists_folder = "~/my-site/lists"             # song lists, exported as playlists
collection_folder = "~/my-site/collection"   # where generate_lists writes (and git pushes)
rekordbox_local_sample_path = "~/Music/PioneerDJ/LocalSamples"
rekordbox_tags_path = "~/Documents/rekordbox_tags"
hidden_tags = ["-ab", "(venue)"]   # tags the browsers leave out of their tag menus

[tags]   # the known tags, each with its properties, in order
DISCO = ["genre", "mark", "playlist"]
TECH_HOUSE = ["genre", "mark", "playlist"]
GOOD = ["mark", "playlist"]
DAY_VENUE = ["mark", "playlist"]
DRUM_LOOPS = ["playlist"]
vocal = ["mark"]
x = ["hidden"]
```

All are optional: `lists_folder` and `collection_folder` are off until set,
`hidden_tags` is empty, and the rest default to the values shown.

Each known tag has any of these properties:

| Property | What it does |
| --- | --- |
| `genre` | the song's genre: the Tk genre column, the "needs genre" filters, the genre color on the web |
| `mark` | marked in the rekordbox file name, e.g. `Song [#disco]` |
| `playlist` | exported as a rekordbox playlist |
| `hidden` | left out of the web browser's tag menus |

The table's order is the order of the marks, the playlists and the tag menus.
Without a `[tags]` table, common genres and the built-in tags are used (`DEFAULT_TAGS`
in `tag.py`); with one, it is the whole list. Tags the code acts on (`GOOD`,
`vocal`, `x`, `SS`, ...) do that either way. See `config.py` and `tag.py` for details.

`history_server.py` listens on all network interfaces, so its message and
suppress pages work from a phone on the same network. Anyone on that network can
reach them too.

## Checks

```sh
python3.11 -m pytest     # tests (never touch the real library or your config)
python3.11 -m pyright --pythonpath "$(command -v python3.11)"   # types
python3.11 -m ruff check .                                       # lint
```

The database record shape is described in `db_types.py`.

`tests/golden/rekordbox.xml` is a snapshot of a full export; after an
intended change to the export, regenerate it with
`UPDATE_GOLDEN=1 python3.11 -m pytest -k golden` and review the diff.

## Publishing (maintainer notes)

Development happens in a private repo; the public one gets a squashed commit per
release from `scripts/publish.py`, which checks for secrets, home paths and
personal strings first (`scripts/publish.py --dry-run` to see what would go out).
Pull requests merged on the public repo come back with `scripts/publish.py --bring-in`.

## Lyrics

`lyrics.py` and `lyrics_server.py` need an Apple Silicon Mac (Whisper runs on MLX) and the machine-learning
extras, installed on demand (`python3.11 -m pip install mlx-whisper torch torchaudio demucs`); the first run downloads the Whisper (~1.6 GB) and
alignment (~1.2 GB) models. Vocal stems and transcripts are cached in `~/Library/Caches/djtools/lyrics/`.
The sidecars are timed in the exported sample rekordbox plays, on rekordbox's timeline: an MP3 with a LAME gapless header is decoded with the 51 ms ffmpeg would trim put back (rekordbox and Ableton play it); after a re-export that changes a sample
(`lyrics.py check` says "stale"), `lyrics.py realign` times the reviewed text again.
The review page shows where each song's text came from: the LRCLIB match (flagged when it is another version of
the song, such as a different remix), Whisper's own hearing when nothing was found (red; check every word), or text
typed in the page.

Saving in the page marks the lines you changed ("✎ edited"; the song list counts them): an edit is not acceptance, so
rebuilds keep those lines (and do not bring back lines you deleted) but still redo the rest of the song:
`lyrics.py add --force` does that, and `realign` keeps the marks. "Mark reviewed" freezes a song (`add --force`
leaves it alone). The page's "Redo song" is the way to start a song over: it replaces everything, edits included.

## License

djtools is licensed under the [GNU General Public License v3.0](LICENSE) or (at your option) any later version.
