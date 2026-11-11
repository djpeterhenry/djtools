# Created on May 14, 2009

import sys
import os
import re
import random
import subprocess
import gzip
import xml.etree.ElementTree as ET
import time
import datetime
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final
import json
from timing import timing
from unidecode import unidecode

from db_types import ClipInfo, DbDict, Record, WarpMarker
from tag import Tag


DATABASE_JSON = "database.json"

DISCOGS_TOKEN_FILE = os.path.expanduser("~/.config/djtools/discogs_token")


def get_discogs_token() -> str:
    """Discogs user token from $DISCOGS_TOKEN, else DISCOGS_TOKEN_FILE."""
    token = os.environ.get("DISCOGS_TOKEN")
    if token:
        return token.strip()
    try:
        with open(DISCOGS_TOKEN_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        sys.exit(
            "No discogs token: set DISCOGS_TOKEN or put it in " + DISCOGS_TOKEN_FILE
        )


ABLETON_EXTENSIONS = [".alc", ".als"]
SAMPLE_EXTENSIONS = [".mp3", ".m4a", ".wav", ".aiff", ".flac"]
ALL_EXTENSIONS = ABLETON_EXTENSIONS + SAMPLE_EXTENSIONS

REKORDBOX_LOCAL_SAMPLE_KEY: Final = "rekordbox_local_sample"

# Record fields worth carrying over when deriving one song's record from another
# (e.g. demucs vocal or silenced copies).
SHARED_RECORD_FIELDS = [
    "bpm",
    "key",
    "release_year_discogs",
    "release_year_manual",
    "labels_discogs",
]


def add_missing_tags(record: Record, tags: Iterable[str]) -> None:
    """Add tags to a record if they are not already present."""
    if "tags" not in record:
        record["tags"] = []
    for tag in tags:
        if tag not in record["tags"]:
            record["tags"].append(tag)


def transfer_shared_record_fields(source_record: Record, target_record: Record) -> None:
    """Transfer shared fields (and tags) from source record to target record."""
    for field in SHARED_RECORD_FIELDS:
        if field in source_record and field not in target_record:
            target_record[field] = source_record[field]

    add_missing_tags(target_record, source_record.get("tags", []))


def get_ts_for(year: int, month: int, day: int) -> float:
    return time.mktime(datetime.date(year, month, day).timetuple())


# To fetch the ts for alc ordering we use "old_alc_ts" for files with "alc_ts" before this datetime.
# These files have a newer "alc_ts" with regard to clip updates that we want to ignore for ordering.
# You don't want to lose the information in "old_alc_ts" even though it doesn't match the .alc file timestamps.
OLD_ALC_TS_CUTOFF = get_ts_for(2016, 6, 12)

LISTS_FOLDER = "/Users/peter/github/djpeterhenry.github.io/lists"

COLLECTION_FOLDER = "/Users/peter/github/djpeterhenry.github.io/collection"

ACTIVE_LIST = "/Users/peter/github/djtools/active_list.txt"

# This is the folder to store demucs samples in.
# This should be relative to "/Users/peter/Music/Ableton/djpeterhenry/"
DEMUCS_SAMPLES = "Samples/Demucs"


def project_path_from_alc_filename(alc_filename: str) -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(alc_filename)))


def get_int(prompt_string: str) -> int | None:
    ui = input(prompt_string)
    try:
        return int(ui)
    except ValueError:
        return None


def is_ableton_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1]
    return ext in ALL_EXTENSIONS


def get_ableton_files() -> list[str]:
    walk_result = os.walk(".")
    result = []
    for dirpath, _, filenames in walk_result:
        for f in filenames:
            # hack to remove './' for compatibility
            filename = os.path.join(dirpath, f)[2:]
            if is_ableton_file(filename):
                result.append(filename)
    return sorted(result, key=lambda x: x.lower())


def get_display_name(filename: str, record: Record) -> str:
    result, ext = os.path.splitext(filename)
    # add extension:
    if ext not in [".alc"]:
        result = "%s (%s)" % (result, ext[1:].upper())
    # add vocal:
    if is_vocal(record):
        result = result + " [Vocal]"
    return result


def rotate_file(filename: str) -> None:
    MAX_BACKUP = 50

    def force_move(src: str, dst: str) -> None:
        try:
            os.remove(dst)
        except OSError:
            pass
        try:
            os.rename(src, dst)
        except OSError:
            pass

    for x in reversed(range(1, MAX_BACKUP)):
        src = "{}.{}".format(filename, x)
        dst = "{}.{}".format(filename, x + 1)
        force_move(src, dst)

    force_move(filename, "{}.1".format(filename))
    assert not os.path.isfile(filename)


