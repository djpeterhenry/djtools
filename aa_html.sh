#!/bin/sh
cd $SONG_PATH
ableton_aid.py aadb.txt -html_sets > sets.html
ableton_aid.py aadb.txt -html_list > list.html
ableton_aid.py aadb.txt -html_list_num > list_num.html
ableton_aid.py aadb.txt -html_list_sample > list_sample.html
ableton_aid.py aadb.txt -html_list_alc > list_alc.html
cp *.html ~/dropbox/DJ\ Peter\ Henry/
