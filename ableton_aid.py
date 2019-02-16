#!/usr/bin/env python
'''
Created on May 14, 2009

@author: phenry
'''

from __future__ import print_function

import sys
import os
import glob
import stat
import cPickle
import shutil
import re
import random
import subprocess
import gzip
import xml.etree.ElementTree as ET
import json
import time
import unicodedata
import datetime
import difflib
import urllib
from collections import defaultdict
import argparse

# import mutagen
try:
    from mutagen.mp3 import MP3
    from mutagen.easyid3 import EasyID3
except:
    pass


ABLETON_EXTENSIONS = ['.alc', '.als']
SAMPLE_EXTENSIONS = ['.mp3', '.m4a', '.wav', '.aiff', '.flac']
ALL_EXTENSIONS = ABLETON_EXTENSIONS + SAMPLE_EXTENSIONS


def get_int(prompt_string):
    ui = raw_input(prompt_string)
    try:
        return int(ui)
    except ValueError:
        return None


def is_ableton_file(filename):
    ext = os.path.splitext(filename)[1]
    return ext in ALL_EXTENSIONS


def get_ableton_files():
    walk_result = os.walk('.')
    result = []
    for dirpath, dirnames, filenames in walk_result:
        for f in filenames:
            # hack to remove './' for compatibility
            filename = os.path.join(dirpath, f)[2:]
            if is_ableton_file(filename):
                result.append(filename)
    return result


def get_ts_list(record):
    try:
        ts_list = record['ts_list']
    except:
        ts_list = []
    return ts_list


def get_base_filename(filename, record):
    pre_padding = ' ' * 2
    divider = ' - '
    file, ext = os.path.splitext(filename)
    result = file
    if 'pretty_name' in record:
        result = record['pretty_name']
    # TODO(peter): what were you trying to do here?
    # Interesting idea but supersceded by exporting sample db
    if False and ext in ['.mp3', '.flac']:
        audio = EasyID3(filename)
        artist = ""
        try:
            artist = audio['artist'][0]
        except KeyError:
            pass
        song = ""
        try:
            song = audio['title'][0]
        except KeyError:
            pass
        if len(artist) > 0:
            result = '%s%s%s' % (artist, divider, song)
        elif len(song) > 0:
            result = song
    # add extension:
    if ext not in ['.alc']:
        result = '%s (%s)' % (result, ext[1:].upper())
    # add vocal:
    if 'vocal' in record['tags']:
        result = result + ' [Vocal]'
    return result


def get_base_filename_with_bpm_and_key(filename, record):
    base = get_base_filename(filename, record)
    return '%s [%s] [%s]' % (base, record['bpm'], record['key'])


def read_db_file(db_filename):
    db_dict = None
    if os.path.exists(db_filename):
        db_file = open(db_filename)
        try:
            db_dict = cPickle.load(db_file)
            #print ("Loaded: " + db_filename)
        except:
            print ("Error opening pickle file...")
            sys.exit(1)
    else:
        print ("Will create new: " + db_filename)
        db_dict = {}
    return db_dict


def write_db_file(db_filename, db_dict):
    db_file = open(db_filename, 'w')
    cPickle.dump(db_dict, db_file)
    print ("Wrote: " + db_filename)


def get_mp3_bpm(filename):
    audio = EasyID3(filename)
    bpm = None
    bpm_text = None
    try:
        bpm_text = audio['bpm'][0]
    except KeyError:
        pass
    if bpm_text is not None:
        try:
            bpm = int(bpm_text)
        except ValueError:
            pass
    return bpm


def get_valid_db_dict(db_filename):
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    # there is a better python way here:
    result = {}
    for filename, record in db_dict.iteritems():
        if filename not in alc_file_set:
            continue
        if 'x' in record['tags']:
            continue
        result[filename] = record
    return result


