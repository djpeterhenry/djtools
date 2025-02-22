#!/usr/bin/env python

from __future__ import print_function

import ableton_aid as aa
import export_rekordbox
import argh
import os
import sys
from collections import defaultdict
import difflib
import re
import pprint


def add_bpms():
    db_dict = aa.read_db_file()
    alc_files = aa.get_ableton_files()
    for filename in alc_files:
        if db_dict.has_key(filename):
            continue

        print(filename)
        bpm = aa.get_int("BPM: ")
        if bpm is None:
            print("Stopping and saving...")
            break

        # record the result in the database
        new_record = {"bpm": bpm, "tags": [], "key": ""}
        db_dict[filename] = new_record
        print("Inserted: " + str(new_record))
    aa.write_db_file(db_dict)


def add_keys():
    db_dict = aa.read_db_file()
    alc_file_set = set(aa.get_ableton_files())
    for filename, record in db_dict.iteritems():
        if filename not in alc_file_set:
            continue
        # print ('considering:', filename)
        key = record["key"]
        if len(key) == 0 or key[-1] == "?":
            filepath = os.path.abspath(filename)
            new_key = aa.get_key_from_alc(filepath)
            print("new_key: " + new_key)
            if new_key is None:
                continue
            new_record = record
            new_record["key"] = new_key
            db_dict[filename] = new_record
        else:
            pass
            # print ('had key:', key)
    # Write the database only once at the end.
    # If you ever need to batch process the whole library again (heaven forbid) change this.
    aa.write_db_file(db_dict)


def edit_bpm(edit_filename):
    """"""
    assert os.path.isfile(edit_filename)
    print(edit_filename)
    db_dict = aa.read_db_file()
    bpm = None
    if db_dict.has_key(edit_filename):
        record = db_dict[edit_filename]
        bpm = record["bpm"]
    bpm = aa.get_int("BPM [%s]: " % bpm)
    if bpm is None:
        print("Aborting single edit")
        sys.exit(1)
    new_record = record
    new_record["bpm"] = bpm
    db_dict[edit_filename] = new_record
    print("Inserted: " + str(new_record))
    aa.write_db_file(db_dict)


def rename_tag(tag_old, tag_new):
    db_dict = aa.read_db_file()
    for _, record in sorted(db_dict.iteritems()):
        tags = record["tags"]
        tags = [x if (x != tag_old) else tag_new for x in tags]
        record["tags"] = tags
    aa.write_db_file(db_dict)


def list_tags():
    db_dict = aa.read_db_file()
    files = aa.get_rekordbox_files(db_dict)
    tag_to_count = defaultdict(int)
    for f in files:
        record = db_dict[f]
        tags = record["tags"]
        for tag in tags:
            tag_to_count[tag] += 1
    for tag, count in tag_to_count.iteritems():
        print(tag, ":", count)


def list_missing():
    missing = aa.get_missing()
    for f in missing:
        print(f)


def transfer_missing():
    db_dict = aa.read_db_file()
    alc_file_set = set(aa.get_ableton_files())
    alc_file_list = list(alc_file_set)
    missing = aa.get_missing()
    for f in missing:
        record = db_dict[f]
        ts_list = aa.get_ts_list(record)
        ts_len = len(ts_list)
        print(f, "plays:", ts_len)

        close = difflib.get_close_matches(f, alc_file_list, cutoff=0.3, n=10)
        for index, other in enumerate(close):
            print(index, ":", other)

        choice = aa.get_int("Choice (-1 explicit delete):")
        if choice is not None:
            if choice == -1:
                del db_dict[f]
                aa.write_db_file(db_dict)
            else:
                try:
                    target = close[choice]
                except KeyError:
                    continue
                target_record = db_dict[target]
                target_ts_list = aa.get_ts_list(target_record)
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
                aa.write_db_file(db_dict)


def print_records():
    db_dict = aa.read_db_file()
    for filename, record in db_dict.iteritems():
        print(filename + " " + str(record))


def print_pretty(output_file):
    db_dict = aa.read_db_file()
    with open(output_file, "w") as f:
        for filename, record in sorted(db_dict.iteritems()):
            print("---", file=f)
            pprint.pprint(filename, f)
            pprint.pprint(record, f)


def print_key_frequency():
    db_dict = aa.read_db_file()
    alc_file_set = set(aa.get_ableton_files())
    key_frequency = {}
    for filename, record in sorted(db_dict.iteritems()):
        if filename not in alc_file_set:
            continue
        key = record["key"]
        cam_key = aa.get_camelot_key(key)
        if cam_key is None:
            continue
        key_key = aa.reverse_camelot_dict[cam_key]
        if key_key not in key_frequency:
            key_frequency[key_key] = 0
        key_frequency[key_key] = key_frequency[key_key] + 1
    # sort by count
    by_count = []
    for key, count in sorted(key_frequency.iteritems()):
        by_count.append((count, key))
    by_count.sort()
    by_count.reverse()
    for count, key in by_count:
        print("%4s - %3s: %d" % (key, aa.get_camelot_key(key), count))


