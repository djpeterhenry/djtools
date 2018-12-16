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


# import mutagen
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3


tag_shorthand = {
    'c': 'classic',
    'p': 'pop',
    'j': 'jazz',
    'r': 'rock',
    'h': 'hiphop',
    't': 'temp',
    'b': 'beats'
}

ABLETON_EXTENSIONS=['.alc', '.als']
SAMPLE_EXTENSIONS=['.mp3', '.m4a', '.wav', '.aiff', '.flac']
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
    if ext in ['.mp3', '.flac']:
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
            file = '%s%s%s' % (artist, divider, song)
        elif len(song) > 0:
            file = song
    # add extension:
    if ext in ['.mp3', '.flac', '.als']:
        file = '%s (%s)' % (file, ext[1:].upper())
    # add vocal:
    if 'vocal' in record['tags']:
        file = file + ' [Vocal]'
    return file


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


def action_add(db_filename):
    db_dict = read_db_file(db_filename)
    alc_files = get_ableton_files()
    for filename in alc_files:
        print (filename)
        if db_dict.has_key(filename):
            print (db_dict[filename])
            continue

        # get with tag if mp3
        bpm = None
        if os.path.splitext(filename)[1] == '.mp3':
            bpm = get_mp3_bpm(filename)
            print ('bpm from mp3:', bpm)
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
    write_db_file(db_filename, db_dict)


def action_edit(db_filename, edit_filename):
    if not os.path.exists(edit_filename):
        print ("File does not exist")
        sys.exit(1)
    print (edit_filename)
    db_dict = read_db_file(db_filename)
    bpm = None
    tag_list = None
    if db_dict.has_key(edit_filename):
        record = db_dict[edit_filename]
        bpm, tag_list, key = (record['bpm'], record['tags'], record['key'])
    ui = raw_input("BPM [%s]: " % bpm)
    if ui:
        try:
            bpm = int(ui)
        except ValueError:
            print ("Aborting single edit")
            sys.exit(1)
    new_record = record
    new_record['bpm'] = bpm
    db_dict[edit_filename] = new_record
    print ("Inserted: " + str(new_record))
    write_db_file(db_filename, db_dict)


def action_print(db_filename):
    db_dict = read_db_file(db_filename)
    for filename, record in db_dict.iteritems():
        print (filename + " " + str(record))


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


def action_list_by_name(db_filename):
    valid_dict = get_valid_db_dict(db_filename)
    valid_names = sorted(valid_dict.keys(), key=str.lower)
    print_pretty_files(valid_names, valid_dict)


def alc_to_xml(alc_filename):
    f = gzip.open(alc_filename, 'rb')
    file_content = f.read()
    f.close()
    # tree = ET.parse('country_data.xml')
    root = ET.fromstring(file_content)
    return root


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
    Sort of. Call the executable with the command line arguments -f filepath to have the key estimate printed to stdout (and/or any errors to stderr). If you also use the switch -w it will try and write to tags. Preferences from the GUI are used to determine the exact operation of the CLI.

    Don't forget that the Mac binary is buried in the .app bundle, so your command line will look something like: ./KeyFinder.app/Contents/MacOS/KeyFinder -f ~/Music/my_track.mp3 [-w]
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


def action_test_xml(alc_filename):
    key = get_key_from_alc(alc_filename)
    print ("key: " + key)


def action_add_missing_keys(db_filename):
    db_dict = read_db_file(db_filename)
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
                write_db_file(db_filename, db_dict)
            else:
                print ('had key:', key)
        except IOError as e:
            print ('IOError: ' + str(e))
        except subprocess.CalledProcessError as e:
            print ('CalledProcessError (probably KeyFinder): ' + str(e))


