#!/usr/bin/env python
# Created on May 14, 2009
from __future__ import print_function

import sys
import os
import cPickle
import re
import random
import subprocess
import gzip
import xml.etree.ElementTree as ET
import time
import datetime
from collections import defaultdict
import json
import io
import string
from timing import timing

from tag import Tag


try:
    UNICODE_EXISTS = bool(type(unicode))
except NameError:
    from six import u as unicode


# DB_FILENAME = "aadb.txt"
DB_FILENAME = "aadb_unicode.txt"
DATABASE_JSON = "database.json"

ABLETON_EXTENSIONS = [".alc", ".als"]
SAMPLE_EXTENSIONS = [".mp3", ".m4a", ".wav", ".aiff", ".flac"]
ALL_EXTENSIONS = ABLETON_EXTENSIONS + SAMPLE_EXTENSIONS

REKORDBOX_LOCAL_SAMPLE_KEY = "rekordbox_local_sample"


def get_ts_for(year, month, day):
    return time.mktime(datetime.date(year, month, day).timetuple())


# To fetch the ts for alc ordering we use "old_alc_ts" for files with "alc_ts" before this datetime.
# These files have a newer "alc_ts" with regard to clip updates that we want to ignore for ordering.
# You don't want to lose the information in "old_alc_ts" even though it doesn't match the .alc file timestamps.
OLD_ALC_TS_CUTOFF = get_ts_for(2016, 6, 12)

LISTS_FOLDER = "/Users/peter/github/djpeterhenry.github.io/lists"

COLLECTION_FOLDER = "/Users/peter/github/djpeterhenry.github.io/collection"

ACTIVE_LIST = "/Users/peter/github/djtools/active_list.txt"


def get_int(prompt_string):
    # Make input be raw_input on python2
    try:
        input = raw_input
    except NameError:
        pass

    ui = input(prompt_string)
    try:
        return int(ui)
    except ValueError:
        return None


def is_ableton_file(filename):
    ext = os.path.splitext(filename)[1]
    return ext in ALL_EXTENSIONS


def get_ableton_files():
    walk_result = os.walk(u".")
    result = []
    for dirpath, _, filenames in walk_result:
        for f in filenames:
            # hack to remove './' for compatibility
            filename = os.path.join(dirpath, f)[2:]
            if is_ableton_file(filename):
                result.append(filename)
    return sorted(result, key=string.lower)


def get_base_filename(filename, record):
    result, ext = os.path.splitext(filename)
    if "pretty_name" in record:
        result = record["pretty_name"]
    # add extension:
    if ext not in [".alc"]:
        result = "%s (%s)" % (result, ext[1:].upper())
    # add vocal:
    if is_vocal(record):
        result = result + " [Vocal]"
    return result


@timing
def read_db_file_pickle():
    db_dict = None
    if os.path.exists(DB_FILENAME):
        db_file = open(DB_FILENAME)
        try:
            db_dict = cPickle.load(db_file)
            # print ("Loaded: " + DB_FILENAME)
        except:
            print("Error opening pickle file...")
            sys.exit(1)
    else:
        print("Will create new: " + DB_FILENAME)
        db_dict = {}
    return db_dict


def rotate_file(filename):
    MAX_BACKUP = 50

    def force_move(src, dst):
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

    # use last value for "src" as the backup target for filename
    force_move(filename, src)
    assert not os.path.isfile(filename)


@timing
def write_db_file_pickle(db_dict):
    rotate_file(DB_FILENAME)
    with open(DB_FILENAME, "w") as db_file:
        cPickle.dump(db_dict, db_file)
    print("Wrote: " + DB_FILENAME)


@timing
def write_db_json(db_dict):
    rotate_file(DATABASE_JSON)
    with io.open(DATABASE_JSON, "w", encoding="utf8") as json_file:
        # data = json.dumps(db_dict, ensure_ascii=False, indent=4)
        data = json.dumps(db_dict, ensure_ascii=False)
        json_file.write(unicode(data))


@timing
def read_db_json():
    assert os.path.isfile(DATABASE_JSON)
    with io.open(DATABASE_JSON, "r", encoding="utf8") as json_file:
        db_dict = json.load(json_file)
    return db_dict


def read_db_file():
    return read_db_json()


def write_db_file(db_dict):
    write_db_json(db_dict)


def use_for_rekordbox(record):
    if "x" in record["tags"]:
        return False
    if "x_rekordbox" in record["tags"]:
        return False
    if Tag.SS_TAG.value in record["tags"]:
        return False
    return True


