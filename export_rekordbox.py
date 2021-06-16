from __future__ import print_function

import os
import subprocess
import shutil
import xml.etree.ElementTree as ET
import random

import ableton_aid as aa
from tag import Tag

VERSION = 3

REKORDBOX_SAMPLE_PATH = u'/Volumes/music/rekordbox_samples'
REKORDBOX_LOCAL_SAMPLE_PATH = u'/Users/peter/Music/PioneerDJ/LocalSamples'
REKORDBOX_HISTORY_PATH = u'/Users/peter/Documents/rekordbox_history'

def export_rekordbox_history(db_filename, history_path=REKORDBOX_HISTORY_PATH):
    db_dict = aa.read_db_file(db_filename)

    for fn in os.listdir(history_path):
        history_filepath = os.path.join(history_path, fn)
        aa.update_with_rekordbox_history(db_dict, history_filepath)

    # write
    aa.write_db_file(db_filename, db_dict)

def export_rekordbox_samples(db_filename, sample_path, sample_key, convert_flac, always_copy):
    aa.update_db_clips_safe(db_filename)
    aa.generate_lists(db_filename)

    extensions_to_convert = ['.mp4', '.m4a']
    if convert_flac:
        extensions_to_convert.append('.flac')

    db_dict = aa.read_db_file(db_filename)
    files = aa.get_valid_alc_files(db_dict)
    for f in files:
        record = db_dict[f]
        if not aa.use_for_rekordbox(record):
            continue
        sample = aa.get_sample_unicode(record)
        if sample is None:
            print ('Failed to get sample for {}'.format(f))
            continue
        _, sample_ext = os.path.splitext(sample)
        # convert
        if sample_ext.lower() in extensions_to_convert:
            target = aa.get_export_sample_path(f, '.aiff', sample_path)
            if not aa.is_valid(target):
                cmd = ['ffmpeg', '-i', sample, target]
                subprocess.check_call(cmd)
        # copy
        elif always_copy:
            target = aa.get_export_sample_path(f, sample_ext, sample_path)
            # remove existing target link to fix
            if os.path.islink(target):
                os.unlink(target)
            if not os.path.exists(target):
                shutil.copy(sample, target)
                # TODO: fix this so it handles unicode.  Some recent Ame track broke it.
                #print ('Copied {} to {}'.format(sample, target))
        else:
            target = sample.encode('utf-8')
        assert aa.is_valid(target)
        record[sample_key] = target.decode('utf-8')
    aa.write_db_file(db_filename, db_dict)


def add_beat_grid_marker(et_track, sec_time, bpm, beat_time):
    et_tempo = ET.SubElement(et_track, 'TEMPO')
    et_tempo.set('Inizio', str(sec_time))
    et_tempo.set('Bpm', str(bpm))
    et_tempo.set('Metro', '4/4')
    # NOTE(peter): rekordbox seems to use sec_time + bpm as enough!
    # CORRECTION: IT'S NOT ENOUGH!  Consider assuming each is a downbeat?
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


def get_beat_for_seconds(ref_beat, ref_sec, desired_seconds, bpm):
    second_diff = desired_seconds - ref_sec
    bps = bpm / 60.0
    return ref_beat + second_diff * bps


def get_seconds_relative_to_marker(ref_marker, beat):
    return get_seconds_for_beat(ref_marker.beat_time, ref_marker.sec_time, beat, ref_marker.bpm)


def get_beat_relative_to_marker(ref_marker, seconds):
    return get_beat_for_seconds(ref_marker.beat_time, ref_marker.sec_time, seconds, ref_marker.bpm)


def set_folder_count(et):
    et.set('Count', str(len(et.getchildren())))


def set_playlist_count(et):
    et.set('Entries', str(len(et.getchildren())))


def add_folder(et_parent, name):
    result = ET.SubElement(et_parent, 'NODE')
    result.set('Type', '0')
    result.set('Name', name)
    return result


