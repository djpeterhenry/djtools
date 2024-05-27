#!/usr/bin/env python
# Created on May 14, 2009
from __future__ import print_function

# Mack input be raw_input on python2
try: input = raw_input
except NameError: pass

import sys
import os
import cPickle
import shutil
import re
import random
import subprocess
import gzip
import codecs
import xml.etree.ElementTree as ET
import time
import datetime
import difflib
from collections import defaultdict
import argparse
import shutil

import export_rekordbox

from tag import Tag


ABLETON_EXTENSIONS = [".alc", ".als"]
SAMPLE_EXTENSIONS = [".mp3", ".m4a", ".wav", ".aiff", ".flac"]
ALL_EXTENSIONS = ABLETON_EXTENSIONS + SAMPLE_EXTENSIONS

REKORDBOX_SAMPLE_KEY = "rekordbox_sample"
REKORDBOX_LOCAL_SAMPLE_KEY = "rekordbox_local_sample"


def get_ts_for(year, month, day):
    return time.mktime(datetime.date(year, month, day).timetuple())


# We use "old_alc_ts" for files with "alc_ts" before this datetime.
# I totally forget how I made that all work, but it seems to.
OLD_ALC_TS_CUTOFF = get_ts_for(2016, 6, 12)

# When I moved to SF
SF_TS = get_ts_for(2015, 7, 1)

MP3_SAMPLE_PATH = u"/Volumes/music/mp3_samples/"

LISTS_FOLDER = "/Users/peter/github/djpeterhenry.github.io/lists"

COLLECTION_FOLDER = "/Users/peter/github/djpeterhenry.github.io/collection"

ACTIVE_LIST = "/Users/peter/github/djtools/active_list.txt"


def is_valid(filepath):
    return os.path.exists(filepath) or os.path.islink(filepath)


def get_int(prompt_string):
    ui = input(prompt_string)
    try:
        return int(ui)
    except ValueError:
        return None


def is_ableton_file(filename):
    ext = os.path.splitext(filename)[1]
    return ext in ALL_EXTENSIONS


def get_ableton_files():
    walk_result = os.walk(".")
    result = []
    for dirpath, _, filenames in walk_result:
        for f in filenames:
            # hack to remove './' for compatibility
            filename = os.path.join(dirpath, f)[2:]
            if is_ableton_file(filename):
                result.append(filename)
    return sorted(result, key=str.lower)


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


def read_db_file(db_filename):
    db_dict = None
    if os.path.exists(db_filename):
        db_file = open(db_filename)
        try:
            db_dict = cPickle.load(db_file)
            # print ("Loaded: " + db_filename)
        except:
            print("Error opening pickle file...")
            sys.exit(1)
    else:
        print("Will create new: " + db_filename)
        db_dict = {}
    return db_dict


def write_db_file(db_filename, db_dict):
    # very first thing make a backup
    for x in xrange(int(1e6)):
        backup_file = "aa_db.{:03}.txt".format(x)
        if os.path.exists(backup_file):
            continue
        break
    try:
        shutil.copyfile(db_filename, backup_file)
        print("created: {}".format(backup_file))
    except:
        print("failed backup: {} -> {}".format(db_filename, backup_file))
    with open(db_filename, "w") as db_file:
        cPickle.dump(db_dict, db_file)
    print("Wrote: " + db_filename)


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


def get_missing(db_filename):
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    result = []
    for filename, _ in iter(sorted(db_dict.iteritems())):
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


def add_ts(record, ts):
    try:
        current = record["ts_list"]
        if ts not in current:
            current.append(ts)
    except KeyError:
        record["ts_list"] = [ts]


def get_ts_list(record):
    try:
        ts_list = record["ts_list"]
    except:
        ts_list = []
    return ts_list


def get_ts_list_after(record, ts):
    ts_list = get_ts_list(record)
    return [x for x in ts_list if x >= ts]


def get_last_ts(record):
    ts_list = get_ts_list(record)
    try:
        return sorted(ts_list)[-1]
    except IndexError:
        return 0


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
        ts_list = (
            get_ts_list_after(record, ts_after) if ts_after else get_ts_list(record)
        )
        num = len(ts_list)
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


def assert_exists(filename):
    if not is_valid(filename):
        raise ValueError("File does not exist: {}".format(filename))


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


