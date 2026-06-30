#!/usr/bin/env python3.11

import os
import subprocess

import argh

import ableton_aid as aa


def _seconds_label(seconds):
    """'5s' for whole numbers, '5.5s' otherwise."""
    if float(seconds).is_integer():
        return "{}s".format(int(seconds))
    return "{}s".format(seconds)


def silence(alc_filename, seconds: float = 5.0):
    """
    Create a Rekordbox-ready copy of a song with `seconds` of silence prepended
    to the audio and every warp marker shifted forward to compensate.

    Use this when a song's beat grid starts before the beginning of the audio
    file (a negative start time, which Rekordbox can't represent).  The silence
    pushes the start positive while staying aligned to your existing warp markers.

    Works on .alc clips and .als sets.  An .als can contain multiple audio clips,
    but only the first clip is handled (a warning is printed in that case).

    Run this from the same folder you run actions.py from (next to database.json).
    """
    if seconds <= 0:
        print("seconds must be positive")
        return

    db_dict = aa.read_db_file()
    record = db_dict.get(alc_filename)
    if not record:
        print(f"File {alc_filename} not found in the database.")
        return

    ext = os.path.splitext(alc_filename)[1]
    if ext not in (".alc", ".als"):
        print(f"Input file {alc_filename} is not an .alc or .als file.")
        return

    if ext == ".als":
        print(
            f"Warning: {alc_filename} is an .als set; only its first audio clip "
            f"will be silenced and re-warped."
        )

    # We need the new sample-path format to be able to write a new .alc file.
    audioclip = aa.get_audioclip_from_alc(alc_filename)
    if audioclip is None:
        print(f"Could not read an audio clip from {alc_filename}.")
        return
    if not audioclip.get("sample_filepath_is_new_format"):
        print(
            f"Input ableton file {alc_filename} does not have sample_filepath_is_new_format."
        )
        return

    sample_filepath = os.path.abspath(record["clip"]["sample"])
    if not os.path.isfile(sample_filepath):
        print(f"Sample file {sample_filepath} does not exist.")
        return

    label = _seconds_label(seconds)

    # New audio file next to the original sample, always .aiff.
    sample_base, _ = os.path.splitext(sample_filepath)
    new_sample_path = f"{sample_base} ({label} silence).aiff"

    # Prepend silence.  adelay pads the start of every channel with silence.
    delay_ms = int(round(seconds * 1000))
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        sample_filepath,
        "-af",
        f"adelay={delay_ms}:all=1",
        new_sample_path,
    ]
    subprocess.check_call(cmd)
    assert os.path.isfile(new_sample_path)
    print(f"Wrote silenced sample: {new_sample_path}")

    # New .alc/.als next to the original, with warp markers shifted forward.
    new_alc_filename = os.path.splitext(alc_filename)[0] + f" ({label} silence){ext}"
    ok = aa.write_silenced_alc(
        alc_filename=alc_filename,
        new_alc_filename=new_alc_filename,
        new_sample_path=new_sample_path,
        sec_offset=seconds,
    )
    if not ok:
        print(f"Failed to write new alc file for {alc_filename}.")
        return

    # Add a record for the new song, carrying over metadata and tags.
    new_record = {}
    aa.transfer_shared_record_fields(record, new_record)
    db_dict[new_alc_filename] = new_record
    aa.write_db_file(db_dict)
    print(f"Added to database: {new_alc_filename}")


if __name__ == "__main__":
    argh.dispatch_command(silence)