def get_filtered_files(db_dict, files,
                       bpm=None, bpm_range=None, 
                       cam_num_list=None,
                       tags=None):
    matching_files = []
    tags = tags or []
    for f in files:
        record = db_dict[f]

        # This is a stupid way to do this probably:
        if tags:
            found_any = False
            for tag in tags:
                if tag in record['tags']:
                    found_any = True
            if not found_any:
                continue

        is_vocal = aa.is_vocal(record)
        if bpm is not None:
            bpm_range_to_use = bpm_range + 10 if is_vocal else bpm_range
            if not aa.matches_bpm_filter(bpm, bpm_range_to_use, record['bpm']):
                continue
        cam_num = aa.get_camelot_num(record['key'])
        if cam_num_list is not None and cam_num not in cam_num_list:
            continue
        matching_files.append(f)
    return matching_files


class BeatGridMarker(object):

    def __init__(self, sec_time, bpm, beat_time, memory_note=None):
        self.sec_time = sec_time
        self.bpm = bpm
        self.beat_time = beat_time
        self.memory_note = memory_note

    def __repr__(self):
        return "(sec_time: {}, bpm: {}, beat_time: {})".format(self.sec_time, self.bpm, self.beat_time)

    def set_memory_note(self, memory_note):
        self.memory_note = memory_note


class Cue(object):

    def __init__(self, start, end, loop_on, name):
        self.start = start
        self.end = end
        self.loop_on = loop_on
        self.name = name


class BeatGridMarkersResult(object):

    def __init__(self, beat_grid_markers, start_cue, loop_cue):
        self.beat_grid_markers = beat_grid_markers
        self.start_cue = start_cue
        self.loop_cue = loop_cue


def get_beat_grid_markers(filename, clip):
    beat_grid_markers = []

    warp_markers = clip['warp_markers']

    first_bpm = None
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
        beat_grid_markers.append(BeatGridMarker(
            sec_time=this_sec_time, bpm=bpm, beat_time=this_beat_time))

    assert beat_grid_markers

    first_from_warp = beat_grid_markers[0]

    start_beat = clip['loop_start'] + clip['start_relative']
    # assumes relative to first warp marker!
    start_seconds = get_seconds_relative_to_marker(first_from_warp, start_beat)
    start_cue = Cue(start_seconds, None, False, 'Start')

    # Starting before zero is broken in Rekordbox
    if start_seconds < 0:
        print ('start_seconds: {:.3}:{}'.format(round(start_seconds, 3), filename))

    # make sure we have beat grid back to the start if before the first warp marker
    if start_beat < first_from_warp.beat_time:
        first_from_warp.set_memory_note('Beat 1')
        beat_grid_markers.append(BeatGridMarker(
            sec_time=start_seconds, bpm=first_bpm, beat_time=start_beat))

    # New: try to put beat grid markers all the way back to around 0 seconds
    # Sort so we can use either the start beat or first warp beat whichever is earlier.
    beat_grid_markers.sort(key=lambda x: x.sec_time)
    beat_cursor = beat_grid_markers[0].beat_time
    while True:
        beat_cursor -= 16
        sec_cursor = get_seconds_relative_to_marker(beat_grid_markers[0], beat_cursor)
        if sec_cursor <= 0:
            break
        beat_grid_markers.append(BeatGridMarker(sec_time=sec_cursor, bpm=first_bpm, beat_time=beat_cursor))

    # Actually create start and loop Cue objects
    # I've discovered that the hidden_loop_start is only correct when the loop is off.
    # When the loop is on, I have no fucking clue what it represents!
    loop_on = clip['loop_on']
    loop_start_beat = clip['loop_start'] if loop_on else clip['hidden_loop_start']
    loop_end_beat = clip['loop_end'] if loop_on else clip['hidden_loop_end']
    loop_cue = None
    if loop_start_beat == start_beat:
        # assumes relative to first warp marker!
        loop_start_sec = get_seconds_relative_to_marker(
            first_from_warp, loop_start_beat)
        loop_end_sec = get_seconds_relative_to_marker(
            first_from_warp, loop_end_beat)
        loop_cue = Cue(loop_start_sec, loop_end_sec, loop_on, 'Start Loop')

    beat_grid_markers.sort(key=lambda x: x.sec_time)
    return BeatGridMarkersResult(beat_grid_markers, start_cue, loop_cue)