def update_db_clips_safe(db_filename):
    db_dict = read_db_file(db_filename)
    valid_alc_files = get_valid_alc_files(db_dict)
    update_db_clips(valid_alc_files, db_dict)
    write_db_file(db_filename, db_dict)


def get_artist_and_track(filename):
    delimiter = " - "
    split = os.path.splitext(filename)[0].split(delimiter)
    if len(split) == 1:
        return "", split[0]
    elif len(split) == 2:
        return split[0], split[1]
    else:
        return split[0], delimiter.join(split[1:])


def get_sample_value_as_unicode(sample):
    """This works around some of my samples being unicode and some not.  Kind of"""
    # Ok, this seems to work to get all the samples to unicode...
    # Still not sure why some samples (Take Over Control Acapella) are unicode
    if not isinstance(sample, unicode):
        sample = sample.decode("utf-8")
    return sample


def get_sample_unicode(record):
    if "clip" not in record:
        return None
    sample = record["clip"]["sample"]
    return get_sample_value_as_unicode(sample)


def get_export_sample_path(f, sample_ext, target_path):
    f_base, _ = os.path.splitext(f.decode("utf-8"))
    return os.path.join(target_path, f_base + sample_ext).encode("utf-8")


def get_existing_rekordbox_sample(record, sample_key):
    try:
        sample = record[sample_key]
        if is_valid(sample):
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
    p_timestamp = re.compile(ur"\[[\d:]+\] (.*)")
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


####################################
# actions start here


def action_add(args):
    db_dict = read_db_file(args.db_filename)
    alc_files = get_ableton_files()
    for filename in alc_files:
        print(filename)
        if db_dict.has_key(filename):
            # print (db_dict[filename])
            continue

        ui = input("BPM: ")
        try:
            bpm = int(ui)
        except ValueError:
            print("Stopping and saving...")
            break

        # record the result in the database
        new_record = {"bpm": bpm, "tags": [], "key": ""}
        db_dict[filename] = new_record
        print("Inserted: " + str(new_record))
    write_db_file(args.db_filename, db_dict)


def action_edit(args):
    # TODO(peter): clean up this shitty old function
    assert_exists(args.edit_filename)
    print(args.edit_filename)
    db_dict = read_db_file(args.db_filename)
    bpm = None
    if db_dict.has_key(args.edit_filename):
        record = db_dict[args.edit_filename]
        bpm = record["bpm"]
    ui = input("BPM [%s]: " % bpm)
    if ui:
        try:
            bpm = int(ui)
        except ValueError:
            print("Aborting single edit")
            sys.exit(1)
    new_record = record
    new_record["bpm"] = bpm
    db_dict[args.edit_filename] = new_record
    print("Inserted: " + str(new_record))
    write_db_file(args.db_filename, db_dict)


def action_add_missing_keys(args):
    db_dict = read_db_file(args.db_filename)
    alc_file_set = set(get_ableton_files())
    for filename, record in db_dict.iteritems():
        if filename not in alc_file_set:
            continue
        # print ('considering:', filename)
        key = record["key"]
        if len(key) == 0 or key[-1] == "?":
            filepath = os.path.abspath(filename)
            new_key = get_key_from_alc(filepath)
            print("new_key: " + new_key)
            if new_key is None:
                continue
            new_record = record
            new_record["key"] = new_key
            db_dict[filename] = new_record
            # write every time...this may take a while
            write_db_file(args.db_filename, db_dict)
        else:
            pass
            # print ('had key:', key)


def action_print(args):
    db_dict = read_db_file(args.db_filename)
    for filename, record in db_dict.iteritems():
        print(filename + " " + str(record))


def action_key_frequency(args):
    db_dict = read_db_file(args.db_filename)
    alc_file_set = set(get_ableton_files())
    key_frequency = {}
    for filename, record in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        key = record["key"]
        cam_key = get_camelot_key(key)
        if cam_key is None:
            continue
        key_key = reverse_camelot_dict[cam_key]
        if key_key not in key_frequency:
            key_frequency[key_key] = 0
        key_frequency[key_key] = key_frequency[key_key] + 1
    # sort by count
    by_count = []
    for key, count in iter(sorted(key_frequency.iteritems())):
        by_count.append((count, key))
    by_count.sort()
    by_count.reverse()
    for count, key in by_count:
        print("%4s - %3s: %d" % (key, get_camelot_key(key), count))