@timing
def read_db_file(filename: str = DATABASE_JSON) -> DbDict:
    assert os.path.isfile(filename)
    with open(filename, "r", encoding="utf8") as json_file:
        return json.load(json_file)


@timing
def write_db_file(db_dict: DbDict, rotate: bool = True) -> None:
    """Atomically replace database.json, first rotating it into the backups.

    Serialized and written beside the db before touching it, so a failure at any
    point leaves the current database.json in place.
    """
    data = json.dumps(db_dict, ensure_ascii=False)
    tmp = DATABASE_JSON + ".tmp"
    with open(tmp, "w", encoding="utf8") as json_file:
        json_file.write(data)
    if rotate:
        rotate_file(DATABASE_JSON)
    os.replace(tmp, DATABASE_JSON)


def get_tags(record: Record) -> list[str]:
    return record.get("tags", [])


def has_tag(record: Record, tag: str) -> bool:
    return tag in get_tags(record)


def add_tag(record: Record, tag: str) -> None:
    if not has_tag(record, tag):
        record.setdefault("tags", []).append(tag)


def remove_tag(record: Record, tag: str) -> None:
    if has_tag(record, tag):
        get_tags(record).remove(tag)


def is_vocal(record: Record) -> bool:
    return has_tag(record, Tag.VOCAL_TAG.value)


def use_for_rekordbox(record: Record) -> bool:
    if has_tag(record, "x"):
        return False
    if has_tag(record, "x_rekordbox"):
        return False
    if has_tag(record, Tag.SS_TAG.value):
        return False
    return True


def has_extension(f: str, extension: str) -> bool:
    return os.path.splitext(f)[1] == extension


def is_alc_file(f: str) -> bool:
    return has_extension(f, ".alc")


def is_als_file(f: str) -> bool:
    return has_extension(f, ".als")


def alc_to_str(alc_filename: str) -> str:
    with gzip.open(alc_filename, "rb") as f:
        return f.read().decode("utf8")


def alc_to_xml(alc_filename: str) -> ET.Element:
    # Something I saw on google:
    # XML carries it's own encoding information (defaulting to UTF-8) and ElementTree does the work for you.
    # So I could almost certainly continue to pass a bytestring to ET.fromstring like I was doing until recently.
    return ET.fromstring(alc_to_str(alc_filename))


def write_xml_to_alc(xml_root: ET.Element, alc_filename: str) -> None:
    xml_str = ET.tostring(xml_root, encoding="utf-8", xml_declaration=True)
    with gzip.open(alc_filename, "wb") as f:
        f.write(xml_str)
    print("Wrote: " + alc_filename)


def _find(xml: ET.Element, path: str) -> ET.Element:
    """Like xml.find, but a missing element is an error rather than None."""
    found = xml.find(path)
    if found is None:
        raise ValueError("Ableton XML has no <{}> under <{}>".format(path, xml.tag))
    return found


def _attr(xml: ET.Element, name: str) -> str:
    value = xml.get(name)
    if value is None:
        raise ValueError("Ableton XML <{}> has no {} attribute".format(xml.tag, name))
    return value


def _value(xml: ET.Element, path: str) -> str:
    """The Value attribute of the element at path, which Ableton uses for most settings."""
    return _attr(_find(xml, path), "Value")