class TrackInfo(object):

    def __init__(self, beat_grid_markers, hot_cues, memory_cues):
        assert len(beat_grid_markers) > 0
        self.beat_grid_markers = beat_grid_markers
        self.hot_cues = hot_cues
        self.memory_cues = memory_cues

    @staticmethod
    def _add_cue(et_track, counter, cue):
        assert isinstance(cue, Cue)
        if cue.end is None:
            add_position_marker(et_track, cue.name, 0, counter, cue.start)
        else:
            add_position_marker(et_track, cue.name, 4,
                                counter, cue.start, cue.end)

    def add_to_track(self, et_track):
        et_track.set('AverageBpm', str(self.beat_grid_markers[0].bpm))
        for b in self.beat_grid_markers:
            add_beat_grid_marker(
                et_track=et_track, sec_time=b.sec_time, bpm=b.bpm, beat_time=b.beat_time)
        hot_cue_counter = 0
        for cue in self.hot_cues:
            self._add_cue(et_track, hot_cue_counter, cue)
            hot_cue_counter += 1
        for cue in self.memory_cues:
            self._add_cue(et_track, -1, cue)


def get_track_info(filename, record):
    clip = record['clip']
    bgm_result = get_beat_grid_markers(filename, clip)
    assert len(bgm_result.beat_grid_markers) > 0

    hot_cues = []
    memory_cues = []

    # There's always a start!
    hot_cues.append(bgm_result.start_cue)
    memory_cues.append(bgm_result.start_cue)

    # There's only a loop if it matched the start
    if bgm_result.loop_cue:
        hot_cues.append(bgm_result.loop_cue)
        memory_cues.append(bgm_result.loop_cue)

    # add memory notes
    for b in bgm_result.beat_grid_markers:
        if not b.memory_note:
            continue
        memory_cues.append(Cue(b.sec_time, None, False, b.memory_note))

    return TrackInfo(bgm_result.beat_grid_markers, hot_cues, memory_cues)


def get_als_track_info(filename, record):
    first_clip = record['clips'][0]
    first_sample = first_clip['sample']
    try:
        as_unicode = aa.get_sample_value_as_unicode(first_sample)
    except:
        print ('Some bullshit unicode')

    # prune to just those matching the first sample.  For now...
    clips_in_als_order = [c for c in record['clips'] if c['sample'] == first_sample]
    # (beat_grid_markers, start_seconds) sorted by start seconds
    bgm_results_in_als_order = [get_beat_grid_markers(filename, c) for c in clips_in_als_order]
    bgm_results_in_start_cue_order = sorted(bgm_results_in_als_order, key=lambda x: x.start_cue.start)

    beat_grid_markers = []
    for i, bgm_result in enumerate(bgm_results_in_start_cue_order):
        # track the next start seconds
        next_start = None
        if i + 1 < len(bgm_results_in_start_cue_order):
            next_start = bgm_results_in_start_cue_order[i + 1].start_cue.start
        previous_bgm = None
        for bgm in bgm_result.beat_grid_markers:
            # If this is at or before the last existing marker, assume we've
            # done our job right up to this point and we don't need it.
            if beat_grid_markers and bgm.sec_time <= beat_grid_markers[-1].sec_time:
                continue
            # If we've now strayed past the next start time, we don't want to
            # use this marker, but we do want to lay one down right before the
            # next start.
            if next_start is not None and bgm.sec_time >= next_start:
                # create a beat marker one beat before the next start
                if previous_bgm is not None:
                    shim_beat = get_beat_relative_to_marker(
                        previous_bgm, next_start) - 1.0
                    shim_seconds = get_seconds_relative_to_marker(
                        previous_bgm, shim_beat)
                    if shim_seconds > previous_bgm.sec_time:
                        shim_b = BeatGridMarker(
                            sec_time=shim_seconds, 
                            bpm=previous_bgm.bpm, 
                            beat_time=shim_beat)
                        beat_grid_markers.append(shim_b)
                # regardless of shim success, we're done with this clips
                # markers
                break
            # We want to use this marker.
            # TODO: the "beat_time" for this may be inconsistent.
            # Not sure how much that matters as it's only used mod 4.
            beat_grid_markers.append(bgm)
            previous_bgm = bgm
    # for m in beat_grid_markers:
    #     print ('  {}'.format(m))

    # Now set up all the hot cues
    # No memory cues right now for ALS?
    hot_cues = []
    memory_cues = []

    for bgm_result in bgm_results_in_als_order:
        if bgm_result.loop_cue and bgm_result.loop_cue.loop_on:
            hot_cues.append(bgm_result.loop_cue)
        else:
            hot_cues.append(bgm_result.start_cue)

    return TrackInfo(beat_grid_markers, hot_cues, memory_cues)



