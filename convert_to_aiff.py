#!/usr/bin/env python

import os
import argparse
import subprocess

def convert_filename(input_filename):
    base, extension = os.path.splitext(input_filename)
    output_filename = base + " (from {})".format(extension) + ".aiff"
    cmd = ['ffmpeg',
        '-i', input_filename,
        "-map_metadata", "0", # doesn't preserve tags as it should
        output_filename
    ]
    subprocess.check_call(cmd)

def convert_folder(input_folder):
    for filename in os.listdir(input_folder):
        if os.path.splitext(filename)[1].lower() != ".mp3":
            continue
        convert_filename(filename)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_filename')
    parser.add_argument('--input_folder')
    args = parser.parse_args()

    if args.input_filename:
        convert_filename(args.input_filename)

    if args.input_folder:
        convert_folder(args.input_folder)
    
if __name__ == '__main__':
    main()


