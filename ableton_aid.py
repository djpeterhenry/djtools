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
import codecs
import xml.etree.ElementTree as ET
import json
import time
import unicodedata
import datetime
import difflib
import urllib
from collections import defaultdict
import argparse
import shutil

# import mutagen
try:
    from mutagen.mp3 import MP3
    from mutagen.easyid3 import EasyID3
except:
    pass


ABLETON_EXTENSIONS = ['.alc', '.als']
SAMPLE_EXTENSIONS = ['.mp3', '.m4a', '.wav', '.aiff', '.flac']
ALL_EXTENSIONS = ABLETON_EXTENSIONS + SAMPLE_EXTENSIONS

def get_ts_for(year, month, day):
    return time.mktime(datetime.date(year, month, day).timetuple())

#OLD_ALC_TS_CUTOFF = time.mktime(datetime.date(2016, 6, 12).timetuple())
OLD_ALC_TS_CUTOFF = get_ts_for(2016, 6, 12)

REKORDBOX_SAMPLE_PATH = u'/Volumes/MacHelper/rekordbox_samples'
#MP3_SAMPLE_PATH = u'/Volumes/MacHelper/mp3_samples'
MP3_SAMPLE_PATH = u'/Volumes/music/mp3_samples/'

LISTS_FOLDER = '/Users/peter/github/djpeterhenry.github.io/lists'

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
    return sorted(result, key=str.lower)


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


def use_for_rekordbox(record):
    if 'x' in record['tags']:
        return False
    if 'x_rekordbox' in record['tags']:
        return False
    return True


def is_vocal(record):
    return 'vocal' in record['tags']


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
    result['alc_ts'] = os.path.getmtime(alc_filename)
    xml_warp_markers = xml_clip.find('WarpMarkers')
    result['warp_markers'] = []
    for marker in xml_warp_markers:
        result['warp_markers'].append(dict(sec_time=float(marker.get('SecTime')),
                                           beat_time=float(marker.get('BeatTime'))))
    xml_loop = xml_clip.find('Loop')
    result['start'] = float(xml_loop.find('LoopStart').get('Value'))
    result['end'] = float(xml_loop.find('LoopEnd').get('Value'))
    result['loop_start'] = float(xml_loop.find('HiddenLoopStart').get('Value'))
    result['loop_end'] = float(xml_loop.find('HiddenLoopEnd').get('Value'))
    # also sample info
    xml_fileref = xml_clip.find('SampleRef/FileRef')
    relative_path = os.path.join(
        '..', *[x.get('Dir') for x in xml_fileref.find('RelativePath')])
    sample_filepath = os.path.join(
        relative_path, xml_fileref.find('Name').get('Value'))
    if os.path.exists(sample_filepath):
        result['sample'] = sample_filepath
        result['sample_ts'] = os.path.getmtime(sample_filepath)
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


def get_camelot_num(key):
    cam_key = get_camelot_key(key)
    if cam_key is None:
        return None
    return int(cam_key[:-1])


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


def get_valid_alc_files(db_dict):
    alc_files = get_ableton_files()
    valid_alc_files = [
        filename for filename in alc_files if db_dict.has_key(filename)]
    valid_alc_files.sort(key=lambda s: s.lower())
    return valid_alc_files


def generate_sample(valid_alc_files, db_dict):
    date_file_tuples = []
    for f in valid_alc_files:
        record = db_dict[f]
        if 'clip' not in record:
            continue
        date_file_tuples.append((record['clip']['sample_ts'], f))
    date_file_tuples.sort()
    date_file_tuples.reverse()
    return [file for _, file in date_file_tuples]


def get_files_from_pairs(pairs):
    return [file for _, file in pairs]


def add_ts(record, ts):
    try:
        current = record['ts_list']
        if ts not in current:
            current.append(ts)
    except KeyError:
        record['ts_list'] = [ts]


def get_ts_list(record):
    try:
        ts_list = record['ts_list']
    except:
        ts_list = []
    return ts_list


def get_last_ts(record):
    ts_list = get_ts_list(record)
    try:
        return sorted(ts_list)[-1]
    except IndexError:
        return 0


def get_alc_ts(record):
    try:
        alc_ts = record['clip']['alc_ts']
        if alc_ts < OLD_ALC_TS_CUTOFF and 'old_alc_ts' in record:
            return record['old_alc_ts']
        return alc_ts
    except KeyError:
        return 0