class PlaylistAdder(object):

    def __init__(self, file_to_id):
        self.playlists_added = 0
        self.file_to_id = file_to_id

    def add_playlist_for_files(self, et_parent, name, files, max_num=None):
        self.playlists_added += 1
        et_list = ET.SubElement(et_parent, 'NODE')
        et_list.set('Type', '1')
        et_list.set('Name', name)
        et_list.set('KeyType', '0')
        files_added = 0
        for f in files:
            try:
                track_id = self.file_to_id[f]
            except KeyError:
                continue
            et_track = ET.SubElement(et_list, 'TRACK')
            et_track.set('Key', str(track_id))
            files_added += 1
            if max_num is not None and files_added > max_num:
                break
        set_playlist_count(et_list)


def find_existing_samples(root_path):
    SAMPLE_EXTENSIONS = set(('.mp3', '.flac', '.mp4', '.aiff', '.wav'))
    # map from filename to path
    result = {}
    for dir_name, _, file_list in os.walk(root_path):
        for f in file_list:
            if os.path.splitext(f)[1] in SAMPLE_EXTENSIONS:
                result[f] = os.path.join(dir_name, f)
    return result


def relative_path(path_from, path_to):
    """
    path_from: /Volumes/rekordbox.xml
    path_to: /Volumes/somthing/stupid.mp3
    """
    path_from_full = os.path.dirname(os.path.abspath(path_from))
    path_to_full = os.path.abspath(path_to)
    common_prefix = os.path.commonprefix((path_from_full, path_to_full))
    to_rel = os.path.relpath(path_to_full, common_prefix)
    return to_rel