def is_vocal(record):
    """
    Common enough to keep I guess?
    """
    return Tag.VOCAL_TAG.value in record["tags"]


def has_extension(f, extension):
    return os.path.splitext(f)[1] == extension


def is_alc_file(f):
    return has_extension(f, ".alc")


def is_als_file(f):
    return has_extension(f, ".als")


def alc_to_str(alc_filename):
    with gzip.open(alc_filename, "rb") as f:
        return f.read()


def alc_to_xml(alc_filename):
    # Something I saw on google:
    # XML carries it's own encoding information (defaulting to UTF-8) and ElementTree does the work for you.
    return ET.fromstring(alc_to_str(alc_filename))


def get_xml_clip_info(xml_clip):
    result = {}
    xml_warp_markers = xml_clip.find("WarpMarkers")
    result["warp_markers"] = []
    for marker in xml_warp_markers:
        result["warp_markers"].append(
            dict(
                sec_time=float(marker.get("SecTime")),
                beat_time=float(marker.get("BeatTime")),
            )
        )
    xml_loop = xml_clip.find("Loop")
    result["loop_start"] = float(xml_loop.find("LoopStart").get("Value"))
    result["loop_end"] = float(xml_loop.find("LoopEnd").get("Value"))
    result["start_relative"] = float(xml_loop.find("StartRelative").get("Value"))
    result["loop_on"] = (
        True if xml_loop.find("LoopOn").get("Value") == "true" else False
    )
    result["hidden_loop_start"] = float(xml_loop.find("HiddenLoopStart").get("Value"))
    result["hidden_loop_end"] = float(xml_loop.find("HiddenLoopEnd").get("Value"))
    # also sample info
    xml_fileref = xml_clip.find("SampleRef/FileRef")
    relative_path = os.path.join(
        "..", *[x.get("Dir") for x in xml_fileref.find("RelativePath")]
    )
    sample_filepath = os.path.join(relative_path, xml_fileref.find("Name").get("Value"))
    if os.path.exists(sample_filepath):
        result["sample"] = sample_filepath
        result["sample_ts"] = os.path.getmtime(sample_filepath)
    else:
        return None
    return result


def get_audioclip_from_alc(alc_filename):
    xml_root = alc_to_xml(alc_filename)
    # just find the first AudioClip for now
    xml_clip = xml_root.find(".//AudioClip")
    if xml_clip is None:
        return None
    return get_xml_clip_info(xml_clip)


def get_audioclips_from_als(als_filename):
    xml_root = alc_to_xml(als_filename)
    result = []
    for xml_clip in xml_root.findall(".//AudioClip"):
        result.append(get_xml_clip_info(xml_clip))
    return result


def get_sample_from_xml(xml_root):
    """
    This function was written specifically for keyfinding before I stored clip info.
    It could probably be removed now and replaced with "clip" functionality.
    """
    sample_refs = xml_root.findall(".//SampleRef")
    # right now, just the first
    sample_ref = sample_refs[0]
    sample_filename = sample_ref.find("FileRef/Name").attrib["Value"]
    sample_path_list = [
        x.attrib["Dir"]
        for x in sample_ref.findall("FileRef/SearchHint/PathHint/RelativePathElement")
    ]
    sample_file_folder = os.path.join("/", *sample_path_list)
    sample_file_fullpath = os.path.join(sample_file_folder, sample_filename)
    if os.path.exists(sample_file_fullpath):
        return sample_file_fullpath
    # for some reason, files can have an invalid path and still work??
    # it's just PathHints after all
    sample_file_folder = "/Users/peter/Music/Ableton/djpeterhenry/Samples/Imported"
    sample_file_fullpath = os.path.join(sample_file_folder, sample_filename)
    if os.path.exists(sample_file_fullpath):
        return sample_file_fullpath
    return None


def get_sample_from_alc_file(alc_filename):
    """
    I guess this also returns the file itself it it happens to be a "sample" already.
    I think this was an attempt to generalize key finding to both .alc files and audio files.
    I think this is only used in get_key_from_alc.

    I also think this is the only function that uses "get_sample_from_xml".
    This is confusing, should consistently use "clip"->"sample" instead I think.
    """
    if os.path.splitext(alc_filename)[1] in SAMPLE_EXTENSIONS:
        return alc_filename
    return get_sample_from_xml(alc_to_xml(alc_filename))


