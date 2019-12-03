from __future__ import print_function

import os
import subprocess
import shutil
import xml.etree.ElementTree as ET
import random

import ableton_aid as aa

VERSION = 43

REKORDBOX_SAMPLE_PATH = u'/Volumes/MacHelper/rekordbox_samples'
REKORDBOX_SAMPLE_KEY = 'rekordbox_sample'

REKORDBOX_LOCAL_SAMPLE_PATH = u'/Users/peter/Music/PioneerDJ/LocalSamples'
REKORDBOX_LOCAL_SAMPLE_KEY = 'rekordbox_local_sample'


def export_rekordbox_samples(db_filename, sample_path, sample_key, always_copy, convert_flac):
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
        print ('Checking sample:', f)
        sample = aa.get_sample_unicode(record)
        if sample is None:
            print ('Failed to get sample for {}'.format(f))
            continue
        _, sample_ext = os.path.splitext(sample)
        # convert flac and mp4 (could be video)
        if sample_ext.lower() in extensions_to_convert:
            target = aa.get_export_sample_path(f, '.aiff', sample_path)
            if not os.path.exists(target):
                cmd = ['ffmpeg', '-i', sample, target]
                subprocess.check_call(cmd)
        # copy others
        elif always_copy:
            target = aa.get_export_sample_path(f, sample_ext, sample_path)
            if not os.path.exists(target):
                shutil.copy(sample, target)
        else:
            target = sample.encode('utf-8')
        assert os.path.exists(target)
        record[sample_key] = target.decode('utf-8')
    aa.write_db_file(db_filename, db_dict)


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


def get_seconds_relative_to_marker(ref_marker, beat):
    return get_seconds_for_beat(ref_marker.beat_time, ref_marker.sec_time, beat, ref_marker.bpm)


def set_folder_count(et):
    et.set('Count', str(len(et.getchildren())))


def set_playlist_count(et):
    et.set('Entries', str(len(et.getchildren())))


def add_folder(et_parent, name):
    result = ET.SubElement(et_parent, 'NODE')
    result.set('Type', '0')
    result.set('Name', name)
    return result


def get_filtered_files(db_dict, files, bpm, bpm_range, cam_num_list, vocal):
    """
    bpm can be None
    cam_num_list can be None
    vocal can be None
    """
    matching_files = []
    for f in files:
        record = db_dict[f]
        if bpm is not None and not aa.matches_bpm_filter(bpm, bpm_range, record['bpm']):
            continue
        cam_num = aa.get_camelot_num(record['key'])
        if cam_num_list is not None and cam_num not in cam_num_list:
            continue
        if vocal is not None:
            if vocal and not aa.is_vocal(record):
                continue
            if not vocal and aa.is_vocal(record):
                continue
        matching_files.append(f)
    return matching_files


class BeatGridMarker(object):

    def __init__(self, sec_time, bpm, beat_time, memory_note=None):
        self.sec_time = sec_time
        self.bpm = bpm
        self.beat_time = beat_time
        self.memory_note = memory_note

    def set_memory_note(self, memory_note):
        self.memory_note = memory_note


def get_beat_grid_markers(clip):
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
    start_seconds = get_seconds_relative_to_marker(first_from_warp, start_beat)

    # make sure we have beat grid back to the start if before the first warp marker
    if start_beat < first_from_warp.beat_time:
        first_from_warp.set_memory_note('Beat 1')
        beat_grid_markers.append(BeatGridMarker(
            sec_time=start_seconds, bpm=first_bpm, beat_time=start_beat))

    beat_grid_markers.sort(key=lambda x: x.sec_time)
    return beat_grid_markers, start_seconds


class Cue(object):

    def __init__(self, start, end, name):
        self.start = start
        self.end = end
        self.name = name


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