def print_pretty_files(file_list, db_dict):
    for filename in file_list:
        record = db_dict[filename]
        pretty_name = get_base_filename_with_bpm_and_key(filename, record)
        print (pretty_name)


def alc_to_str(alc_filename):
    with gzip.open(alc_filename, 'rb') as f:
        return f.read()


def alc_to_xml(alc_filename):
    return ET.fromstring(alc_to_str(alc_filename))


def get_audioclip_from_alc(alc_filename):
    xml_root = alc_to_xml(alc_filename)
    # just find the first AudioClip for now
    xml_clip = xml_root.find('.//AudioClip')
    if xml_clip is None:
        return None
    result = {}
    xml_warp_markers = xml_clip.find('WarpMarkers')
    result['warp_markers'] = []
    for marker in xml_warp_markers:
        result['warp_markers'].append(dict(sec_time=float(marker.get('SecTime')),
                                           beat_time=float(marker.get('BeatTime'))))
    xml_loop = xml_clip.find('Loop')
    result['loop_start'] = float(xml_loop.find('HiddenLoopStart').get('Value'))
    result['loop_end'] = float(xml_loop.find('HiddenLoopEnd').get('Value'))
    result['start'] = float(xml_clip.find('CurrentStart').get('Value'))
    # also sample info
    xml_fileref = xml_clip.find('SampleRef/FileRef')
    relative_path = os.path.join(
        '..', *[x.get('Dir') for x in xml_fileref.find('RelativePath')])
    sample_filepath = os.path.join(
        relative_path, xml_fileref.find('Name').get('Value'))
    if os.path.exists(sample_filepath):
        result['sample'] = sample_filepath
    else:
        print ('Sample failed: {}'.format(alc_filename))
    return result


def get_sample_from_xml(xml_root):
    sample_refs = xml_root.findall('.//SampleRef')
    # right now, just the first
    sample_ref = sample_refs[0]
    sample_filename = sample_ref.find('FileRef/Name').attrib['Value']
    sample_path_list = [x.attrib['Dir'] for x in sample_ref.findall(
        'FileRef/SearchHint/PathHint/RelativePathElement')]
    sample_file_folder = os.path.join('/', *sample_path_list)
    sample_file_fullpath = os.path.join(sample_file_folder, sample_filename)
    if os.path.exists(sample_file_fullpath):
        return sample_file_fullpath
    # for some reason, files can have an invalid path and still work??
    # it's just PathHints after all
    sample_file_folder = '/Users/peter/Music/Ableton/djpeterhenry/Samples/Imported'
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
    keyfinder_app = '/Applications/KeyFinder.app/Contents/MacOS/KeyFinder'
    command = '"%s" -f "%s"' % (keyfinder_app, sample_fullpath)
    result = subprocess.check_output(command, shell=True)
    return result


def get_key_from_alc(alc_filename):
    sample_file = get_sample_from_alc_file(alc_filename)
    return get_key_from_sample(sample_file)


def get_clips_from_als(als_filename):
    xml_root = alc_to_xml(als_filename)
    audio_clips = xml_root.findall('.//AudioClip')
    result = []
    for clip in audio_clips:
        name = clip.find('Name').attrib['Value']
        time = float(clip.attrib['Time'])
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
    camelot_list = ['Ab', 'B', 'Eb', 'Gb', 'Bb', 'Db', 'F', 'Ab',
                    'C', 'Eb', 'G', 'Bb', 'D', 'F', 'A', 'C',
                    'E', 'G', 'B', 'D', 'Gb', 'A', 'Db', 'E']
    initial_dict = {}
    reverse_dict = {}
    ab = ['A', 'B']
    for i, k in enumerate(camelot_list):
        camelot_name = str(i / 2 + 1) + ab[i % 2]
        if i % 2 == 0:
            k = k + 'm'
        initial_dict[k] = camelot_name
        reverse_dict[camelot_name] = k
    full_dict = initial_dict.copy()
    for k, c in initial_dict.iteritems():
        if len(k) > 1 and k[1] == 'b':
            key_char = k[0]
            key_ascii = ord(key_char)
            sharp_ascii = key_ascii - 1
            if sharp_ascii < ord('A'):
                sharp_ascii = ord('G')
            sharp_key = chr(sharp_ascii)
            minor_str = ''
            if len(k) == 3:
                minor_str = 'm'
            sharp_dict_entry = str(sharp_key) + '#' + minor_str
            full_dict[sharp_dict_entry] = c
    return full_dict, reverse_dict

