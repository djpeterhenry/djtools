#!/bin/sh
# this makes it work in automator when .bash_profile exports the right variables and paths
source ~/.bash_profile

cd "$SONG_PATH"
ableton_gui.py "$@" &