def action_check_bitrate(db_filename):
    # you do these next four lines a lot
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    for filename, record in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        bpm, tags, key = (record['bpm'], record['tags'], record['key'])
        filepath = os.path.abspath(filename)
        try:
            sample_file = get_sample_from_alc_file(
                filepath)  # put the try in here?
        except IOError as e:
            continue
        f, e = os.path.splitext(sample_file)
        if e != '.mp3':
            continue
        mutagen_file = MP3(sample_file)
        bitrate = (mutagen_file.info.bitrate / 1000)
        # assume 320 ok
        if bitrate >= 320:
            continue
        if 'x' in tags:
            continue
        if 'vocal' in tags:
            continue
        try:
            line = u'%s\t%s\t%s' % (bitrate, filename, sample_file)
            line_to_print = line.encode('utf-8')
            print (line_to_print, file=sys.stderr)
            print (line_to_print)
        except UnicodeDecodeError as e:
            print ('unicode error')


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


def action_test_als(db_filename, als_filename):
    # do I need these?
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    # mostly about this:
    # can use misnamed version for als
    clips = get_clips_from_als(als_filename)
    for clip in clips:
        print (clip)
    for clip in clips:
        print (clip[1])


def action_print_date_alc(db_filename):
    date_file_tuples = []
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    for filename, _ in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        try:
            m_time = os.path.getmtime(filename)
            date_file_tuples.append((m_time, filename))
        except OSError as e:
            pass
            # print e
    for time, filename in date_file_tuples:
        print (str(time) + " " + filename)


def action_print_date_sample(db_filename):
    date_file_tuples = []
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    for filename, _ in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        try:
            sample_file = get_sample_from_alc_file(filename)
            m_time = os.path.getmtime(sample_file)
            date_file_tuples.append((m_time, filename))
            print ('debug: ' + sample_file + ' ' +
                   str(m_time), file=sys.stderr)
        except OSError as e:
            print ('OSError: ' + str(e), file=sys.stderr)
        except IOError as e:
            print ('IOError: ' + str(e), file=sys.stderr)
    for time, filename in date_file_tuples:
        print (str(time) + " " + filename)


def date_list_to_dict(date_file):
    result = {}
    try:
        with open(date_file) as f:
            lines = f.readlines()
    except (IOError, OSError) as e:
        return result
    for line in lines:
        time, file = line.split(None, 1)
        result[file.strip()] = float(time)
    return result


def action_test_date_list_to_dict(date_file):
    d = date_list_to_dict(date_file)
    print (d)


def action_key_frequency(db_filename):
    date_file_tuples = []
    db_dict = read_db_file(db_filename)
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


def action_list_fields(db_filename):
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    fields = []
    for filename, record in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        for field in record.keys():
            if field not in fields:
                fields.append(field)
    print (fields)


def delete_key(record, key):
    try:
        del record[key]
    except KeyError:
        pass


def action_print_date_als(db_filename, als_filename):
    # do I need these?
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    # clips and time
    clips = get_clips_from_als(als_filename)
    for time, filename in clips:
        print (str(time) + " " + filename)
    # also without time
    for _, filename in clips:
        print (filename)


def action_summarize_als(als_filename, overwrite):
    base_filename, _ = os.path.splitext(als_filename)
    output_filename = base_filename + '.txt'
    if not overwrite and os.path.exists(output_filename):
        return
    output_file = open(output_filename, 'w')
    try:
        clips = get_clips_from_als(als_filename)
        json.dump(clips, output_file)
    except IOError as e:
        print ('IOError: ' + str(e))
        return


def action_summarize_als_folder(folder, overwrite):
    als_files = glob.glob(os.path.join(folder, '*.als'))
    for f in als_files:
        print(f)
        summarize_als(f, overwrite)


def get_ts_for_file(file):
    try:
        return os.path.getmtime(file)
    except OSError as e:
        print (e)
        return None


