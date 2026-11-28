#!/usr/bin/env python3.11

import os
import subprocess

import argh

import ableton_aid as aa
from db_types import Record


def _seconds_label(seconds: float) -> str:
    """'5s' for whole numbers, '5.5s' otherwise."""
    if float(seconds).is_integer():
        return "{}s".format(int(seconds))
    return "{}s".format(seconds)


# Where Ableton keeps its decodes of compressed samples (mp3, m4a, ...).
ABLETON_DECODING_CACHE = os.path.expanduser("~/Library/Caches/Ableton/Cache/Decoding")

# Formats Ableton plays directly, sample for sample as ffmpeg decodes them.
PCM_EXTENSIONS = (".wav", ".aif", ".aiff")


def _sample_count(path: str) -> int | None:
    """Length of the first audio stream in samples, from ffprobe."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                "stream=duration_ts", "-of", "csv=p=0", path,
            ]
        )
        return int(out.decode("utf8").strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def _ableton_audio(alc_filename: str, sample_filepath: str) -> str | None:
    """
    The audio as Ableton sees it, so that warp marker times (SecTime) line up.

    PCM files are used as they are.  Compressed files are not: ffmpeg and Ableton
    decode an mp3 to different starts (ffmpeg trims the encoder delay, Ableton
    keeps it and adds a frame for the LAME header), so the warp markers would land
    tens of milliseconds late.  Use Ableton's own decode from its cache instead,
    checked against the clip's DefaultDuration so a stale or same-named file is
    never picked up.
    """
    if os.path.splitext(sample_filepath)[1].lower() in PCM_EXTENSIONS:
        return sample_filepath

    xml_duration = aa.alc_to_xml(alc_filename).find(".//AudioClip/SampleRef/DefaultDuration")
    expected = None if xml_duration is None else int(float(xml_duration.get("Value", "0")))
    name = os.path.splitext(os.path.basename(sample_filepath))[0] + ".wav"
    cached = os.path.join(ABLETON_DECODING_CACHE, name)
    if expected and os.path.isfile(cached) and _sample_count(cached) == expected:
        return cached

    print(
        f"{os.path.basename(sample_filepath)} is compressed, and Ableton's decode of it "
        f"({cached}) is missing or doesn't match the clip's length ({expected} samples).\n"
        f"Open {alc_filename} in Ableton once so it decodes the file, then run this again."
    )
    return None


def silence(alc_filename: str, seconds: float = 5.0) -> None:
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

    sample_filepath = os.path.abspath(audioclip["sample"])
    if not os.path.isfile(sample_filepath):
        print(f"Sample file {sample_filepath} does not exist.")
        return

    # Prepend the silence to the audio Ableton actually plays.
    source_filepath = _ableton_audio(alc_filename, sample_filepath)
    if source_filepath is None:
        return
    if source_filepath != sample_filepath:
        print(f"Using Ableton's decode: {source_filepath}")

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
        source_filepath,
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
    new_record: Record = {}
    aa.transfer_shared_record_fields(record, new_record)
    db_dict[new_alc_filename] = new_record
    aa.write_db_file(db_dict)
    print(f"Added to database: {new_alc_filename}")


if __name__ == "__main__":
    argh.dispatch_command(silence)