def print_xml(alc_filename):
    assert os.path.isfile(alc_filename)
    print(aa.alc_to_str(alc_filename))


def print_audioclip(alc_filename):
    assert os.path.isfile(alc_filename)
    print(aa.get_audioclip_from_alc(alc_filename))


def print_audioclips(als_filename):
    assert os.path.isfile(als_filename)
    print(aa.get_audioclips_from_als(als_filename))


def rekordbox_xml(rekordbox_filename):
    export_rekordbox.export_rekordbox_xml(rekordbox_filename=rekordbox_filename)


def test_lists():
    db_dict = aa.read_db_file()
    name_to_file = aa.get_list_name_to_file(aa.LISTS_FOLDER)
    for name, list_file in sorted(name_to_file.iteritems()):
        print("---", name)
        for display, f in aa.get_list_from_file(list_file, db_dict):
            if f is None:
                print(display)


def cue_to_tracklist(cue_filename, tracklist_filename):
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
    p_title = re.compile(r'\tTITLE "(.*) \[')
    p_performer = re.compile(r'\tPERFORMER "(.*)"')
    p_index = re.compile(r"\tINDEX 01 (.*)")
    with open(cue_filename) as f:
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
    with open(tracklist_filename, "w") as w:
        for t in tracks:
            w.write("{}\n".format(str(t)))


def generate_lists(output_path):
    aa.generate_lists(output_path)


def fix_alc_ts():
    # THIS WAS BRUTAL AND WRONG
    # old_alc_ts is the one you want for ordering and display if it exists.
    # There are alc files with a modified timestamp before old_alc_ts.
    # The value of "alc_ts" always matches the file timestamp, but may be newer than
    # the corresponding "old_alc_ts".
    # So for ordering, use "get_alc_ts",
    # but for checking whether clips need to be updated, check the "alc_ts" record value directly.
    db_dict = aa.read_db_file()
    # Update alc_ts
    for filename, record in db_dict.iteritems():
        alc_ts = aa.get_alc_ts(record)
        if not alc_ts > 0:
            print(filename)
        record["alc_ts"] = alc_ts
        try:
            del record["old_alc_ts"]
        except KeyError:
            pass
    aa.write_db_file(db_dict)


def remove_old_fields():
    # Ran this successfully and leaving just as a reference
    db_dict = aa.read_db_file()

    def del_field(record, field):
        try:
            del record[field]
        except KeyError:
            pass

    for filename, record in db_dict.iteritems():
        del_field(record, "mp3_sample")
        del_field(record, "rekordbox_sample")
    aa.write_db_file(db_dict)


# todo: kill eventually
def test_filenames():
    db_dict = aa.read_db_file()
    for filename, record in db_dict.iteritems():
        assert type(filename) == unicode
        assert os.path.isfile(filename)


# todo: kill eventually
def test_unicode_clip_samples():
    db_dict = aa.read_db_file()
    for filename, record in db_dict.iteritems():
        clip_sample = record["clip"]["sample"]
        if type(clip_sample) == unicode:
            print(clip_sample)
        else:
            if not all(0 <= ord(c) <= 127 for c in clip_sample):
                print(clip_sample)
        assert os.path.isfile(clip_sample)


def convert_keys_to_unicode():
    # I ran this successfully
    db_dict = aa.read_db_file()
    new_dict = {}
    for filename, record in db_dict.iteritems():
        assert os.path.isfile(filename)
        new_key = filename.decode("utf-8")
        new_dict[new_key] = record
        print(repr(new_key))
    aa.write_db_file(new_dict)


def test_db_json():
    db_dict = aa.read_db_file()
    # write as json
    aa.write_db_json(db_dict)
    db_dict_json = aa.read_db_json()

    # They produce exactly the same in-memory db_dict!
    assert db_dict == db_dict_json


if __name__ == "__main__":
    parser = argh.ArghParser()
    parser.add_commands(
        [
            add_bpms,
            add_keys,
            edit_bpm,
            rename_tag,
            list_tags,
            list_missing,
            transfer_missing,
            print_records,
            print_pretty,
            print_key_frequency,
            print_xml,
            print_audioclip,
            print_audioclips,
            rekordbox_xml,
            test_lists,
            cue_to_tracklist,
            generate_lists,
            test_filenames,
            test_unicode_clip_samples,
            test_db_json,
        ]
    )
    parser.dispatch()