# TODO: make one of these for ALS files
def get_track_info(record):
    clip = record['clip']
    beat_grid_markers, start_seconds = get_beat_grid_markers(clip)
    assert len(beat_grid_markers) > 0

    hot_cues = []
    memory_cues = []

    first_marker = beat_grid_markers[0]

    start_cue = Cue(start_seconds, None, 'Start')
    hot_cues.append(start_cue)
    memory_cues.append(start_cue)

    # memory and hot cues for loop as well
    loop_start_beat = clip['hidden_loop_start']
    loop_end_beat = clip['hidden_loop_end']
    # This assumes the loop is relative to the first marker (safe usually)
    loop_start_sec = get_seconds_relative_to_marker(
        first_marker, loop_start_beat)
    loop_end_sec = get_seconds_relative_to_marker(
        first_marker, loop_end_beat)
    loop_cue = Cue(loop_start_sec, loop_end_sec, 'Start Loop')
    hot_cues.append(loop_cue)
    memory_cues.append(loop_cue)

    # add memory notes
    for b in beat_grid_markers:
        if not b.memory_note:
            continue
        memory_cues.append(Cue(b.sec_time, None, b.memory_note))

    return TrackInfo(beat_grid_markers, hot_cues, memory_cues)


def get_als_track_info(record):
    clips = [get_beat_grid_markers(clip) for clip in record['clips']]
    clips.sort(key=lambda x: x[1])
    beat_grid_markers = []
    for i, clip in enumerate(clips):
        next_start = None
        if i + 1 < len(clips):
            _, next_start = clips[i + 1]
        for b in clip[0]:
            if beat_grid_markers and b.sec_time < beat_grid_markers[-1].sec_time:
                continue
            if next_start is not None and b.sec_time >= next_start:
                break
            # TODO: modfy?
            beat_grid_markers.append(b)
    print (beat_grid_markers)



class PlaylistAdder(object):

    def __init__(self, file_to_id):
        self.playlists_added = 0
        self.file_to_id = file_to_id

    def add_playlist_for_files(self, et_parent, name, files):
        self.playlists_added += 1
        et_list = ET.SubElement(et_parent, 'NODE')
        et_list.set('Type', '1')
        et_list.set('Name', name)
        et_list.set('KeyType', '0')
        for f in files:
            et_track = ET.SubElement(et_list, 'TRACK')
            et_track.set('Key', str(self.file_to_id[f]))
        set_playlist_count(et_list)