def get_key_from_sample(sample_fullpath):
    """
    Sort of. Call the executable with the command line arguments -f filepath to
    have the key estimate printed to stdout (and/or any errors to stderr).
    If you also use the switch -w it will try and write to tags.
    Preferences from the GUI are used to determine the exact operation of the CLI.

    Don't forget that the Mac binary is buried in the .app bundle,
    so your command line will look something like:
    ./KeyFinder.app/Contents/MacOS/KeyFinder -f ~/Music/my_track.mp3 [-w]
    """
    if sample_fullpath is None:
        return None
    keyfinder_app = "/Applications/KeyFinder.app/Contents/MacOS/KeyFinder"
    command = '"%s" -f "%s"' % (keyfinder_app, sample_fullpath)
    result = subprocess.check_output(command, shell=True)
    return result


def get_key_from_alc(alc_filename):
    sample_file = get_sample_from_alc_file(alc_filename)
    return get_key_from_sample(sample_file)


def get_clips_from_als(als_filename):
    xml_root = alc_to_xml(als_filename)
    audio_clips = xml_root.findall(".//AudioClip")
    result = []
    for clip in audio_clips:
        name = clip.find("Name").attrib["Value"]
        time = float(clip.attrib["Time"])
        # only those which actually appear
        # no because some mixes actually start at 0
        # if time <= 0: continue
        result.append((time, name))
    result.sort()
    # in sorted list, remove sequential dups
    unique_result = []
    previous_name = None
    for t, n in result:
        if previous_name is None or n != previous_name:
            unique_result.append((t, n))
        previous_name = n
    return unique_result


def generate_camelot_dict():
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
        camelot_name = str(i / 2 + 1) + ab[i % 2]
        if i % 2 == 0:
            k = k + "m"
        initial_dict[k] = camelot_name
        reverse_dict[camelot_name] = k
    full_dict = initial_dict.copy()
    for k, c in initial_dict.iteritems():
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

CAMELOT_KEY = re.compile("([0-9][0-9]?)[A|B|a|b]")


def normalized_camelot_key(s):
    if CAMELOT_KEY.match(s):
        return s.upper()


def get_camelot_key(s):
    # match direct
    match = normalized_camelot_key(s)
    if match:
        return match
    return camelot_dict.get(s)


def get_camelot_num(key):
    cam_key = get_camelot_key(key)
    if cam_key is None:
        return None
    return int(cam_key[:-1])


def reveal_file(filename):
    command = ["open", "-R", filename]
    subprocess.call(command)


def get_missing():
    db_dict = read_db_file()
    alc_file_set = set(get_ableton_files())
    result = []
    for filename, _ in sorted(db_dict.iteritems()):
        if filename not in alc_file_set:
            result.append(filename)
    return result


def get_db_by_ts(db_dict):
    result = defaultdict(list)
    for f, record in db_dict.iteritems():
        ts_list = get_ts_list(record)
        for ts in ts_list:
            result[ts].append(f)
    return result


def get_valid_alc_files(db_dict):
    alc_files = get_ableton_files()
    valid_alc_files = [filename for filename in alc_files if db_dict.has_key(filename)]
    valid_alc_files.sort(key=lambda s: s.lower())
    return valid_alc_files


def get_rekordbox_files(db_dict):
    alc_files = get_ableton_files()
    result = []
    for f in alc_files:
        try:
            record = db_dict[f]
        except:
            continue
        if not use_for_rekordbox(record):
            continue
        result.append(f)
    result.sort(key=lambda s: s.lower())
    return result


def generate_sample(valid_alc_files, db_dict):
    date_file_tuples = []
    for f in valid_alc_files:
        record = db_dict[f]
        if "clip" not in record:
            continue
        date_file_tuples.append((record["clip"]["sample_ts"], f))
    date_file_tuples.sort()
    date_file_tuples.reverse()
    return [file for _, file in date_file_tuples]


def get_files_from_pairs(pairs):
    return [file for _, file in pairs]


def get_span_days(days):
    H = 60 * 60
    D = 24 * H
    return D * days


def get_span_years(years):
    return get_span_days(365 * years)


def get_past_ts(span):
    now = time.time()
    return now - span


def get_ts_list(record):
    return sorted(record.get("ts_list", []))


def add_ts(record, ts):
    ts_list = get_ts_list(record)
    if ts not in ts_list:
        ts_list.append(ts)
    record["ts_list"] = ts_list


def get_last_ts(record):
    ts_list = get_ts_list(record)
    try:
        return ts_list[-1]
    except IndexError:
        return 0


def get_ts_list_date_limited(record):
    """Return a list of the timestamps, but only the latest one for each day (date)"""
    ts_list = get_ts_list(record)
    date_map = {}
    for ts in ts_list:
        date = datetime.date.fromtimestamp(ts)
        previous_ts = date_map.get(date, 0)
        if ts > previous_ts:
            date_map[date] = ts
    return sorted(date_map.values())