def get_xml_clip_info(xml_clip: ET.Element) -> ClipInfo | None:
    warp_markers: list[WarpMarker] = [
        {
            "sec_time": float(_attr(marker, "SecTime")),
            "beat_time": float(_attr(marker, "BeatTime")),
        }
        for marker in _find(xml_clip, "WarpMarkers")
    ]
    xml_loop = _find(xml_clip, "Loop")
    # Get verified sample path and timestamp
    xml_fileref = _find(xml_clip, "SampleRef/FileRef")

    def get_sample_filepath_old() -> str | None:
        # Example in <FileRef>
        # <HasRelativePath Value="true" />
        # <RelativePathType Value="3" />
        # <RelativePath>
        #     <RelativePathElement Dir="Samples" />
        #     <RelativePathElement Dir="Imported" />
        # </RelativePath>
        # <Name Value="deadmau5 - Arguru 2k19 (Original Mix).aiff" />
        xml_name = xml_fileref.find("Name")
        if xml_name is None:
            return None
        relative_path = os.path.join(
            "..", *[_attr(x, "Dir") for x in _find(xml_fileref, "RelativePath")]
        )
        return os.path.join(relative_path, _attr(xml_name, "Value"))

    def get_sample_filepath_new() -> str | None:
        # Example in <FileRef>
        # <RelativePathType Value="3" />
        # <RelativePath Value="Samples/Imported/Bob Sinclar - Cinderella (She said her name) (Meridian Remix).aiff" />
        # <Path Value="/Users/peter/Music/Ableton/djpeterhenry/Samples/Imported/Bob Sinclar - Cinderella (She said her name) (Meridian Remix).aiff" />

        # I guess I'll keep the previous behavior of keeping this path relative to the .alc file
        # This means I have to go up one folder using ".." because the sample relative path is to the top level djpeterhenry project
        xml_relative_path = xml_fileref.find("RelativePath")
        relative_path = None if xml_relative_path is None else xml_relative_path.get("Value")
        if not relative_path:
            return None
        return os.path.join("..", relative_path)

    sample_filepath_is_new_format = False
    sample_filepath = get_sample_filepath_old()
    if not sample_filepath:
        sample_filepath_is_new_format = True
        sample_filepath = get_sample_filepath_new()

    if not sample_filepath or not os.path.exists(sample_filepath):
        return None
    return {
        "warp_markers": warp_markers,
        "loop_start": float(_value(xml_loop, "LoopStart")),
        "loop_end": float(_value(xml_loop, "LoopEnd")),
        "start_relative": float(_value(xml_loop, "StartRelative")),
        "loop_on": _value(xml_loop, "LoopOn") == "true",
        "hidden_loop_start": float(_value(xml_loop, "HiddenLoopStart")),
        "hidden_loop_end": float(_value(xml_loop, "HiddenLoopEnd")),
        "sample": sample_filepath,
        "sample_ts": os.path.getmtime(sample_filepath),
        "sample_filepath_is_new_format": sample_filepath_is_new_format,
    }


def get_audioclip_from_alc(alc_filename: str) -> ClipInfo | None:
    xml_root = alc_to_xml(alc_filename)
    # just find the first AudioClip for now
    xml_clip = xml_root.find(".//AudioClip")
    if xml_clip is None:
        return None
    return get_xml_clip_info(xml_clip)


def get_audioclips_from_als(als_filename: str) -> list[ClipInfo | None]:
    xml_root = alc_to_xml(als_filename)
    return [get_xml_clip_info(xml_clip) for xml_clip in xml_root.findall(".//AudioClip")]


def _repath_first_audioclip(
    xml_root: ET.Element, alc_filename: str, new_alc_filename: str, new_sample_path: str
) -> ET.Element | None:
    """Point the first AudioClip at new_sample_path and name it after
    new_alc_filename.  Returns the clip, or None if there isn't one."""
    xml_clip = xml_root.find(".//AudioClip")
    if xml_clip is None:
        return None

    xml_fileref = xml_clip.find("SampleRef/FileRef")
    if xml_fileref is None:
        return None

    # make sure we start with an absolute path
    new_sample_path = os.path.abspath(new_sample_path)

    # Get relative path to the project
    project_path = project_path_from_alc_filename(alc_filename)
    new_sample_path_project_relative = os.path.relpath(new_sample_path, project_path)

    # Update the sample path, relative and absolute
    _find(xml_fileref, "RelativePath").set("Value", new_sample_path_project_relative)
    _find(xml_fileref, "Path").set("Value", new_sample_path)

    # Update the name for the audioclip
    _find(xml_clip, "Name").set(
        "Value", os.path.splitext(os.path.basename(new_alc_filename))[0]
    )
    return xml_clip


def replace_audioclip_path(alc_filename: str, new_alc_filename: str, new_sample_path: str) -> bool:
    """
    Replace the sample path in an Ableton Live .alc file with a new sample path.
    """
    if os.path.splitext(alc_filename)[1] != ".alc":
        raise ValueError("alc_filename must have .alc extension")
    if os.path.splitext(new_alc_filename)[1] != ".alc":
        raise ValueError("new_alc_filename must have .alc extension")

    xml_root = alc_to_xml(alc_filename)
    if _repath_first_audioclip(xml_root, alc_filename, new_alc_filename, new_sample_path) is None:
        return False

    # Lots of other things are now wrong.  However I seem to be able to open this alc file without fixing these.
    # <OriginalFileSize Value="17215488" />
    # <OriginalCrc Value="46285" />

    write_xml_to_alc(xml_root, new_alc_filename)
    return True