# create global
camelot_dict, reverse_camelot_dict = generate_camelot_dict()


def get_camelot_key(key):
    if len(key) < 1:
        return None
    key = key[:1].upper() + key[1:]
    if key[-1] == '?':
        key = key[:-1]
    if camelot_dict.has_key(key):
        return camelot_dict[key]
    else:
        return None


def delete_key(record, key):
    try:
        del record[key]
    except KeyError:
        pass


def get_ts_for_file(file):
    try:
        return os.path.getmtime(file)
    except OSError as e:
        print (e)
        return None


def reveal_file(filename):
    command = ['open', '-R', filename]
    subprocess.call(command)


def get_missing(db_filename):
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    result = []
    for filename, record in iter(sorted(db_dict.iteritems())):
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


def get_files_by_num(files, db_dict):
    num_file_tuples = []
    for file in files:
        record = db_dict[file]
        num = -len(get_ts_list(record))
        num_file_tuples.append((num, file))
    num_file_tuples.sort()
    return [file for _, file in num_file_tuples]


def update_and_get_cache_values(filename):
    cache_filename = filename + '.cache.txt'
    try:
        cache_dict = cPickle.load(open(cache_filename))
    except:
        cache_dict = {}
    try:
        cache_m_time_alc = cache_dict['m_time_alc']
    except:
        cache_m_time_alc = None
    if cache_m_time_alc:
        m_time_alc = os.path.getmtime(filename)
        if cache_m_time_alc == m_time_alc:
            return cache_dict
    # must update file
    # for some reason this breaks when trying to print to terminal
    # print (u'updating: {}'.format(filename))
    m_time_alc = os.path.getmtime(filename)
    sample_file = get_sample_from_alc_file(filename)
    # print (u'sample_file: {}'.format(sample_file))
    m_time_sample = os.path.getmtime(sample_file)
    cache_dict['m_time_alc'] = m_time_alc
    cache_dict['sample_file'] = sample_file
    cache_dict['m_time_sample'] = m_time_sample
    cPickle.dump(cache_dict, open(cache_filename, 'w'))
    return cache_dict


def get_valid_alc_files(db_dict):
    alc_files = get_ableton_files()
    valid_alc_files = [
        filename for filename in alc_files if db_dict.has_key(filename)]
    valid_alc_files.sort(key=lambda s: s.lower())
    return valid_alc_files


def get_dict_file_cache(valid_alc_files):
    dict_file_cache = {}
    for file in valid_alc_files:
        cache_dict = update_and_get_cache_values(file)
        dict_file_cache[file] = cache_dict
    return dict_file_cache


def get_dict_date_sample(valid_alc_files, dict_file_cache):
    dict_date_sample = {}
    for file in valid_alc_files:
        cache_dict = dict_file_cache[file]
        dict_date_sample[file] = cache_dict['m_time_sample']
    return dict_date_sample


def generate_sample(valid_alc_files, dict_date_sample):
    date_file_tuples = []
    for file in valid_alc_files:
        m_time_sample = dict_date_sample[file]
        date_file_tuples.append((m_time_sample, file))
    date_file_tuples.sort()
    date_file_tuples.reverse()
    return [file for _, file in date_file_tuples]


def json_list_to_dict(json_filename):
    result = {}
    with open(json_filename) as json_file:
        json_list = json.load(json_file)
        for ts, filename in json_list:
            # filename is in unicode here...gotta encode it
            result[filename.encode('utf-8')] = ts
    return result