def action_rename_tag(args):
    db_dict = read_db_file(args.db_filename)
    for _, record in iter(sorted(db_dict.iteritems())):
        tags = record["tags"]
        tags = [x if (x != args.tag_old) else args.tag_new for x in tags]
        record["tags"] = tags
    write_db_file(args.db_filename, db_dict)


def action_list_tags(args):
    db_dict = read_db_file(args.db_filename)
    files = get_rekordbox_files(db_dict)
    tag_to_count = defaultdict(int)
    for f in files:
        record = db_dict[f]
        tags = record["tags"]
        for tag in tags:
            tag_to_count[tag] += 1
    for tag, count in tag_to_count.iteritems():
        print(tag, ":", count)


def action_list_missing(args):
    missing = get_missing(args.db_filename)
    for f in missing:
        print(f)


def action_transfer_ts(args):
    db_dict = read_db_file(args.db_filename)
    alc_file_set = set(get_ableton_files())
    alc_file_list = list(alc_file_set)
    missing = get_missing(args.db_filename)
    for f in missing:
        record = db_dict[f]
        ts_list = get_ts_list(record)
        ts_len = len(ts_list)
        if ts_len == 0:
            continue

        print(f, "plays:", ts_len)

        close = difflib.get_close_matches(f, alc_file_list, cutoff=0.3, n=10)
        for index, other in enumerate(close):
            print(index, ":", other)

        choice = get_int("Choice (-1 explicit delete):")
        if choice is not None:
            if choice == -1:
                del db_dict[f]
                write_db_file(args.db_filename, db_dict)
            else:
                try:
                    target = close[choice]
                except KeyError:
                    continue
                target_record = db_dict[target]
                target_ts_list = get_ts_list(target_record)
                both_ts_list = sorted(list(set(target_ts_list + ts_list)))
                target_record["ts_list"] = both_ts_list
                print(
                    "ts_list:",
                    ts_list,
                    "target_ts_list:",
                    target_ts_list,
                    "both_ts_list:",
                    both_ts_list,
                )
                # also transfer tags
                for old_tag in record["tags"]:
                    if old_tag not in target_record["tags"]:
                        target_record["tags"].append(old_tag)
                # also transfer key if not already present
                old_key = target_record.get("key")
                key = record.get("key")
                if key and not old_key:
                    target_record["key"] = key
                # delete old record
                del db_dict[f]
                write_db_file(args.db_filename, db_dict)


def action_export_sample_database(args):
    db_dict = read_db_file(args.db_filename)
    alc_file_set = set(get_ableton_files())
    sample_db = {}
    for filename, _ in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        record = db_dict[filename]
        sample_filepath = get_sample(record)
        if not sample_filepath:
            continue
        sample_filename = os.path.basename(sample_filepath)
        record["pretty_name"] = os.path.splitext(filename)[0]
        sample_db[sample_filename] = record
    write_db_file(args.sample_db_filename, sample_db)


def action_print_xml(args):
    assert_exists(args.alc_filename)
    print(alc_to_str(args.alc_filename))


def action_print_audioclip(args):
    assert_exists(args.alc_filename)
    print(get_audioclip_from_alc(args.alc_filename))


def action_print_audioclips(args):
    assert_exists(args.als_filename)
    print(get_audioclips_from_als(args.als_filename))


def action_export_rekordbox_local(args):
    export_rekordbox.export_rekordbox_xml(
        db_filename=args.db_filename, rekordbox_filename=args.rekordbox_filename
    )


def action_export_rekordbox_xml(args):
    export_rekordbox.export_rekordbox_xml(
        db_filename=args.db_filename,
        rekordbox_filename=args.rekordbox_filename,
        sample_root_path=args.sample_root_path,
    )


def action_export_mp3_samples(args):
    db_dict = read_db_file(args.db_filename)
    files = get_ableton_files()
    for f in files:
        record = db_dict[f]
        if not use_for_rekordbox(record):
            continue
        print("Starting", f)
        sample = get_sample_unicode(record)
        if sample is None:
            print("Failed to get sample for {}".format(f))
            continue
        _, sample_ext = os.path.splitext(sample)
        # convert all but mp3 and m4a
        if sample_ext.lower() in (".mp3", ".m4a"):
            # copy these
            target = get_export_sample_path(f, sample_ext, MP3_SAMPLE_PATH)
            if not os.path.exists(target):
                shutil.copy(sample, target)
        else:
            # convert these
            target = get_export_sample_path(f, ".mp3", MP3_SAMPLE_PATH)
            if not os.path.exists(target):
                cmd = [
                    "ffmpeg",
                    "-i",
                    sample,
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "320k",
                    target,
                ]
                subprocess.check_call(cmd)
        assert os.path.exists(target)
        os.utime(target, (time.time(), get_alc_ts(record)))
        record["mp3_sample"] = target.decode("utf-8")
    write_db_file(args.db_filename, db_dict)


