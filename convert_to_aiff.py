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



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input_filename')
    args = parser.parse_args()

    convert_filename(args.input_filename)
    
if __name__ == '__main__':
    main()