def write_silenced_alc(
    alc_filename: str, new_alc_filename: str, new_sample_path: str, sec_offset: float
) -> bool:
    """
    Like replace_audioclip_path, but also shifts every warp marker forward by
    sec_offset seconds.  Use this when sec_offset seconds of silence have been
    prepended to new_sample_path: shifting the warp markers keeps the beat grid
    aligned while pushing a previously-negative start time positive (which is
    what Rekordbox needs).

    Only SecTime (position within the audio file) changes.  BeatTime and all the
    beat-domain loop values are untouched, so bpm and beat alignment are preserved.

    Accepts .alc clips and .als sets.  For an .als with multiple audio clips, only
    the first AudioClip is repathed and re-warped.
    """
    if os.path.splitext(alc_filename)[1] not in (".alc", ".als"):
        raise ValueError("alc_filename must have .alc or .als extension")
    if os.path.splitext(new_alc_filename)[1] not in (".alc", ".als"):
        raise ValueError("new_alc_filename must have .alc or .als extension")

    xml_root = alc_to_xml(alc_filename)
    xml_clip = _repath_first_audioclip(xml_root, alc_filename, new_alc_filename, new_sample_path)
    if xml_clip is None:
        return False

    # Shift every warp marker forward to compensate for the prepended silence.
    for marker in _find(xml_clip, "WarpMarkers"):
        new_sec_time = float(_attr(marker, "SecTime")) + sec_offset
        marker.set("SecTime", repr(new_sec_time))

    # Best-effort: keep DefaultDuration (in samples) consistent with the longer
    # file.  Rekordbox ignores this and Ableton tolerates a mismatch, but it's
    # cheap to keep honest.
    xml_sample_ref = _find(xml_clip, "SampleRef")
    xml_default_duration = xml_sample_ref.find("DefaultDuration")
    xml_default_sample_rate = xml_sample_ref.find("DefaultSampleRate")
    if xml_default_duration is not None and xml_default_sample_rate is not None:
        sample_rate = float(_attr(xml_default_sample_rate, "Value"))
        duration = float(_attr(xml_default_duration, "Value"))
        new_duration = int(round(duration + sec_offset * sample_rate))
        xml_default_duration.set("Value", str(new_duration))

    write_xml_to_alc(xml_root, new_alc_filename)
    return True


def get_key_from_keyfinder_cli(sample_fullpath: str) -> str:
    try:
        result = subprocess.check_output(["keyfinder-cli", sample_fullpath])
    except subprocess.CalledProcessError as e:
        print("Error running keyfinder-cli:", e)
        # Assume a return code of 1 was because it wasn't 16-bit PCM.
        if e.returncode != 1:
            raise
        # Create a temporary conversion of sample_fullpath and run the process again.
        print("Converting to 16-bit PCM for keyfinder-cli...")
        temp_sample = sample_fullpath + ".temp.wav"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            sample_fullpath,
            "-c:a",
            "pcm_s16le",
            temp_sample,
        ]
        try:
            subprocess.check_call(command)
            result = subprocess.check_output(["keyfinder-cli", temp_sample])
        finally:
            if os.path.exists(temp_sample):
                os.remove(temp_sample)

    return result.decode("utf8").strip()