def get_alc_or_last_ts(record):
    return max(get_alc_ts(record), get_last_ts(record))


def get_date_from_ts(ts):
    return datetime.date.fromtimestamp(ts).strftime('%Y-%m-%d')


def get_sample(record):
    try:
        return record['clip']['sample']
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


def generate_alc(valid_alc_files, db_dict):
    return get_files_from_pairs(generate_alc_pairs(valid_alc_files, db_dict))


def generate_date(valid_alc_files, db_dict):
    return get_files_from_pairs(generate_date_pairs(valid_alc_files, db_dict))


def generate_date_plus_alc(valid_alc_files, db_dict):
    return get_files_from_pairs(generate_date_plus_alc_pairs(valid_alc_files, db_dict))


def get_keys_for_camelot_number(camelot_number):
    if camelot_number is None:
        return []
    key_minor = reverse_camelot_dict[str(camelot_number) + 'A']
    key_major = reverse_camelot_dict[str(camelot_number) + 'B']
    return [key_minor, key_major]


def get_relative_camelot_key(cam_num, offset):
    return (((cam_num + offset - 1) % 12) + 1)


def matches_bpm_filter(filter_bpm, bpm_range, bpm):
    for sub_bpm in [int(round(bpm / 2.0)), bpm, int(round(bpm * 2.0))]:
        if (sub_bpm >= filter_bpm - bpm_range and sub_bpm <= filter_bpm + bpm_range):
            return True
    return False


def assert_exists(filename):
    if not os.path.exists(filename):
        raise ValueError('File does not exist: {}'.format(filename))


def update_db_clips(valid_alc_files, db_dict, force=False):
    for f in valid_alc_files:
        record = db_dict[f]
        alc_ts = os.path.getmtime(f)
        if not force and 'clip' in record and record['clip']['alc_ts'] == alc_ts:
            continue
        record['clip'] = get_audioclip_from_alc(f)
        print ('Updated:', f)


def get_artist_and_track(filename):
    delimiter = ' - '
    split = os.path.splitext(filename)[0].split(delimiter)
    if len(split) == 1:
        return '', split[0]
    elif len(split) == 2:
        return split[0], split[1]
    else:
        return split[0], delimiter.join(split[1:])


def get_sample_unicode(record):
    if 'clip' not in record:
        return None
    sample = record['clip']['sample']
    # Ok, this seems to work to get all the samples to unicode...
    # Still not sure why some samples (Take Over Control Acapella) are unicode
    if not isinstance(sample, unicode):
        sample = sample.decode('utf-8')
    return sample


def get_export_sample_path(f, sample_ext, target_path):
    f_base, _ = os.path.splitext(f.decode('utf-8'))
    return os.path.join(target_path, f_base + sample_ext).encode('utf-8')


def get_existing_rekordbox_sample(record):
    try:
        sample = record['rekordbox_sample']
        if os.path.exists(sample):
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
        if ext in ('.txt', '') and not name.startswith('.'):
            name_to_file[name] = f
    return name_to_file


def get_song_in_db(s, db_dict):
    alc_filename = s + '.alc'
    als_filename = s + '.als'
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
    with open(filename) as f:
        song_list = [song.strip() for song in f.readlines()]
        display_and_file = []
        for s in song_list:
            t = get_song_in_db(s, db_dict)
            display_and_file.append(t)
        return display_and_file



####################################
# actions start here

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


def action_edit(args):
    # TODO(peter): clean up this shitty old function
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
        record['pretty_name'] = os.path.splitext(filename)[0]
        sample_db[sample_filename] = record
    write_db_file(args.sample_db_filename, sample_db)


def action_print_xml(args):
    assert_exists(args.alc_filename)
    print (alc_to_str(args.alc_filename))


def action_print_audioclip(args):
    assert_exists(args.alc_filename)
    print (get_audioclip_from_alc(args.alc_filename))


def action_update_db_clips(args, force=True):
    db_dict = read_db_file(args.db_filename)
    valid_alc_files = get_valid_alc_files(db_dict)
    update_db_clips(valid_alc_files, db_dict, force)
    write_db_file(args.db_filename, db_dict)


