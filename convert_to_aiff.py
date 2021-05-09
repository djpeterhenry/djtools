#!/usr/bin/env python

import os
import argparse
import subprocess

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input_filename')
    args = parser.parse_args()

    input_filename = args.input_filename
    base, extension = os.path.splitext(input_filename)
    output_filename = base + " (from {})".format(extension) + ".aiff"

    cmd = ['ffmpeg', '-i', input_filename, output_filename]
    subprocess.check_call(cmd)
    
if __name__ == '__main__':
    main()