def export_rekordbox_xml(db_filename, rekordbox_filename, is_for_usb):
    if is_for_usb:
        export_rekordbox_samples(db_filename,
                                 sample_path=REKORDBOX_SAMPLE_PATH,
                                 sample_key=REKORDBOX_SAMPLE_KEY,
                                 always_copy=True,
                                 convert_flac=True)
    else:
        export_rekordbox_samples(db_filename,
                                 sample_path=REKORDBOX_LOCAL_SAMPLE_PATH,
                                 sample_key=REKORDBOX_LOCAL_SAMPLE_KEY,
                                 always_copy=False,
                                 convert_flac=False)

    db_dict = aa.read_db_file(db_filename)
    files = aa.get_valid_alc_files(db_dict)
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
        if not aa.use_for_rekordbox(record):
            continue
        if is_for_usb:
            sample = aa.get_existing_rekordbox_sample(
                record, sample_key=REKORDBOX_SAMPLE_KEY)
        else:
            sample = aa.get_existing_rekordbox_sample(
                record, sample_key=REKORDBOX_LOCAL_SAMPLE_KEY)
        if sample is None:
            print ('Error getting sample for {}'.format(f))
            continue

        et_track = ET.SubElement(et_collection, 'TRACK')
        artist, track = aa.get_artist_and_track(f)

        # Optionally put [Vocal] in the track name
        if aa.is_vocal(record):
            track = '{} [Vocal]'.format(track)

        # Put camelot key in track name
        cam_key = aa.get_camelot_key(record['key'])
        if cam_key:
            et_track.set('Tonality', cam_key)
            track = '{} [{}]'.format(track, cam_key)

        # Evidently getting these as unicode is important for some
        et_track.set('Name', track.decode('utf-8'))
        et_track.set('Artist', artist.decode('utf-8'))
        sample_uri = 'file://localhost' + os.path.abspath(sample)
        et_track.set('Location', sample_uri)

        # number of plays
        num_plays = len(aa.get_ts_list(record))
        et_track.set('PlayCount', str(num_plays))

        # alc
        et_track.set('DateAdded', aa.get_date_from_ts(aa.get_alc_ts(record)))

        # abuse comment for alc+date
        et_track.set('Comments', aa.get_date_from_ts(
            aa.get_alc_or_last_ts(record)))

        # abuse album for random
        et_track.set('Album', str(random.randint(0, 2**31)))

        # Go back to just setting 20:00 for all tracks because it wants full
        # sample length
        et_track.set('TotalTime', str(60 * 20))

        # get track info and add
        track_info = get_track_info(record)
        track_info.add_to_track(et_track)

        if aa.is_als_file(f):
            track_info = get_als_track_info(record)

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

    # version playlist as root
    et_version_node = add_folder(et_root_node, 'V{:02}'.format(VERSION))

    # playlist for all
    adder.add_playlist_for_files(et_version_node, 'All (touch)', files_with_id)
    adder.add_playlist_for_files(
        et_version_node, 'All (new)', aa.generate_alc(files_with_id, db_dict))
    adder.add_playlist_for_files(
        et_version_node, 'All (num)', aa.generate_num(files_with_id, db_dict))
    adder.add_playlist_for_files(
        et_version_node, 'All (random)', aa.generate_random(files_with_id))

    def add_bpm_folder(et_parent_folder, bpm, bpm_range):
        folder_name = get_bpm_name(bpm, bpm_range)
        print(folder_name)

        et_bpm_folder = add_folder(et_parent_folder, folder_name)

        # all unfiltered
        adder.add_playlist_for_files(et_bpm_folder, 'All BPM', files_with_id)

        # all for bpm (various orders)
        matching_files = get_filtered_files(db_dict=db_dict,
                                            files=files_with_id,
                                            bpm=bpm, bpm_range=bpm_range,
                                            cam_num_list=None,
                                            vocal=False)
        # default order (touch)
        adder.add_playlist_for_files(
            et_bpm_folder, 'All (touch)', matching_files)
        adder.add_playlist_for_files(
            et_bpm_folder, 'All (new)', aa.generate_alc(matching_files, db_dict))
        adder.add_playlist_for_files(
            et_bpm_folder, 'All (num)', aa.generate_num(matching_files, db_dict))
        adder.add_playlist_for_files(
            et_bpm_folder, 'All (random)', aa.generate_random(matching_files))

        # vocal for bpm (default order)
        matching_files = get_filtered_files(db_dict=db_dict,
                                            files=files_with_id,
                                            bpm=bpm, bpm_range=bpm_range,
                                            cam_num_list=None,
                                            vocal=True)
        adder.add_playlist_for_files(et_bpm_folder, 'Vocal', matching_files)

        # for each key
        for key in xrange(1, 13):
            # (key, key+1)
            keys = [key, aa.get_relative_camelot_key(key, 1)]
            matching_files = get_filtered_files(db_dict=db_dict,
                                                files=files_with_id,
                                                bpm=bpm, bpm_range=bpm_range,
                                                cam_num_list=keys,
                                                vocal=False)
            adder.add_playlist_for_files(
                et_bpm_folder, get_key_name(key), matching_files)

    def add_bpm_folders(et_filter_folder):
        # create tuples of (bpm, bpm_range) and sort them
        bpm_and_range = [(0, 0)]
        for bpm in range(116, 141, 2):
            bpm_and_range.append((bpm, 3))
        for bpm in range(80, 161, 5):
            bpm_and_range.append((bpm, 5))
        bpm_and_range.sort()
        for bpm, bpm_range in bpm_and_range:
            add_bpm_folder(et_filter_folder, bpm, bpm_range)

    ##########
    # Lists
    et_lists_folder = add_folder(et_version_node, 'Lists')
    name_to_file = aa.get_list_name_to_file(aa.LISTS_FOLDER)
    for name, list_file in sorted(name_to_file.iteritems()):
        l = aa.get_list_from_file(list_file, db_dict)
        matching_files = [
            f for _, f in l if f is not None and f in files_with_id]
        adder.add_playlist_for_files(et_lists_folder, name, matching_files)

    # BPM
    et_filter_folder = add_folder(et_version_node, 'BPM Filter')
    add_bpm_folders(et_filter_folder)

    print ('Total playlists: {}'.format(adder.playlists_added))

    # finalize
    tree = ET.ElementTree(et_dj_playlists)
    tree.write(rekordbox_filename, encoding='utf-8', xml_declaration=True)