def action_update_db_from_summaries(db_filename, folder):
    als_files = glob.glob(os.path.join(folder, '*.als'))
    db_dict = read_db_file(db_filename)
    for f in als_files:
        print(f)
        summary_filename = os.path.splitext(f)[0] + '.txt'
        json_file = open(summary_filename, 'r')
        try:
            clips = json.load(json_file)
        except ValueError as e:
            print ("ValueError:", e)
            continue
        if not clips:
            continue
        ts_file = get_ts_for_file(f)
        ts_max = max([clip[0] for clip in clips])

        for clip in clips:
            alc_file = clip[1] + '.alc'
            print (alc_file)
            try:
                record = db_dict[alc_file]
            except KeyError:
                print ("key error:", alc_file)
                continue
            ts_clip = ts_file - ts_max + clip[0]
            ts_list = get_ts_list(record)
            print ('ts_list before:', ts_list)
            print ('ts_clip:', ts_clip)
            if ts_clip not in ts_list:
                ts_list.append(ts_clip)
                ts_list.sort()
                record['ts_list'] = ts_list
            print ('ts_list after:', ts_list)
    write_db_file(db_filename, db_dict)


def action_remove_tag(db_filename, tag):
    db_dict = read_db_file(db_filename)
    for filename, record in iter(sorted(db_dict.iteritems())):
        tags = record['tags']
        try:
            tags.remove(tag)
        except ValueError:
            pass
    write_db_file(db_filename, db_dict)


def action_rename_tag(db_filename, tag_old, tag_new):
    db_dict = read_db_file(db_filename)
    for filename, record in iter(sorted(db_dict.iteritems())):
        tags = record['tags']
        tags = [x if (x != tag_old) else tag_new for x in tags]
        record['tags'] = tags
    write_db_file(db_filename, db_dict)


def reveal_file(filename):
    command = ['open','-R', filename]
    subprocess.call(command)


def get_missing(db_filename):
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    result = []
    for filename, record in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            result.append(filename)
    return result


def action_list_missing(db_filename):
    missing = get_missing(db_filename)
    for f in missing:
        print (f)


def action_transfer_ts(db_filename):
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    alc_file_list = list(alc_file_set)
    missing = get_missing(db_filename)
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
                write_db_file(db_filename, db_dict)
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
                write_db_file(db_filename, db_dict)


def get_db_by_ts(db_dict):
    result = defaultdict(list)
    for f, record in db_dict.iteritems():
        ts_list = get_ts_list(record)
        for ts in ts_list:
            result[ts].append(f)
    return result


def action_list_sets(db_filename):
    db_dict = read_db_file(db_filename)
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


def get_google_query(f):
    s = os.path.splitext(f)[0]
    s_url = urllib.quote(s)
    link = 'http://www.google.com/search?q=%s' % s_url
    return link


def get_html_line(f, link):
    return '<a href=%s target="_blank">%s</a><br>' % (link, f)


def action_html_sets(db_filename):
    db_dict = read_db_file(db_filename)
    ts_db_dict = get_db_by_ts(db_dict)
    last_ts = max(ts_db_dict.iterkeys()) + 1
    last_date = datetime.date.today()
    max_count = 10000
    count = 0
    last_file = None
    for ts in sorted(ts_db_dict.iterkeys(), reverse=True):
        date = datetime.date.fromtimestamp(ts)
        divider = False
        if divider:
            ts_diff = last_ts - ts  # swap if not reversed
            max_seconds = 10 * 60
            if ts_diff > max_seconds:
                divider = '-' * 12 + '(%d)' % (ts_diff / 60)
                print (divider + '<br>')
        if last_date != date:
            divider = str(date) + ':'
            print (divider + '<br>')
        # update from file
        last_ts = ts
        last_date = date
        files = ts_db_dict[ts]
        # NOTE(peter): there should be only one...
        for f in files:
            if last_file == f:
                continue
            last_file = f
            record = db_dict[f]
            name = get_base_filename_with_bpm_and_key(f, record)
            # link = f
            link = get_google_query(f)
            line = get_html_line(name, link)
            print (line)
            count += 1
            if count > max_count:
                return