def action_export_rekordbox(args):
    USE_REKORDBOX_SAMPLE = False
    VERSION = 11

    db_dict = read_db_file(args.db_filename)
    files = get_ableton_files()
    files = generate_date_plus_alc(files, db_dict)


    def add_beat_grid_marker(et_track, sec_time, bpm, beat_time):
        et_tempo = ET.SubElement(et_track, 'TEMPO')
        et_tempo.set('Inizio', str(sec_time))
        et_tempo.set('Bpm', str(bpm))
        et_tempo.set('Metro', '4/4')
        # round beat time to nearest beat and mod 4?
        nearest_beat = (int(round(beat_time)) % 4) + 1
        et_tempo.set('Battito', str(nearest_beat))

    def add_position_marker(et_track, name, type, num, start_seconds, end_seconds=None):
        et_position = ET.SubElement(et_track, 'POSITION_MARK')
        et_position.set('Name', name)
        et_position.set('Type', str(type))
        et_position.set('Start', str(start_seconds))
        if end_seconds is not None:
            et_position.set('End', str(end_seconds))
        et_position.set('Num', str(num))

    def get_seconds_for_beat(ref_beat, ref_sec, desired_beat, bpm):
        beat_diff = desired_beat - ref_beat
        spb = 60.0 / bpm
        return ref_sec + beat_diff * spb

    num_added = 0
    et_dj_playlists = ET.Element('DJ_PLAYLISTS')
    et_collection = ET.SubElement(et_dj_playlists, 'COLLECTION')
    file_to_id = {}
    files_with_id = []

    for f in files:
        record = db_dict[f]
        if not use_for_rekordbox(record):
            continue
        if USE_REKORDBOX_SAMPLE:
            sample = get_existing_rekordbox_sample(record)
        else:
            sample = get_sample_unicode(record)
        if sample is None:
            print ('Error getting sample for {}'.format(f))
            continue

        et_track = ET.SubElement(et_collection, 'TRACK')
        artist, track = get_artist_and_track(f)

        # Put camelot key in track name
        cam_key = get_camelot_key(record['key'])
        if cam_key:
            et_track.set('Tonality', cam_key)
            track = '{} [{}]'.format(track, cam_key)

        # Evidently getting these as unicode is important for some
        et_track.set('Name', track.decode('utf-8'))
        et_track.set('Artist', artist.decode('utf-8'))
        sample_uri = 'file://localhost' + os.path.abspath(sample)
        et_track.set('Location', sample_uri)

        # number of plays
        num_plays = len(get_ts_list(record))
        et_track.set('PlayCount', str(num_plays))

        # alc
        et_track.set('DateAdded', get_date_from_ts(get_alc_ts(record)))

        # abuse comment for alc+date
        et_track.set('Comments', get_date_from_ts(get_alc_or_last_ts(record)))

        # abuse album for random
        et_track.set('Album', str(random.randint(0, 2**31)))

        first_bpm = None

        clip = record['clip']
        warp_markers = clip['warp_markers']

        # maybe these need to be in order?
        beat_grid_markers = []

        for warp_index in xrange(len(warp_markers) - 1):
            this_marker = warp_markers[warp_index]
            this_beat_time = this_marker['beat_time']
            this_sec_time = this_marker['sec_time']
            next_marker = warp_markers[warp_index + 1]
            next_beat_time = next_marker['beat_time']
            next_sec_time = next_marker['sec_time']
            bpm = 60 * ((next_beat_time - this_beat_time) /
                        (next_sec_time - this_sec_time))
            if warp_index == 0:
                first_bpm = bpm
                et_track.set('AverageBpm', str(bpm))
            beat_grid_markers.append(
                dict(sec_time=this_sec_time, bpm=bpm, beat_time=this_beat_time))

        # We need a first bpm and first marker to do the rest
        if first_bpm:
            first_marker = warp_markers[0]
            first_marker_beat = first_marker['beat_time']
            first_marker_sec = first_marker['sec_time']

            start_beat = clip['start']
            start_seconds = get_seconds_for_beat(
                first_marker_beat, first_marker_sec, start_beat, first_bpm)

            # NOTE(peter): this may be wrong if the bpm changes a lot...
            #end_beat = clip['end']
            #end_seconds = get_seconds_for_beat(first_marker_beat, first_marker_sec, end_beat, first_bpm)
            #et_track.set('TotalTime', str(end_seconds - start_seconds))
            # Go back to just setting 20:00 for all tracks because it wants full sample length
            # Better would be extracting full sample duration and using that,
            # but needlessly slow
            et_track.set('TotalTime', str(60 * 20))

            if start_beat < first_marker_beat:
                beat_grid_markers.append(
                    dict(sec_time=start_seconds, bpm=first_bpm, beat_time=start_beat))

            # sort beat grid markers before adding (needed...sigh)
            beat_grid_markers.sort(key=lambda x: x['sec_time'])
            for b in beat_grid_markers:
                add_beat_grid_marker(et_track, **b)

            hot_cue_counter = 0
            # memory cue
            add_position_marker(et_track, 'Start', 0, -1, start_seconds)
            add_position_marker(et_track, 'Start', 0, hot_cue_counter, start_seconds)
            hot_cue_counter += 1
            # hot cue
            #add_position_marker(et_track, 'Start (hot)', 0, 0, start_seconds)
            # loop hot and memory queues
            loop_start_beat = clip['loop_start']
            loop_end_beat = clip['loop_end']
            loop_start_sec = get_seconds_for_beat(
                first_marker_beat, first_marker_sec, loop_start_beat, first_bpm)
            loop_end_sec = get_seconds_for_beat(
                first_marker_beat, first_marker_sec, loop_end_beat, first_bpm)
            add_position_marker(et_track, 'Start Loop',
                                4, -1, loop_start_sec, loop_end_sec)
            add_position_marker(et_track, 'Start Loop',
                                4, hot_cue_counter, loop_start_sec, loop_end_sec)

            # memory cue for first warp marker too if it's after start
            if start_beat < first_marker_beat:
                add_position_marker(et_track, 'Beat 1',
                                    0, -1, first_marker_sec)

        # finally record this track id
        et_track.set('TrackID', str(num_added))
        file_to_id[f] = num_added
        files_with_id.append(f)
        num_added += 1
    # this is great...add this at the end!
    et_collection.set('Entries', str(num_added))

    def set_folder_count(et):
        et.set('Count', str(len(et.getchildren())))

    def set_playlist_count(et):
        et.set('Entries', str(len(et.getchildren())))

    def add_playlist_for_files(et_parent, name, files):
        et_list = ET.SubElement(et_parent, 'NODE')
        et_list.set('Type', '1')
        et_list.set('Name', name)
        et_list.set('KeyType', '0')
        for f in files:
            et_track = ET.SubElement(et_list, 'TRACK')
            et_track.set('Key', str(file_to_id[f]))
        set_playlist_count(et_list)

    def add_folder(et_parent, name):
        result = ET.SubElement(et_parent, 'NODE')
        result.set('Type', '0')
        result.set('Name', name)
        return result

    def get_filtered_files(files, bpm, bpm_range, cam_num_list, vocal):
        matching_files = []
        for f in files:
            record = db_dict[f]
            if bpm is not None and not matches_bpm_filter(bpm, bpm_range, record['bpm']):
                continue
            cam_num = get_camelot_num(record['key'])
            if cam_num_list and cam_num not in cam_num_list:
                continue
            if not (is_vocal(record) or not vocal):
                continue
            matching_files.append(f)
        return matching_files

    def get_bpm_name(bpm):
        return '{:03d} BPM'.format(bpm)

    def get_key_name(key):
        str_minor, str_major = get_keys_for_camelot_number(key)
        return '{:02d} [{}, {}]'.format(key, str_minor, str_major)

    # now the playlists...
    et_playlists = ET.SubElement(et_dj_playlists, 'PLAYLISTS')
    et_root_node = add_folder(et_playlists, 'ROOT')

    # version playlist as root
    et_version_node = add_folder(et_root_node, 'V{:02}'.format(VERSION))

    # playlist for all
    add_playlist_for_files(et_version_node, 'All', files_with_id)

    def add_bpm_folders(et_filter_folder, bpm_range, meta_bpm_and_range=None):
        bpm_centers = [0] + range(80, 161, bpm_range)
        for bpm in bpm_centers:
            print(bpm)
            if meta_bpm_and_range is not None:
                print(meta_bpm_and_range)
                meta_bpm, meta_bpm_range = meta_bpm_and_range
                if bpm < meta_bpm or bpm >= meta_bpm + meta_bpm_range:
                    continue

            et_bpm_folder = add_folder(et_filter_folder, get_bpm_name(bpm))
            matching_files = get_filtered_files(files=files_with_id,
                                                bpm=bpm, bpm_range=bpm_range,
                                                cam_num_list=None,
                                                vocal=False)
            add_playlist_for_files(et_bpm_folder, 'All', matching_files)

            matching_files = get_filtered_files(files=files_with_id,
                                                bpm=bpm, bpm_range=bpm_range,
                                                cam_num_list=None,
                                                vocal=True)
            add_playlist_for_files(et_bpm_folder, 'Vocal', matching_files)

            for key in xrange(1, 13):
                # (key, key+1)
                keys = [key, get_relative_camelot_key(key, 1)]
                matching_files = get_filtered_files(files=files_with_id,
                                                    bpm=bpm, bpm_range=bpm_range,
                                                    cam_num_list=keys,
                                                    vocal=False)
                add_playlist_for_files(
                    et_bpm_folder, get_key_name(key), matching_files)

    ##########
    # hot damn 5*2
    meta_bpm_range = 10
    for meta_bpm in [0] + range(80, 159, meta_bpm_range):
        print('{}'.format(meta_bpm))
        meta_bpm_and_range = (meta_bpm, meta_bpm_range)
        et_meta_folder = add_folder(
            et_version_node, '{}-{}'.format(meta_bpm, meta_bpm + (meta_bpm_range - 1)))
        et_filter_folder = add_folder(et_meta_folder, 'BPM Filter (2)')
        add_bpm_folders(et_filter_folder, 2, meta_bpm_and_range)
        et_filter_folder = add_folder(et_meta_folder, 'BPM Filter (5)')
        add_bpm_folders(et_filter_folder, 5, meta_bpm_and_range)

    # lists
    et_lists_folder = add_folder(et_version_node, 'Lists')
    name_to_file = get_list_name_to_file(LISTS_FOLDER)
    for name, list_file in sorted(name_to_file.iteritems()):
        l =  get_list_from_file(list_file, db_dict)
        matching_files = [f for _, f in l if f is not None]
        add_playlist_for_files(et_lists_folder, name, matching_files)

    # finalize
    tree = ET.ElementTree(et_dj_playlists)
    tree.write(args.rekordbox_filename, encoding='utf-8', xml_declaration=True)


