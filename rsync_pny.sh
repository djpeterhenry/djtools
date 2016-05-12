#!/bin/sh
# 3601 is a daylight savings time hack
# not needed for new drive!
# except when DST starts again!
rsync -av --modify-window=3601 --delete /Users/peter/Music/Ableton/User\ Library /Volumes/PNY256GB/
