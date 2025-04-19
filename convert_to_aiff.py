#!/usr/bin/env python3.11

import os
import subprocess
import argh


def convert_filename(input_filename, pcm_16bit=False):
    base, extension = os.path.splitext(input_filename)
    output_filename = base + " (from {})".format(extension) + ".aiff"
    cmd = [
        "ffmpeg",
        "-i",
        input_filename,
        "-map_metadata",
        "0",  # doesn't preserve tags as it should
    ]
    if pcm_16bit:
        cmd.extend(["-c:a", "pcm_s16le"])  # Specify 16-bit PCM encoding
    cmd.append(output_filename)
    subprocess.check_call(cmd)


def convert_folder(input_folder, pcm_16bit=False):
    for filename in os.listdir(input_folder):
        if os.path.splitext(filename)[1].lower() != ".mp3":
            continue
        convert_filename(os.path.join(input_folder, filename), pcm_16bit=pcm_16bit)


@argh.arg("--input-filename", help="Path to the input file to convert")
@argh.arg("--input-folder", help="Path to the folder containing files to convert")
@argh.arg("--pcm-16bit", help="Convert output to 16-bit PCM", default=False)
def main(input_filename=None, input_folder=None, pcm_16bit=False):
    if input_filename:
        convert_filename(input_filename, pcm_16bit=pcm_16bit)

    if input_folder:
        convert_folder(input_folder, pcm_16bit=pcm_16bit)


if __name__ == "__main__":
    argh.dispatch_command(main)