def action_export_rekordbox_samples(args):
    db_dict = read_db_file(args.db_filename)
    files = get_ableton_files()
    for f in files:
        record = db_dict[f]
        if not use_for_rekordbox(record):
            continue
        print ('Starting', f)
        sample = get_sample_unicode(record)
        if sample is None:
            print ('Failed to get sample for {}'.format(f))
            continue
        _, sample_ext = os.path.splitext(sample)
        # convert flac, copy others
        if sample_ext.lower() == '.flac':
            target = get_export_sample_path(f, '.aiff', REKORDBOX_SAMPLE_PATH)
            if not os.path.exists(target):
                cmd = ['ffmpeg', '-i', sample, target]
                subprocess.check_call(cmd)
        else:
            target = get_export_sample_path(
                f, sample_ext, REKORDBOX_SAMPLE_PATH)
            if not os.path.exists(target):
                shutil.copy(sample, target)
        assert os.path.exists(target)
        record['rekordbox_sample'] = target.decode('utf-8')
    write_db_file(args.db_filename, db_dict)


def action_export_mp3_samples(args):
    db_dict = read_db_file(args.db_filename)
    files = get_ableton_files()
    for f in files:
        record = db_dict[f]
        if not use_for_rekordbox(record):
            continue
        print ('Starting', f)
        sample = get_sample_unicode(record)
        if sample is None:
            print ('Failed to get sample for {}'.format(f))
            continue
        _, sample_ext = os.path.splitext(sample)
        # convert all but mp3 and m4a
        if sample_ext.lower() in ('.mp3', '.m4a'):
            # copy these
            target = get_export_sample_path(f, sample_ext, MP3_SAMPLE_PATH)
            if not os.path.exists(target):
                shutil.copy(sample, target)
        else:
            # convert these
            target = get_export_sample_path(f, '.mp3', MP3_SAMPLE_PATH)
            if not os.path.exists(target):
                cmd = ['ffmpeg', '-i', sample, '-codec:a',
                       'libmp3lame', '-b:a', '320k', target]
                subprocess.check_call(cmd)
        assert os.path.exists(target)
        os.utime(target, (time.time(), get_alc_ts(record)))
        record['mp3_sample'] = target.decode('utf-8')
    write_db_file(args.db_filename, db_dict)


