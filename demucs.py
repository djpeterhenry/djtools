#!/usr/bin/env python3.11

import argh
import subprocess

def demucs(input_filename, output_base_folder):
    command = [
        "demucs",
        "-d", "cpu",
        input_filename,
        "--out", output_base_folder,
    ]
    try:
        subprocess.run(command, check=True)
        print(f"Demucs processing completed for {input_filename}. Output saved to {output_base_folder}.")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while processing {input_filename}: {e}")

if __name__ == "__main__":
    argh.dispatch_command(demucs)