def get_dict_date_alc_json(valid_alc_files, dict_file_cache):
    # would like to use file date, but it's wrong and too new
    # examining filesystem, june 11 was when they all got updated
    magic_date = datetime.date(2016, 6, 12)
    magic_ts = time.mktime(magic_date.timetuple())
    json_filename = 'alc_dates.json'
    have_json_file = os.path.exists(json_filename)
    dict_date_alc = json_list_to_dict(json_filename) if have_json_file else {}
    for file in valid_alc_files:
        cache_dict = dict_file_cache[file]
        m_time_alc = cache_dict['m_time_alc']
        if have_json_file and m_time_alc < magic_ts:
            continue
        dict_date_alc[file] = m_time_alc
    return dict_date_alc


def get_dict_date_alc(valid_alc_files, dict_file_cache):
    return get_dict_date_alc_json(valid_alc_files, dict_file_cache)


def get_files_from_pairs(pairs):
    return [file for _, file in pairs]


def generate_alc_pairs(valid_alc_files, dict_date_alc):
    date_file_tuples = []
    for file in valid_alc_files:
        m_time_alc = dict_date_alc[file]
        date_file_tuples.append((m_time_alc, file))
    date_file_tuples.sort()
    date_file_tuples.reverse()
    return date_file_tuples
    return [file for _, file in date_file_tuples]


def normalize_hfs_filename(filename):
    """
    This was a bit of advice that I don't use anywhere...
    """
    filename = unicodedata.normalize(
        'NFC', unicode(filename, 'utf-8')).encode('utf-8')
    return filename


def get_last_ts(record):
    ts_list = get_ts_list(record)
    try:
        return ts_list[-1]
    except IndexError:
        return 0


def generate_date_pairs(valid_alc_files, db_dict):
    date_file_tuples = []
    for file in valid_alc_files:
        record = db_dict[file]
        ts = get_last_ts(record)
        date_file_tuples.append((ts, file))
    date_file_tuples.sort()
    date_file_tuples.reverse()
    return date_file_tuples


def generate_date_plus_alc_pairs(valid_alc_files, db_dict, dict_date_alc):
    tuples = []
    for file in valid_alc_files:
        record = db_dict[file]
        play_date = get_last_ts(record)
        alc_date = dict_date_alc[file]
        tuples.append((max(play_date, alc_date), file))
    tuples.sort()
    tuples.reverse()
    return tuples


def generate_alc(valid_alc_files, dict_date_alc):
    return get_files_from_pairs(generate_alc_pairs(valid_alc_files, dict_date_alc))


def generate_date(valid_alc_files, db_dict):
    return get_files_from_pairs(generate_date_pairs(valid_alc_files, db_dict))


def generate_date_plus_alc(valid_alc_files, db_dict, dict_date_alc):
    return get_files_from_pairs(generate_date_plus_alc_pairs(valid_alc_files, db_dict, dict_date_alc))


def get_keys_for_camelot_number(camelot_number):
    if camelot_number is None:
        return []
    key_minor = reverse_camelot_dict[str(camelot_number) + 'A']
    key_major = reverse_camelot_dict[str(camelot_number) + 'B']
    return [key_minor, key_major]


def assert_exists(filename):
    if not os.path.exists(filename):
        raise ValueError('File does not exist: {}'.format(filename))


###########
# Updated actions