def action_test_lists(args):
    db_dict = read_db_file(args.db_filename)
    name_to_file = get_list_name_to_file(LISTS_FOLDER)
    for name, list_file in sorted(name_to_file.iteritems()):
        print("---", name)
        for display, f in get_list_from_file(list_file, db_dict):
            if f is None:
                print(display)


def update_with_rekordbox_history(db_dict, history_filename):
    # get date from filename
    p_filename = re.compile(ur"HISTORY (\d+)-(\d+)-(\d+)\.txt")
    p_filename_paren = re.compile(ur"HISTORY (\d+)-(\d+)-(\d+) \((\d+)\)\.txt")
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
    # fun print of those later:
    if False:
        for f, record in db_dict.iteritems():
            last_ts = get_alc_or_last_ts(record)
            if last_ts > date_ts:
                print(f)
        return

    with codecs.open(history_filename, encoding="utf-16le") as h:
        for index, line in enumerate(h.readlines()[1:]):
            p_line = re.compile(ur"\d+\t(.*)\t([^\[]*) \[.*$")
            m = p_line.match(line)
            if m:
                stamp_song(db_dict, date_ts, index, m.group(1), m.group(2))
            else:
                print("{}: failed to match: {}".format(history_filename, line))


def stamp_song(db_dict, date_ts, index, artist, title):
    s = u"{} - {}".format(artist.strip(), title.strip())
    s_str = s.encode("utf8")
    _, f = get_song_in_db(s_str, db_dict)
    if f is None:
        print("Failure to stamp: {}".format(s_str))
        return
    record = db_dict[f]
    ts_to_write = date_ts + index
    add_ts(record, ts_to_write)
    # print ('{}:{}'.format(f, ts_to_write))


def action_rekordbox_history(args):
    export_rekordbox.export_rekordbox_history(args.db_filename)


def action_cue_to_tracklist(args):
    class Track(object):
        def __init__(self):
            self.artist = None
            self.song = None
            self.index = None

        def __str__(self):
            return "[{}] {} - {}".format(self.index, self.artist, self.song)

    tracks = []
    track = Track()
    # assume [key] on all tracks?
    p_title = re.compile(ur'\tTITLE "(.*) \[')
    p_performer = re.compile(ur'\tPERFORMER "(.*)"')
    p_index = re.compile(ur"\tINDEX 01 (.*)")
    with open(args.cue_filename) as f:
        for line in f.readlines():
            m_title = p_title.search(line)
            m_performer = p_performer.search(line)
            m_index = p_index.search(line)
            if m_title:
                track.song = m_title.group(1).strip()
            elif m_performer:
                track.artist = m_performer.group(1).strip()
            elif m_index:
                track.index = m_index.group(1).strip()
                tracks.append(track)
                track = Track()
    # for t in tracks:
    #     print (t)
    with open(args.tracklist_filename, "w") as w:
        for t in tracks:
            w.write("{}\n".format(str(t)))


def generate_lists(db_filename, output_path=COLLECTION_FOLDER):
    db_dict = read_db_file(db_filename)
    files = get_rekordbox_files(db_dict)

    def write_files(filename, files_to_write):
        with open(os.path.join(output_path, filename), "w") as outfile:
            for f in files_to_write:
                f_print = os.path.splitext(f)[0]
                outfile.write("{}\n".format(f_print))

    write_files("date_or_add.txt", generate_date_plus_alc(files, db_dict))
    write_files("add.txt", generate_alc(files, db_dict))
    write_files("name.txt", files)
    write_files("num.txt", generate_num(files, db_dict))
    sets = generate_sets(files, db_dict)
    write_files("sets.txt", sets)


def action_generate_lists(args):
    generate_lists(args.db_filename, args.output_path)


def action_touch_list(args):
    db_dict = read_db_file(args.db_filename)
    date_ts = get_ts_for(args.date[0], args.date[1], args.date[2])
    for counter, (_, f) in enumerate(get_list_from_file(args.list_file, db_dict)):
        if f is None:
            continue
        record = db_dict[f]
        ts_to_add = date_ts + counter
        add_ts(record, ts_to_add)
    write_db_file(args.db_filename, db_dict)