def action_html_list(db_filename):
    valid_dict = get_valid_db_dict(db_filename)
    for f in sorted(valid_dict.iterkeys()):
        record = valid_dict[f]
        link = get_google_query(f)
        with_bpm_key = get_base_filename_with_bpm_and_key(f, record)
        line = get_html_line(with_bpm_key, link)
        print (line)


def get_files_by_num(files, db_dict):
    num_file_tuples = []
    for file in files:
        record = db_dict[file]
        num = -len(get_ts_list(record))
        num_file_tuples.append((num, file))
    num_file_tuples.sort()
    return [file for _, file in num_file_tuples]


def action_html_list_by_num(db_filename):
    valid_dict = get_valid_db_dict(db_filename)
    files = get_files_by_num(valid_dict.iterkeys(), valid_dict)
    for f in files:
        record = valid_dict[f]
        link = get_google_query(f)
        with_bpm_key = get_base_filename_with_bpm_and_key(f, record)
        line = get_html_line(with_bpm_key, link)
        print (line)


def update_and_get_cache_values(filename):
    cache_filename = filename + '.cache.txt'
    try:
        cache_dict = cPickle.load(open(cache_filename))
    except:
        cache_dict = {}
    try:
        cache_m_time_alc = cache_dict['m_time_alc']
        cache_sample_file = cache_dict['sample_file']
    except:
        cache_m_time_alc = None
    if cache_m_time_alc:
        m_time_alc = os.path.getmtime(filename)
        if cache_m_time_alc == m_time_alc:
            return cache_dict
    # must update file
    # NOTE: this breaks when trying to print to terminal but works thereafter
#    print (u'updating: {}'.format(filename))
    m_time_alc = os.path.getmtime(filename)
    sample_file = get_sample_from_alc_file(filename)
    print (u'sample_file: {}'.format(sample_file))
    m_time_sample = os.path.getmtime(sample_file)
    cache_dict['m_time_alc'] = m_time_alc
    cache_dict['sample_file'] = sample_file
    cache_dict['m_time_sample'] = m_time_sample
    cPickle.dump(cache_dict, open(cache_filename, 'w'))
    return cache_dict


def action_update_cache(db_filename):
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    for filename, _ in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        cache_dict = update_and_get_cache_values(filename)
        print (cache_dict)


def action_export_database(db_filename, sample_db_filename):
    db_dict = read_db_file(db_filename)
    alc_file_set = set(get_ableton_files())
    sample_db = {}
    for filename, _ in iter(sorted(db_dict.iteritems())):
        if filename not in alc_file_set:
            continue
        cache_dict = update_and_get_cache_values(filename)
        sample_filename = os.path.basename(cache_dict['sample_file'])
        sample_db[sample_filename] = db_dict[filename]
    write_db_file(sample_db_filename, sample_db)


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


def action_html_list_by_sample(db_filename):
    db_dict = read_db_file(db_filename)
    valid_alc_files = get_valid_alc_files(db_dict)
    dict_file_cache = get_dict_file_cache(valid_alc_files)
    dict_date_sample = get_dict_date_sample(valid_alc_files, dict_file_cache)
    by_sample = generate_sample(valid_alc_files, dict_date_sample)
    print_html_files(by_sample, db_dict)


def get_dict_date_alc_old(valid_alc_files, dict_file_cache):
    # this holds old alc m_time values before live 9
    # the magic value is April 5, 2014
    # so if alc time is before magic_date, use the date_alc.txt value
    magic_date = datetime.date(2014, 4, 5)
    magic_ts = time.mktime(magic_date.timetuple())

    date_alc_txt = 'date_alc.txt'
    dict_date_alc = date_list_to_dict(date_alc_txt)
    for file in valid_alc_files:
        cache_dict = dict_file_cache[file]
        m_time_alc = cache_dict['m_time_alc']
        if m_time_alc < magic_ts:
            continue
        dict_date_alc[file] = m_time_alc
    return dict_date_alc


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