def generate_camelot_dict() -> tuple[dict[str, str], dict[str, str]]:
    camelot_list = [
        "Ab",
        "B",
        "Eb",
        "Gb",
        "Bb",
        "Db",
        "F",
        "Ab",
        "C",
        "Eb",
        "G",
        "Bb",
        "D",
        "F",
        "A",
        "C",
        "E",
        "G",
        "B",
        "D",
        "Gb",
        "A",
        "Db",
        "E",
    ]
    initial_dict = {}
    reverse_dict = {}
    ab = ["A", "B"]
    # this shit was fucking clever:
    for i, k in enumerate(camelot_list):
        camelot_name = str(i // 2 + 1) + ab[i % 2]
        if i % 2 == 0:
            k = k + "m"
        initial_dict[k] = camelot_name
        reverse_dict[camelot_name] = k
    full_dict = initial_dict.copy()
    for k, c in initial_dict.items():
        if len(k) > 1 and k[1] == "b":
            key_char = k[0]
            key_ascii = ord(key_char)
            sharp_ascii = key_ascii - 1
            if sharp_ascii < ord("A"):
                sharp_ascii = ord("G")
            sharp_key = chr(sharp_ascii)
            minor_str = ""
            if len(k) == 3:
                minor_str = "m"
            sharp_dict_entry = str(sharp_key) + "#" + minor_str
            full_dict[sharp_dict_entry] = c
    return full_dict, reverse_dict


# create global
camelot_dict, reverse_camelot_dict = generate_camelot_dict()

CAMELOT_KEY = re.compile(r"(1[0-2]|[1-9])[ABab]")


def normalized_camelot_key(s: str) -> str | None:
    if CAMELOT_KEY.fullmatch(s):
        return s.upper()
    return None


def get_camelot_key(s: str | None) -> str | None:
    # Records added before their key is analyzed have none
    if not s:
        return None
    # match direct
    match = normalized_camelot_key(s)
    if match:
        return match
    return camelot_dict.get(s)


def get_camelot_num(key: str | None) -> int | None:
    cam_key = get_camelot_key(key)
    if cam_key is None:
        return None
    return int(cam_key[:-1])


def reveal_file(filename: str) -> None:
    command = ["open", "-R", filename]
    subprocess.call(command)


def copy_file_to_clipboard(path: str) -> None:
    """Put a file on the clipboard (as a file, for pasting into Ableton).

    The path goes in as an argument rather than spliced into the script, so
    quotes and other shell characters in song names are harmless.
    """
    subprocess.call(
        [
            "osascript",
            "-e",
            "on run argv",
            "-e",
            "set the clipboard to POSIX file (item 1 of argv)",
            "-e",
            "end run",
            path,
        ]
    )


def get_missing() -> list[str]:
    db_dict = read_db_file()
    alc_file_set = set(get_ableton_files())
    result = []
    for filename, _ in sorted(db_dict.items()):
        if filename not in alc_file_set:
            result.append(filename)
    return result


def get_db_by_ts(db_dict: DbDict) -> dict[float, list[str]]:
    result = defaultdict(list)
    for f, record in db_dict.items():
        ts_list = get_ts_list(record)
        for ts in ts_list:
            result[ts].append(f)
    return result


def get_valid_alc_files(db_dict: DbDict) -> list[str]:
    alc_files = get_ableton_files()
    valid_alc_files = [filename for filename in alc_files if filename in db_dict]
    valid_alc_files.sort(key=lambda s: s.lower())
    return valid_alc_files


def filter_recordbox_files(files: Iterable[str], db_dict: DbDict) -> list[str]:
    return [f for f in files if f in db_dict and use_for_rekordbox(db_dict[f])]


def get_rekordbox_files(db_dict: DbDict) -> list[str]:
    alc_files = get_ableton_files()
    result = filter_recordbox_files(alc_files, db_dict)
    result.sort(key=lambda s: s.lower())
    return result


def generate_sample(valid_alc_files: Iterable[str], db_dict: DbDict) -> list[str]:
    date_file_tuples = []
    for f in valid_alc_files:
        clip = get_clip(db_dict[f])
        if clip is None:
            continue
        date_file_tuples.append((clip["sample_ts"], f))
    date_file_tuples.sort()
    date_file_tuples.reverse()
    return [file for _, file in date_file_tuples]


def get_files_from_pairs(pairs: Iterable[tuple[Any, str]]) -> list[str]:
    return [file for _, file in pairs]


def get_span_days(days: float) -> float:
    H = 60 * 60
    D = 24 * H
    return D * days


def get_span_years(years: float) -> float:
    return get_span_days(365 * years)


def get_past_ts(span: float) -> float:
    now = time.time()
    return now - span


def get_ts_list(record: Record) -> list[float]:
    return sorted(record.get("ts_list", []))


def add_ts(record: Record, ts: float) -> None:
    ts_list = get_ts_list(record)
    if ts not in ts_list:
        ts_list.append(ts)
    record["ts_list"] = ts_list


def get_last_ts(record: Record) -> float:
    ts_list = get_ts_list(record)
    try:
        return ts_list[-1]
    except IndexError:
        return 0


def get_ts_list_date_limited(record: Record) -> list[float]:
    """Return a list of the timestamps, but only the latest one for each day (date)"""
    ts_list = get_ts_list(record)
    date_map = {}
    for ts in ts_list:
        date = datetime.date.fromtimestamp(ts)
        previous_ts = date_map.get(date, 0)
        if ts > previous_ts:
            date_map[date] = ts
    return sorted(date_map.values())


def get_ts_date_count(record: Record, ts_after: float | None = None) -> int:
    ts_list = get_ts_list_date_limited(record)
    if ts_after:
        ts_list = [x for x in ts_list if x >= ts_after]
    return len(ts_list)


def get_alc_ts(record: Record) -> float:
    # old_alc_ts is the one you want for ordering and display if it exists.
    #
    # There are alc files with a modified timestamp before old_alc_ts.
    # But this is not consistent...these should not be trusted for ordering.
    #
    # So for ordering, use "get_alc_ts",
    # but for checking whether clips need to be updated, check the "alc_ts" record value directly.
    alc_ts = record.get("alc_ts")
    if alc_ts is None:
        return 0
    old_alc_ts = record.get("old_alc_ts")
    if alc_ts < OLD_ALC_TS_CUTOFF and old_alc_ts is not None:
        return old_alc_ts
    return alc_ts


def get_alc_or_last_ts(record: Record) -> float:
    return max(get_alc_ts(record), get_last_ts(record))


def get_date_from_ts(ts: float) -> str:
    return datetime.date.fromtimestamp(ts).strftime("%Y-%m-%d")


def get_clip(record: Record) -> ClipInfo | None:
    """The record's first audio clip, or None.

    A clip is stored as None when its sample file has gone missing.
    """
    return record.get("clip")


def get_sample(record: Record) -> str | None:
    clip = get_clip(record)
    if clip is None:
        return None
    return clip["sample"]


def _generate_ts_pairs(
    valid_alc_files: Iterable[str], db_dict: DbDict, get_ts: Callable[[Record], float]
) -> list[tuple[float, str]]:
    """(ts, file) pairs, newest first (ties broken by reverse filename)."""
    return sorted(((get_ts(db_dict[f]), f) for f in valid_alc_files), reverse=True)


def generate_alc_pairs(valid_alc_files: Iterable[str], db_dict: DbDict) -> list[tuple[float, str]]:
    return _generate_ts_pairs(valid_alc_files, db_dict, get_alc_ts)


def generate_date_pairs(valid_alc_files: Iterable[str], db_dict: DbDict) -> list[tuple[float, str]]:
    return _generate_ts_pairs(valid_alc_files, db_dict, get_last_ts)


def generate_date_plus_alc_pairs(
    valid_alc_files: Iterable[str], db_dict: DbDict
) -> list[tuple[float, str]]:
    return _generate_ts_pairs(valid_alc_files, db_dict, get_alc_or_last_ts)


def generate_num_alc_pairs(
    valid_alc_files: Iterable[str], db_dict: DbDict, ts_after: float | None
) -> list[tuple[int, str]]:
    num_file_tuples = []
    for file in valid_alc_files:
        record = db_dict[file]
        num = get_ts_date_count(record, ts_after)
        num_file_tuples.append((num, file))
    # Ties on play count break on recency, so equal counts read most recent
    # first instead of by filename.
    num_file_tuples.sort(
        key=lambda pair: (pair[0], get_alc_or_last_ts(db_dict[pair[1]])), reverse=True
    )
    return num_file_tuples


def generate_alc(valid_alc_files: Iterable[str], db_dict: DbDict) -> list[str]:
    return get_files_from_pairs(generate_alc_pairs(valid_alc_files, db_dict))


def generate_date(valid_alc_files: Iterable[str], db_dict: DbDict) -> list[str]:
    return get_files_from_pairs(generate_date_pairs(valid_alc_files, db_dict))


def generate_date_plus_alc(valid_alc_files: Iterable[str], db_dict: DbDict) -> list[str]:
    return get_files_from_pairs(generate_date_plus_alc_pairs(valid_alc_files, db_dict))


def generate_num(
    valid_alc_files: Iterable[str], db_dict: DbDict, ts_after: float | None = None
) -> list[str]:
    return get_files_from_pairs(
        generate_num_alc_pairs(valid_alc_files, db_dict, ts_after)
    )


def generate_recent_and_old(
    files: Iterable[str], db_dict: DbDict, years: float
) -> tuple[list[str], list[str]]:
    past_ts = get_past_ts(get_span_years(years))
    date_file = generate_date_plus_alc_pairs(files, db_dict)
    recent = [f for ts, f in date_file if ts >= past_ts]
    old = [f for ts, f in date_file if ts < past_ts]
    return recent, old


def generate_random(files: Iterable[str]) -> list[str]:
    files_copy = list(files)
    random.shuffle(files_copy)
    return files_copy


def generate_sets(files: Iterable[str], db_dict: DbDict) -> list[str]:
    ts_db_dict = get_db_by_ts(db_dict)
    ts_sorted = sorted(ts_db_dict.keys(), reverse=True)

    file_set = set(files)

    result = []
    # now from most recent
    last_ts = None
    last_file = None
    for ts in ts_sorted:
        if last_ts is None:
            last_ts = ts
        ts_diff = last_ts - ts
        max_seconds = 30 * 60
        if ts_diff > max_seconds:
            divider = "-" * 12 + " {}".format(get_date_from_ts(ts))
            result.append(divider)
        last_ts = ts
        for f in ts_db_dict[ts]:
            if f not in file_set:
                continue
            if f == last_file:
                continue
            result.append(f)
            last_file = f
    return result


def get_keys_for_camelot_number(camelot_number: int | str | None) -> list[str]:
    if camelot_number is None:
        return []
    key_minor = reverse_camelot_dict[str(camelot_number) + "A"]
    key_major = reverse_camelot_dict[str(camelot_number) + "B"]
    return [key_minor, key_major]


def get_relative_camelot_key(cam_num: int, offset: int) -> int:
    return ((cam_num + offset - 1) % 12) + 1


def matches_bpm_filter(filter_bpm: float, bpm_range: float, bpm: float) -> bool:
    for sub_bpm in [int(round(bpm / 2.0)), bpm, int(round(bpm * 2.0))]:
        if sub_bpm >= filter_bpm - bpm_range and sub_bpm <= filter_bpm + bpm_range:
            return True
    return False


def update_db_clips(
    valid_alc_files: Iterable[str],
    db_dict: DbDict,
    force_alc: bool = False,
    force_als: bool = False,
) -> None:
    print("update_db_clips")
    for f in valid_alc_files:
        record = db_dict[f]
        f_ts = os.path.getmtime(f)
        # Get the first clip for key/update purposes from both alc and als
        if is_alc_file(f) or is_als_file(f):
            if (
                force_alc
                or record.get("alc_ts") != f_ts
                or not record.get("clip", None)
            ):
                record["clip"] = get_audioclip_from_alc(f)
                record["alc_ts"] = f_ts
                print("Updated clip:", f)
        # If it's an als file, get the "clips" as well
        if is_als_file(f):
            if (
                force_als
                or record.get("als_ts") != f_ts
                or not record.get("clips", None)
            ):
                record["clips"] = get_audioclips_from_als(f)
                record["als_ts"] = f_ts
                print("Updated clips:", f)


def update_db_clips_safe() -> None:
    db_dict = read_db_file()
    valid_alc_files = get_valid_alc_files(db_dict)
    update_db_clips(valid_alc_files, db_dict)
    write_db_file(db_dict)


def get_artist_and_track(filename: str) -> tuple[str, str]:
    """
    Extract artist and track name from a filename.
    Apply unidecode to the result so rekordbox search works better and so you can later use this funciton to match back from rekordbox to the filename.
    """
    artist = ""
    track = ""

    delimiter = " - "
    split = os.path.splitext(filename)[0].split(delimiter)
    if len(split) == 1:
        track = split[0]
    else:
        artist = split[0]
        # Join the rest as track name.  Needing to join here will be rare.
        if len(split) > 2:
            track = delimiter.join(split[1:])
        else:
            track = split[1]
    return (unidecode(artist.strip()), unidecode(track.strip()))


def get_export_sample_path(f: str, sample_ext: str, target_path: str) -> str:
    f_base, _ = os.path.splitext(f)
    return os.path.join(target_path, f_base + sample_ext)


def get_existing_rekordbox_sample(record: Record) -> str | None:
    sample = record.get(REKORDBOX_LOCAL_SAMPLE_KEY)
    if sample and os.path.isfile(sample):
        return sample
    return None


def get_list_name_to_file(path: str) -> dict[str, str]:
    files = [os.path.join(path, f) for f in os.listdir(path)]
    name_to_file = {}
    for f in files:
        if not os.path.isfile(f):
            continue
        name, ext = os.path.splitext(os.path.basename(f))
        if ext in (".txt", "") and not name.startswith("."):
            name_to_file[name] = f
    return name_to_file


# TODO: This function predates unidecode and shouldn't be used for new code.
def get_song_in_db(s: str, db_dict: Mapping[str, object]) -> tuple[str, str | None]:
    alc_filename = s + ".alc"
    als_filename = s + ".als"
    if s in db_dict:
        t = (s, s)
    elif als_filename in db_dict:
        t = (s, als_filename)
    elif alc_filename in db_dict:
        t = (s, alc_filename)
    else:
        t = (s, None)
    return t


def get_filename_unidecode_matching(artist: str, track: str, db_dict: DbDict) -> str | None:
    """
    Get matching filename from artist and track, including unidecode.
    This is a linear search through the database so should be avoided if possible.
    """
    artist = unidecode(artist.strip())
    track = unidecode(track.strip())
    for filename, _ in db_dict.items():
        db_artist, db_track = get_artist_and_track(filename)
        if artist == db_artist and track == db_track:
            return filename
    return None


def get_list_from_file(filename: str, db_dict: DbDict) -> list[tuple[str, str | None]]:
    p_timestamp = re.compile(r"\[[\d:]+\] (.*)")
    with open(filename) as f:
        song_list = [song.strip() for song in f.readlines()]
        display_and_file = []
        for s in song_list:
            m_timestamp = p_timestamp.match(s)
            if m_timestamp:
                s = m_timestamp.group(1)
            t = get_song_in_db(s, db_dict)
            display_and_file.append(t)
        return display_and_file


def strip_title_tags(title: str) -> str:
    """Drop the [#tag] suffixes the rekordbox export appends to track names."""
    return title.split("[")[0].strip()


def stamp_song(db_dict: DbDict, ts: float, artist: str, title: str) -> None:
    filename = get_filename_unidecode_matching(artist, title, db_dict)
    if filename is None:
        print("Failure to stamp: {} - {}".format(artist, title))
        return
    record = db_dict[filename]
    add_ts(record, ts)


def update_with_rekordbox_tags(db_dict: DbDict, tags_filepath: str) -> None:
    tag_str = os.path.splitext(os.path.basename(tags_filepath))[0].upper()
    # The tag must match a known Tag value
    if tag_str not in Tag.__members__:
        print(f"Unknown tag: {tag_str}")
        return
    tag = Tag[tag_str]

    with open(tags_filepath, encoding="utf-16le") as f:
        # Obtain the track and artist column indices
        header = f.readline().strip().split("\t")
        artist_col = header.index("Artist")
        title_col = header.index("Track Title")

        for line in f.readlines():
            columns = line.strip().split("\t")
            artist = columns[artist_col]
            title = strip_title_tags(columns[title_col])
            filename = get_filename_unidecode_matching(artist, title, db_dict)
            if filename is None:
                print(f"Failure to tag: {artist} - {title}")
                continue
            record = db_dict[filename]
            add_tag(record, tag.value)


def get_release_year(record: Record) -> int | None:
    """Get the release year: a manual entry if there is one, else discogs."""
    manual = record.get("release_year_manual")
    if manual is not None:
        return manual
    return record.get("release_year_discogs")


def generate_lists(output_path: str = COLLECTION_FOLDER, push: bool = True) -> None:
    db_dict = read_db_file()
    files = get_rekordbox_files(db_dict)

    def write_files(filename: str, alc_filenames_to_write: Iterable[str]) -> None:
        with open(
            os.path.join(output_path, filename), "w", encoding="utf-8"
        ) as outfile:
            for f in alc_filenames_to_write:
                f_print = os.path.splitext(f)[0]
                outfile.write("{}\n".format(f_print))

    write_files("date_or_add.txt", generate_date_plus_alc(files, db_dict))
    write_files("add.txt", generate_alc(files, db_dict))
    write_files("name.txt", files)
    write_files("num.txt", generate_num(files, db_dict))
    write_files("sets.txt", generate_sets(files, db_dict))

    if push:
        repo = os.path.dirname(output_path)
        subprocess.run(["git", "-C", repo, "add", "collection/"], check=True)
        result = subprocess.run(["git", "-C", repo, "commit", "-m", "update collections"])
        if result.returncode not in (0, 1):
            result.check_returncode()
        if result.returncode == 0:
            subprocess.run(["git", "-C", repo, "push"], check=True)