def export_rekordbox_xml(db_filename, rekordbox_filename,
                         bpm_folders=False, key_lists=False,
                         sample_root_path=None):
    export_rekordbox_history(db_filename)

    sample_dict = None
    if sample_root_path is not None:
        sample_dict = find_existing_samples(sample_root_path)
    else:
        export_rekordbox_samples(db_filename,
                                 sample_path=REKORDBOX_LOCAL_SAMPLE_PATH,
                                 sample_key=aa.REKORDBOX_LOCAL_SAMPLE_KEY,
                                 convert_flac=True,
                                 always_copy=True,
                                 )

    db_dict = aa.read_db_file(db_filename)
    files = aa.get_rekordbox_files(db_dict)
    files = aa.generate_date_plus_alc(files, db_dict)

    # testing filter
    #files = [f for f in files if 'Everything But The Girl - Lullaby Of Clubland.als' in f]
    #print (files)

    num_added = 0
    et_dj_playlists = ET.Element('DJ_PLAYLISTS')
    et_collection = ET.SubElement(et_dj_playlists, 'COLLECTION')
    file_to_id = {}
    files_with_id = []

    for f in files:
        record = db_dict[f]
        sample = aa.get_existing_rekordbox_sample(
            record, sample_key=aa.REKORDBOX_LOCAL_SAMPLE_KEY)
        if sample_dict is not None:
            sample = sample_dict.get(os.path.basename(sample))
        if sample is None:
            print ('Error getting sample for {}'.format(f))
            continue

        et_track = ET.SubElement(et_collection, 'TRACK')
        artist, track = aa.get_artist_and_track(f)

        # Optionally put [Vocal] in the track name
        suffixes = []

        if aa.is_vocal(record):
            suffixes.append('[Vocal]')

        # Put camelot key (7A) in the tag
        cam_key = aa.get_camelot_key(record['key'])
        if cam_key is not None:
            et_track.set('Tonality', cam_key)
            # [7=A]
            cam_num = int(cam_key[:-1])
            cam_ab = cam_key[-1:]
            suffixes.append('[{}={}]'.format(cam_num, cam_ab))
            # [7-A][6-A]
            cam_num_minus = aa.get_relative_camelot_key(cam_num, -1)
            suffixes.append('[{}-{}][{}-{}]'.format(cam_num, cam_ab, cam_num_minus, cam_ab))

        if suffixes:
            spaces = ' ' * 10
            track = '{}{}{}'.format(track, spaces, ' '.join(suffixes))

        # Evidently getting these as unicode is important for some
        et_track.set('Name', track.decode('utf-8'))
        et_track.set('Artist', artist.decode('utf-8'))
        sample_uri = 'file://localhost' + os.path.abspath(sample)
        et_track.set('Location', sample_uri)

        # number of plays (now in Comments field)
        num_plays = len(aa.get_ts_list(record))
        et_track.set('Comments', '{:03}'.format(num_plays))

        # alc
        et_track.set('DateAdded', aa.get_date_from_ts(aa.get_alc_ts(record)))

        # abuse album for random
        et_track.set('Album', str(random.randint(0, 2**31)))

        # Go back to just setting 20:00 for all tracks because it wants full
        # sample length
        et_track.set('TotalTime', str(60 * 20))

        # get track info and add
        if aa.is_alc_file(f):
            track_info = get_track_info(filename=f, record=record)
        elif aa.is_als_file(f):
            track_info = get_als_track_info(filename=f, record=record)
        else:
            raise RuntimeError('wtf: {}'.format(f))
        track_info.add_to_track(et_track)

        # finally record this track id
        et_track.set('TrackID', str(num_added))
        file_to_id[f] = num_added
        files_with_id.append(f)
        num_added += 1
    # this is great...add this at the end!
    et_collection.set('Entries', str(num_added))

    adder = PlaylistAdder(file_to_id)

    def get_bpm_name(bpm, bpm_range):
        return '{:03d} ({}) BPM'.format(bpm, bpm_range)

    def get_key_name(key):
        str_minor, str_major = aa.get_keys_for_camelot_number(key)
        return '{:02d} [{}, {}]'.format(key, str_minor, str_major)

    # now the playlists...
    et_playlists = ET.SubElement(et_dj_playlists, 'PLAYLISTS')
    et_root_node = add_folder(et_playlists, 'ROOT')


    ###################
    #######
    # version playlist as root
    et_version_node = add_folder(et_root_node, 'V{:02}'.format(VERSION))
    ###### ^

    def add_bpm_folder(et_parent_folder, bpm, bpm_range):
        folder_name = get_bpm_name(bpm, bpm_range)
        print(folder_name)

        et_bpm_folder = add_folder(et_parent_folder, folder_name)

        # all unfiltered
        if False:
            adder.add_playlist_for_files(et_bpm_folder, 'All BPM', files_with_id)

        # all for bpm (various orders)
        matching_files = get_filtered_files(db_dict=db_dict,
                                            files=files_with_id,
                                            bpm=bpm, bpm_range=bpm_range)
        # default order (touch)
        adder.add_playlist_for_files(
            et_bpm_folder, 'All (touch)', matching_files)
        if False:
            adder.add_playlist_for_files(
                et_bpm_folder, 'All (new)', aa.generate_alc(matching_files, db_dict))
            adder.add_playlist_for_files(
                et_bpm_folder, 'All (num)', aa.generate_num(matching_files, db_dict))
            adder.add_playlist_for_files(
                et_bpm_folder, 'All (recent)', aa.generate_recent(matching_files, db_dict))

        # for each key
        if key_lists:
            for key in xrange(1, 13):
                # (key, key+1)
                keys = [key, aa.get_relative_camelot_key(key, 1)]
                matching_files = get_filtered_files(db_dict=db_dict,
                                                    files=files_with_id,
                                                    bpm=bpm, bpm_range=bpm_range,
                                                    cam_num_list=keys)
                adder.add_playlist_for_files(
                    et_bpm_folder, get_key_name(key), matching_files)

    def get_bpm_and_range_list():
        # create tuples of (bpm, bpm_range) and sort them
        bpm_and_range = [(0, 0)]
        # fives all the way through
        for bpm in range(80, 161, 5):
            bpm_and_range.append((bpm, 5))
        # middle threes
        for bpm in range(114, 135, 2):
            bpm_and_range.append((bpm, 3))
        bpm_and_range.sort()
        return bpm_and_range

    def add_bpm_folders(et_filter_folder):
        # create tuples of (bpm, bpm_range) and sort them
        bpm_and_range = get_bpm_and_range_list()
        for bpm, bpm_range in bpm_and_range:
            add_bpm_folder(et_filter_folder, bpm, bpm_range)

    def add_bpm_playlists(et_filter_folder):
        bpm_and_range = get_bpm_and_range_list()
        for bpm, bpm_range in bpm_and_range:
            playlist_name = get_bpm_name(bpm, bpm_range)
            matching_files = get_filtered_files(db_dict=db_dict,
                                                files=files_with_id,
                                                bpm=bpm, bpm_range=bpm_range)
            adder.add_playlist_for_files(
                et_filter_folder, playlist_name, matching_files)

    def get_matching_files_from_list(list_file):
        l = aa.get_list_from_file(list_file, db_dict)
        return [f for _, f in l if f is not None and f in files_with_id]


    # all
    def add_all(parent):
        adder.add_playlist_for_files(parent, 'All', files_with_id)

    # top
    def add_top(parent):
        # Sets (aka hand history)
        adder.add_playlist_for_files(
            parent, 'Sets', aa.generate_sets(files=files, db_dict=db_dict), max_num=9999)

        # New Songs!
        adder.add_playlist_for_files(
            parent, 'New', aa.generate_alc(files_with_id, db_dict))
        
        # Recent (random)
        adder.add_playlist_for_files(
            parent, 'Random', aa.generate_random(aa.generate_recent(files_with_id, db_dict)))

        # Active list
        adder.add_playlist_for_files(parent, 'Active', get_matching_files_from_list(aa.ACTIVE_LIST))

        wedding_tags = [Tag.P_NASTY_TAG, Tag.SHANNON_TAG, Tag.DAN_TAG, Tag.PETER_PICKS_TAG]
        wedding_values = [x.value for x in wedding_tags]

        for tag_value in wedding_values:
            adder.add_playlist_for_files(parent, tag_value,
                get_filtered_files(db_dict=db_dict, files=files_with_id, tags=[tag_value]))

        # union
        adder.add_playlist_for_files(parent, "UNION",
            get_filtered_files(db_dict=db_dict, files=files_with_id, tags=wedding_values))



    # All
    et_all_folder = add_folder(et_version_node, "All")
    add_all(et_all_folder)

    # Top
    et_top_folder = add_folder(et_version_node, 'Top')
    add_top(et_top_folder)

    # Lists
    et_lists_folder = add_folder(et_version_node, 'Lists')
    name_to_file = aa.get_list_name_to_file(aa.LISTS_FOLDER)
    for name, list_file in sorted(name_to_file.iteritems()):
        matching_files = get_matching_files_from_list(list_file)
        adder.add_playlist_for_files(et_lists_folder, name, matching_files)

    # BPM
    if bpm_folders:
        et_filter_folder = add_folder(et_version_node, 'BPM Filter')
        add_bpm_folders(et_filter_folder)
    else:
        et_filter_folder = add_folder(et_version_node, 'BPM Filter')
        add_bpm_playlists(et_filter_folder)

    print ('Total playlists: {}'.format(adder.playlists_added))

    # finalize
    tree = ET.ElementTree(et_dj_playlists)
    tree.write(rekordbox_filename, encoding='utf-8', xml_declaration=True)