def action_add(args):
    db_dict = read_db_file(args.db_filename)
    alc_files = get_ableton_files()
    for filename in alc_files:
        print (filename)
        if db_dict.has_key(filename):
            print (db_dict[filename])
            continue

        # get with tag if mp3
        bpm = None
        # TODO(peter): consider making this work again
        # if os.path.splitext(filename)[1] == '.mp3':
        #     bpm = get_mp3_bpm(filename)
        #     print ('bpm from mp3:', bpm)
        if bpm is None:
            ui = raw_input("BPM: ")
            try:
                bpm = int(ui)
            except ValueError:
                print ("Stopping and saving...")
                break

        # record the result in the database
        new_record = {'bpm': bpm, 'tags': [], 'key': ''}
        db_dict[filename] = new_record
        print ("Inserted: " + str(new_record))
    write_db_file(args.db_filename, db_dict)

# TODO(peter): this function still gross:


def action_edit(args):
    assert_exists(args.edit_filename)
    print (args.edit_filename)
    db_dict = read_db_file(args.db_filename)
    bpm = None
    if db_dict.has_key(args.edit_filename):
        record = db_dict[args.edit_filename]
        bpm = record['bpm']
    ui = raw_input("BPM [%s]: " % bpm)
    if ui:
        try:
            bpm = int(ui)
        except ValueError:
            print ("Aborting single edit")
            sys.exit(1)
    new_record = record
    new_record['bpm'] = bpm
    db_dict[args.edit_filename] = new_record
    print ("Inserted: " + str(new_record))
    write_db_file(args.db_filename, db_dict)


def action_add_missing_keys(args):
    db_dict = read_db_file(args.db_filename)
    alc_file_set = set(get_ableton_files())
    for filename, record in db_dict.iteritems():
        if filename not in alc_file_set:
            continue
        try:
            print ('considering:', filename)
            bpm, tags, key = (record['bpm'], record['tags'], record['key'])
            if len(key) == 0 or key[-1] == '?':
                filepath = os.path.abspath(filename)
                new_key = get_key_from_alc(filepath)
                print ('new_key: ' + new_key)
                if new_key is None:
                    continue
                new_record = record
                new_record['key'] = new_key
                db_dict[filename] = new_record
                # write every time...this may take a while
                write_db_file(args.db_filename, db_dict)
            else:
                print ('had key:', key)
        except IOError as e:
            print ('IOError: ' + str(e))
        except subprocess.CalledProcessError as e:
            print ('CalledProcessError (probably KeyFinder): ' + str(e))


def action_print(args):
    db_dict = read_db_file(args.db_filename)
    for filename, record in db_dict.iteritems():
        print (filename + " " + str(record))


def action_list_by_name(args):
    valid_dict = get_valid_db_dict(args.db_filename)
    valid_names = sorted(valid_dict.keys(), key=str.lower)
    print_pretty_files(valid_names, valid_dict)


def action_list_sets(args):
    db_dict = read_db_file(args.db_filename)
    ts_db_dict = get_db_by_ts(db_dict)
    last_ts = 0
    for ts in sorted(ts_db_dict.iterkeys()):
        ts_diff = ts - last_ts
        max_seconds = 10 * 60
        if ts_diff > max_seconds:
            divider = '-' * 12 + '(%d)' % (ts_diff / 60)
            print (divider)
        last_ts = ts
        files = ts_db_dict[ts]
        for f in files:
            print (f)


def action_key_frequency(args):
    date_file_tuples = []
    db_dict = read_db_file(args.db_filename)
    alc_file_set = set(get_ableton_files())
    key_frequency = {}
    for filename, record in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        bpm, tags, key = (record['bpm'], record['tags'], record['key'])
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
        print ('%4s - %3s: %d' % (key, get_camelot_key(key), count))


def action_rename_tag(args):
    db_dict = read_db_file(args.db_filename)
    for filename, record in iter(sorted(db_dict.iteritems())):
        tags = record['tags']
        tags = [x if (x != args.tag_old) else args.tag_new for x in tags]
        record['tags'] = tags
    write_db_file(args.db_filename, db_dict)