def action_find_samples(args):
    sample_dict = export_rekordbox.find_existing_samples(args.root_path)
    print(sample_dict)
    print("num_samples: {}".format(len(sample_dict)))


def action_relative_path(args):
    result = export_rekordbox.relative_path(args.path_from, args.path_to)
    print(result)


###########
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("db_filename")
    subparsers = parser.add_subparsers()

    subparsers.add_parser("addbpm").set_defaults(func=action_add)
    subparsers.add_parser("addkey").set_defaults(func=action_add_missing_keys)

    p_edit = subparsers.add_parser("edit")
    p_edit.add_argument("edit_filename")
    p_edit.set_defaults(func=action_edit)

    # TODO: pick one?  print is raw, list is pretty
    # This should match listing orders in GUI, be pretty, and be the new dump
    subparsers.add_parser("print").set_defaults(func=action_print)

    subparsers.add_parser("keyfreq").set_defaults(func=action_key_frequency)

    p_rename = subparsers.add_parser("rename_tag")
    p_rename.add_argument("tag_old")
    p_rename.add_argument("tag_new")
    p_rename.set_defaults(func=action_rename_tag)

    subparsers.add_parser("list_tags").set_defaults(func=action_list_tags)

    subparsers.add_parser("list_missing").set_defaults(func=action_list_missing)
    subparsers.add_parser("transfer_ts").set_defaults(func=action_transfer_ts)

    p_export = subparsers.add_parser("export_sample_db")
    p_export.add_argument("sample_db_filename")
    p_export.set_defaults(func=action_export_sample_database)

    p_xml = subparsers.add_parser("print_xml")
    p_xml.add_argument("alc_filename")
    p_xml.set_defaults(func=action_print_xml)

    p_audioclip = subparsers.add_parser("print_audioclip")
    p_audioclip.add_argument("alc_filename")
    p_audioclip.set_defaults(func=action_print_audioclip)

    p_audioclip = subparsers.add_parser("print_audioclips")
    p_audioclip.add_argument("als_filename")
    p_audioclip.set_defaults(func=action_print_audioclips)

    p_rekordbox = subparsers.add_parser("export_rekordbox_local")
    p_rekordbox.add_argument("rekordbox_filename")
    p_rekordbox.set_defaults(func=action_export_rekordbox_local)

    p_rekordbox = subparsers.add_parser("export_rekordbox_xml")
    p_rekordbox.add_argument("rekordbox_filename")
    p_rekordbox.add_argument("sample_root_path")
    p_rekordbox.set_defaults(func=action_export_rekordbox_xml)

    p_mp3_samples = subparsers.add_parser("export_mp3_samples")
    p_mp3_samples.set_defaults(func=action_export_mp3_samples)

    subparsers.add_parser("test_lists").set_defaults(func=action_test_lists)

    p_rekordbox_history = subparsers.add_parser("rekordbox_history")
    p_rekordbox_history.set_defaults(func=action_rekordbox_history)

    p_cue_to_tracklist = subparsers.add_parser("cue_to_tracklist")
    p_cue_to_tracklist.add_argument("cue_filename")
    p_cue_to_tracklist.add_argument("tracklist_filename")
    p_cue_to_tracklist.set_defaults(func=action_cue_to_tracklist)

    p_rekordbox_history = subparsers.add_parser("generate_lists")
    p_rekordbox_history.add_argument("output_path")
    p_rekordbox_history.set_defaults(func=action_generate_lists)

    p_touch_list = subparsers.add_parser("touch_list")
    p_touch_list.add_argument("list_file")
    p_touch_list.add_argument("date", type=int, nargs=3)
    p_touch_list.set_defaults(func=action_touch_list)

    p_find_samples = subparsers.add_parser("find_samples")
    p_find_samples.add_argument("root_path")
    p_find_samples.set_defaults(func=action_find_samples)

    p_relative_path = subparsers.add_parser("relative_path")
    p_relative_path.add_argument("path_from")
    p_relative_path.add_argument("path_to")
    p_relative_path.set_defaults(func=action_relative_path)

    return parser.parse_args()


def main(args):
    args.func(args)


if __name__ == "__main__":
    main(parse_args())