def get_ts_date_count(record, ts_after=None):
    ts_list = get_ts_list_date_limited(record)
    if ts_after:
        ts_list = [x for x in ts_list if x >= ts_after]
    return len(ts_list)


def get_alc_ts(record):
    try:
        alc_ts = record["alc_ts"]
        if alc_ts < OLD_ALC_TS_CUTOFF and "old_alc_ts" in record:
            return record["old_alc_ts"]
        return alc_ts
    except KeyError:
        return 0


def get_alc_or_last_ts(record):
    return max(get_alc_ts(record), get_last_ts(record))


def get_date_from_ts(ts):
    return datetime.date.fromtimestamp(ts).strftime("%Y-%m-%d")


def get_sample(record):
    try:
        return record["clip"]["sample"]
    except KeyError:
        return None


def generate_alc_pairs(valid_alc_files, db_dict):
    tuples = []
    for f in valid_alc_files:
        tuples.append((get_alc_ts(db_dict[f]), f))
    tuples.sort()
    tuples.reverse()
    return tuples


def generate_date_pairs(valid_alc_files, db_dict):
    tuples = []
    for f in valid_alc_files:
        tuples.append((get_last_ts(db_dict[f]), f))
    tuples.sort()
    tuples.reverse()
    return tuples


def generate_date_plus_alc_pairs(valid_alc_files, db_dict):
    tuples = []
    for f in valid_alc_files:
        tuples.append((get_alc_or_last_ts(db_dict[f]), f))
    tuples.sort()
    tuples.reverse()
    return tuples


def generate_num_alc_pairs(valid_alc_files, db_dict, ts_after):
    num_file_tuples = []
    for file in valid_alc_files:
        record = db_dict[file]
        num = get_ts_date_count(record, ts_after)
        num_file_tuples.append((num, file))
    num_file_tuples.sort(reverse=True)
    return num_file_tuples


def generate_alc(valid_alc_files, db_dict):
    return get_files_from_pairs(generate_alc_pairs(valid_alc_files, db_dict))


def generate_date(valid_alc_files, db_dict):
    return get_files_from_pairs(generate_date_pairs(valid_alc_files, db_dict))


def generate_date_plus_alc(valid_alc_files, db_dict):
    return get_files_from_pairs(generate_date_plus_alc_pairs(valid_alc_files, db_dict))


def generate_num(valid_alc_files, db_dict, ts_after=None):
    return get_files_from_pairs(
        generate_num_alc_pairs(valid_alc_files, db_dict, ts_after)
    )


def generate_recent_and_old(files, db_dict, years):
    past_ts = get_past_ts(get_span_years(years))
    date_file = generate_date_plus_alc_pairs(files, db_dict)
    recent = [f for ts, f in date_file if ts >= past_ts]
    old = [f for ts, f in date_file if ts < past_ts]
    return recent, old


def generate_random(files):
    files_copy = list(files)
    random.shuffle(files_copy)
    return files_copy


def generate_sets(files, db_dict):
    ts_db_dict = get_db_by_ts(db_dict)
    ts_sorted = sorted(ts_db_dict.iterkeys(), reverse=True)

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


def get_keys_for_camelot_number(camelot_number):
    if camelot_number is None:
        return []
    key_minor = reverse_camelot_dict[str(camelot_number) + "A"]
    key_major = reverse_camelot_dict[str(camelot_number) + "B"]
    return [key_minor, key_major]


def get_relative_camelot_key(cam_num, offset):
    return ((cam_num + offset - 1) % 12) + 1


def matches_bpm_filter(filter_bpm, bpm_range, bpm):
    for sub_bpm in [int(round(bpm / 2.0)), bpm, int(round(bpm * 2.0))]:
        if sub_bpm >= filter_bpm - bpm_range and sub_bpm <= filter_bpm + bpm_range:
            return True
    return False


def update_db_clips(valid_alc_files, db_dict, force_alc=False, force_als=False):
    print("update_db_clips")
    for f in valid_alc_files:
        record = db_dict[f]
        f_ts = os.path.getmtime(f)
        # Get the first clip for key/update purposes from both alc and als
        if is_alc_file(f) or is_als_file(f):
            if force_alc or record.get("alc_ts") != f_ts:
                record["clip"] = get_audioclip_from_alc(f)
                record["alc_ts"] = f_ts
                print("Updated clip:", f)
        # If it's an als file, get the "clips" as well
        if is_als_file(f):
            if force_als or record.get("als_ts") != f_ts:
                record["clips"] = get_audioclips_from_als(f)
                record["als_ts"] = f_ts
                print("Updated clips:", f)