def action_html_list_by_alc(db_filename):
    # TODO: dup with action_html_list_by_sample at least
    db_dict = read_db_file(db_filename)
    valid_alc_files = get_valid_alc_files(db_dict)
    dict_file_cache = get_dict_file_cache(valid_alc_files)
    dict_date_alc = get_dict_date_alc(valid_alc_files, dict_file_cache)
    by_alc = generate_alc(valid_alc_files, dict_date_alc)
    print_html_files(by_alc, db_dict)


def print_html_files(files, db_dict):
    for f in files:
        record = db_dict[f]
        link = get_google_query(f)
        with_bpm_key = get_base_filename_with_bpm_and_key(f, record)
        line = get_html_line(with_bpm_key, link)
        print (line)


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
    key_minor = reverse_camelot_dict[str(camelot_number)+'A']
    key_major = reverse_camelot_dict[str(camelot_number)+'B']
    return [key_minor, key_major]



########################################################################
if __name__ == '__main__':
    argv_iter = iter(sys.argv)
    _ = argv_iter.next()

    db_filename = argv_iter.next()
    # TODO: read db once here and pass object around

    command_opt = argv_iter.next()
    if command_opt == '-addbpm':
        action_add(db_filename)
    elif command_opt == '-addkey':
        action_add_missing_keys(db_filename)
    elif command_opt == '-e':
        edit_filename = argv_iter.next()
        action_edit(db_filename, edit_filename)
    elif command_opt == '-p':
        action_print(db_filename)
    elif command_opt == '-ls':
        action_list_by_name(db_filename)
    elif command_opt == '-test':
        filename = argv_iter.next()
        action_test_xml(filename)
    elif command_opt == '-check':
        action_check_bitrate(db_filename)
    elif command_opt == '-als':
        als_filename = argv_iter.next()
        action_test_als(db_filename, als_filename)
    elif command_opt == '-datealc':
        action_print_date_alc(db_filename)
    elif command_opt == '-datesample':
        action_print_date_sample(db_filename)
    elif command_opt == '-testdate':
        date_file = argv_iter.next()
        action_test_date_list_to_dict(date_file)
    elif command_opt == '-keyfreq':
        action_key_frequency(db_filename)
    elif command_opt == '-listfields':
        action_list_fields(db_filename)
    elif command_opt == '-print_als':
        als_filename = argv_iter.next()
        action_print_date_als(db_filename, als_filename)
    elif command_opt == '-summarize_als':
        als_filename = argv_iter.next()
        action_summarize_als(als_filename, True)
    elif command_opt == '-summarize_als_folder':
        als_folder = argv_iter.next()
        action_summarize_als_folder(als_folder, False)
    elif command_opt == '-update_db_from_summaries':
        als_folder = argv_iter.next()
        action_update_db_from_summaries(db_filename, als_folder)
    elif command_opt == '-remove_tag':
        tag = argv_iter.next()
        action_remove_tag(db_filename, tag)
    elif command_opt == '-rename_tag':
        tag_old = argv_iter.next()
        tag_new = argv_iter.next()
        action_rename_tag(db_filename, tag_old, tag_new)
    elif command_opt == '-list_missing':
        action_list_missing(db_filename)
    elif command_opt == '-transfer_ts':
        action_transfer_ts(db_filename)
    elif command_opt == '-list_sets':
        action_list_sets(db_filename)
    elif command_opt == '-html_sets':
        action_html_sets(db_filename)
    elif command_opt == '-html_list':
        action_html_list(db_filename)
    elif command_opt == '-html_list_num':
        action_html_list_by_num(db_filename)
    elif command_opt == '-html_list_sample':
        action_html_list_by_sample(db_filename)
    elif command_opt == '-html_list_alc':
        action_html_list_by_alc(db_filename)
    elif command_opt == '-update_cache':
        action_update_cache(db_filename)
    elif command_opt == '-export_sample_db':
        sample_db_filename = argv_iter.next()
        action_export_database(db_filename, sample_db_filename)
    else:
        print ('Unknown command')
        sys.exit(1)
