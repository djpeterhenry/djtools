# I think the idea here was to export the entire library as MP3
# I haven't done this in forever and I don't expect to either.
# However it might be fun to do again at some point??

MP3_SAMPLE_PATH = u"/Volumes/music/mp3_samples/"

def action_export_mp3_samples(args):
    db_dict = read_db_file()
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
    write_db_file(db_dict)