def action_test_lists(args):
    db_dict = read_db_file(args.db_filename)
    name_to_file = get_list_name_to_file(LISTS_FOLDER)
    for name, list_file in sorted(name_to_file.iteritems()):
        print ('---', name)
        for display, f in get_list_from_file(list_file, db_dict):
            if f is None:
                print (display)


def action_test_artist_track(args):
    db_dict = read_db_file(args.db_filename)
    files = get_ableton_files()
    for f in files:
        artist, track = get_artist_and_track(f)
        if not artist or not track:
            print (f)


def action_rekordbox_history(args):
    db_dict = read_db_file(args.db_filename)

    p_line = re.compile(ur'\d+\t(.*)\t(.*) \[.*$')

    # get date from filename
    p_filename = re.compile(ur'HISTORY (\d+)-(\d+)-(\d+)\.txt')
    m_filename = p_filename.match(os.path.basename(args.history_filename))
    if not m_filename:
        return
    year = int(m_filename.group(1))
    month = int(m_filename.group(2))
    day = int(m_filename.group(3))
    date_ts = get_ts_for(year, month, day)
    # fun print of those later:
    if False:
        for f, record in db_dict.iteritems():
            last_ts = get_alc_or_last_ts(record)
            if last_ts > date_ts:
                print (f)
        return

    with codecs.open(args.history_filename, encoding='utf-16le') as h:
        for index, line in enumerate(h.readlines()[1:]):
            m = p_line.match(line)
            if m:
                s = u'{} - {}'.format(m.group(1), m.group(2))
                s_str = s.encode('utf8')
                _, f = get_song_in_db(s_str, db_dict)
                if f is not None:
                    record = db_dict[f]
                    ts_to_write = date_ts + index
                    print ('{}:{}'.format(f, ts_to_write))
                    add_ts(record, ts_to_write)
    # write
    write_db_file(args.db_filename, db_dict)


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
    subparsers.add_parser('list_sets').set_defaults(func=action_list_sets)

    subparsers.add_parser('keyfreq').set_defaults(func=action_key_frequency)

    p_rename = subparsers.add_parser('rename_tag')
    p_rename.add_argument('tag_old')
    p_rename.add_argument('tag_new')
    p_rename.set_defaults(func=action_rename_tag)

    subparsers.add_parser('list_missing').set_defaults(
        func=action_list_missing)
    subparsers.add_parser('transfer_ts').set_defaults(func=action_transfer_ts)

    p_export = subparsers.add_parser('export_sample_db')
    p_export.add_argument('sample_db_filename')
    p_export.set_defaults(func=action_export_sample_database)

    p_xml = subparsers.add_parser('print_xml')
    p_xml.add_argument('alc_filename')
    p_xml.set_defaults(func=action_print_xml)

    p_audioclip = subparsers.add_parser('print_audioclip')
    p_audioclip.add_argument('alc_filename')
    p_audioclip.set_defaults(func=action_print_audioclip)

    subparsers.add_parser('update_db_clips').set_defaults(
        func=action_update_db_clips)

    p_rekordbox = subparsers.add_parser('export_rekordbox')
    p_rekordbox.add_argument('rekordbox_filename')
    p_rekordbox.set_defaults(func=action_export_rekordbox)

    p_rb_samples = subparsers.add_parser('export_rekordbox_samples')
    p_rb_samples.set_defaults(func=action_export_rekordbox_samples)

    p_mp3_samples = subparsers.add_parser('export_mp3_samples')
    p_mp3_samples.set_defaults(func=action_export_mp3_samples)

    subparsers.add_parser('test_lists').set_defaults(func=action_test_lists)
    subparsers.add_parser('test_artists').set_defaults(func=action_test_artist_track)

    p_rekordbox_history = subparsers.add_parser('rekordbox_history')
    p_rekordbox_history.add_argument('history_filename')
    p_rekordbox_history.set_defaults(func=action_rekordbox_history)

    return parser.parse_args()


def main(args):
    args.func(args)

if __name__ == '__main__':
    main(parse_args())