def action_list_missing(args):
    missing = get_missing(args.db_filename)
    for f in missing:
        print (f)


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

        print (f, "plays:", ts_len)

        e = os.path.splitext(f)[1]

        # cutoff=0.4, n=10
        close = difflib.get_close_matches(f, alc_file_list, cutoff=0.3, n=10)
        for index, other in enumerate(close):
            print (index, ":", other)

        choice = get_int("Choice:")
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
                target_record['ts_list'] = both_ts_list
                print ('ts_list:', ts_list, 'target_ts_list:',
                       target_ts_list, 'both_ts_list:', both_ts_list)
                # also transfer tags
                for old_tag in record['tags']:
                    if old_tag not in target_record['tags']:
                        target_record['tags'].append(old_tag)
                # delete old record
                del db_dict[f]
                write_db_file(args.db_filename, db_dict)


def action_update_cache(args):
    db_dict = read_db_file(args.db_filename)
    alc_file_set = set(get_ableton_files())
    for filename, _ in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        cache_dict = update_and_get_cache_values(filename)
        print (cache_dict)


def action_export_sample_database(args):
    db_dict = read_db_file(args.db_filename)
    alc_file_set = set(get_ableton_files())
    sample_db = {}
    for filename, _ in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        cache_dict = update_and_get_cache_values(filename)
        sample_filename = os.path.basename(cache_dict['sample_file'])
        record = db_dict[filename]
        record['pretty_name'] = os.path.splitext(filename)[0]
        sample_db[sample_filename] = record
    write_db_file(args.sample_db_filename, sample_db)


def action_print_xml(args):
    assert_exists(args.alc_filename)
    print (alc_to_str(args.alc_filename))


def action_print_audioclip(args):
    assert_exists(args.alc_filename)
    print (get_audioclip_from_alc(args.alc_filename))


def action_test_audioclip_on_all(args):
    alc_files = get_ableton_files()
    for index, f in enumerate(alc_files):
        get_audioclip_from_alc(f)
        print ('{}/{}'.format(index, len(alc_files)))


###########
# main

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('db_filename')
    subparsers = parser.add_subparsers()

    subparsers.add_parser('addbpm').set_defaults(func=action_add)
    subparsers.add_parser('addkey').set_defaults(func=action_add_missing_keys)

    p_edit = subparsers.add_parser('edit')
    p_edit.add_argument('edit_filename')
    p_edit.set_defaults(func=action_edit)

    # TODO: pick one?  print is raw, list is pretty
    # This should match listing orders in GUI, be pretty, and be the new dump
    subparsers.add_parser('print').set_defaults(func=action_print)
    subparsers.add_parser('list').set_defaults(func=action_list_by_name)
    subparsers.add_parser('list_sets').set_defaults(func=action_list_sets)

    subparsers.add_parser('keyfreq').set_defaults(func=action_key_frequency)

    p_rename = subparsers.add_parser('rename_tag')
    p_rename.add_argument('tag_old')
    p_rename.add_argument('tag_new')
    p_rename.set_defaults(func=action_rename_tag)

    subparsers.add_parser('list_missing').set_defaults(
        func=action_list_missing)
    subparsers.add_parser('transfer_ts').set_defaults(func=action_transfer_ts)
    subparsers.add_parser('update_cache').set_defaults(
        func=action_update_cache)

    p_export = subparsers.add_parser('export_sample_db')
    p_export.add_argument('sample_db_filename')
    p_export.set_defaults(func=action_export_sample_database)

    p_xml = subparsers.add_parser('print_xml')
    p_xml.add_argument('alc_filename')
    p_xml.set_defaults(func=action_print_xml)

    p_audioclip = subparsers.add_parser('print_audioclip')
    p_audioclip.add_argument('alc_filename')
    p_audioclip.set_defaults(func=action_print_audioclip)

    p_test = subparsers.add_parser('test_audioclip_on_all')
    p_test.set_defaults(func=action_test_audioclip_on_all)

    return parser.parse_args()


def main(args):
    args.func(args)

if __name__ == '__main__':
    main(parse_args())