def update_db_clips_safe():
    db_dict = read_db_file()
    valid_alc_files = get_valid_alc_files(db_dict)
    update_db_clips(valid_alc_files, db_dict)
    write_db_file(db_dict)


def get_artist_and_track(filename):
    delimiter = u" - "
    split = os.path.splitext(filename)[0].split(delimiter)
    if len(split) == 1:
        return u"", split[0]
    elif len(split) == 2:
        return split[0], split[1]
    else:
        return split[0], delimiter.join(split[1:])


def get_sample_value_as_unicode(sample):
    """
    Some of the clip "sample" are unicode and some are not.
    This is an old function from before I understood everything.
    This is a way to get a string value as a unicode value.
    """
    if not isinstance(sample, unicode):
        # TODO(peter): I think just unicode(sample) would also work, but this is more explicit.
        # I've actually confirmed that the non-unicode sample values are all pure ascii.
        sample = sample.decode("utf-8")
    return sample


def get_sample_unicode(record):
    if "clip" not in record:
        return None
    sample = record["clip"]["sample"]
    return get_sample_value_as_unicode(sample)


def get_export_sample_path(f, sample_ext, target_path):
    f_base, _ = os.path.splitext(f)
    return os.path.join(target_path, f_base + sample_ext)


def get_existing_rekordbox_sample(record, sample_key):
    try:
        sample = record[sample_key]
        if os.path.isfile(sample):
            return sample
    except:
        pass
    return None


def get_list_name_to_file(path):
    files = [os.path.join(path, f) for f in os.listdir(path)]
    name_to_file = {}
    for f in files:
        if not os.path.isfile(f):
            continue
        name, ext = os.path.splitext(os.path.basename(f))
        if ext in (".txt", "") and not name.startswith("."):
            name_to_file[name] = f
    return name_to_file


def get_song_in_db(s, db_dict):
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


def get_list_from_file(filename, db_dict):
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


def update_with_rekordbox_history(db_dict, history_filename):
    # get date from filename
    p_filename = re.compile(r"HISTORY (\d+)-(\d+)-(\d+)\.txt")
    p_filename_paren = re.compile(r"HISTORY (\d+)-(\d+)-(\d+) \((\d+)\)\.txt")
    m_filename = p_filename.match(os.path.basename(history_filename))
    m_filename_paren = p_filename_paren.match(os.path.basename(history_filename))
    if m_filename_paren:
        year = int(m_filename_paren.group(1))
        month = int(m_filename_paren.group(2))
        day = int(m_filename_paren.group(3))
        paren_num = int(m_filename_paren.group(4))
    elif m_filename:
        year = int(m_filename.group(1))
        month = int(m_filename.group(2))
        day = int(m_filename.group(3))
        paren_num = None
    else:
        return
    date_ts = get_ts_for(year, month, day)
    if paren_num is not None:
        date_ts += 1000.0 * paren_num

    p_line = re.compile(r"\d+\t(.*)\t([^\[]*) \[.*$")
    with io.open(history_filename, encoding="utf-16le") as h:
        for index, line in enumerate(h.readlines()[1:]):
            m = p_line.match(line)
            if m:
                stamp_song(db_dict, date_ts, index, m.group(1), m.group(2))
            else:
                print("{}: failed to match: {}".format(history_filename, line))


def stamp_song(db_dict, date_ts, index, artist, title):
    alc_filename = u"{} - {}".format(artist.strip(), title.strip())
    _, f = get_song_in_db(alc_filename, db_dict)
    if f is None:
        print("Failure to stamp: {}".format(alc_filename))
        return
    record = db_dict[f]
    ts_to_write = date_ts + index
    add_ts(record, ts_to_write)


def generate_lists(output_path=COLLECTION_FOLDER):
    db_dict = read_db_file()
    files = get_rekordbox_files(db_dict)

    def write_files(filename, alc_filenames_to_write):
        with io.open(
            os.path.join(output_path, filename), "w", encoding="utf-8"
        ) as outfile:
            for f in alc_filenames_to_write:
                f_print = os.path.splitext(f)[0]
                outfile.write(u"{}\n".format(f_print))

    write_files("date_or_add.txt", generate_date_plus_alc(files, db_dict))
    write_files("add.txt", generate_alc(files, db_dict))
    write_files("name.txt", files)
    write_files("num.txt", generate_num(files, db_dict))
    write_files("sets.txt", generate_sets(files, db_dict))
