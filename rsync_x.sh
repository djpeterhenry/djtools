#!/bin/sh
# 3601 is a daylight savings time hack
# not needed for new drive!
# except when DST starts again!

# --delete was brutal when you targeted home folder, say
#rsync -av --modify-window=3601 --delete "${PROJECT_PATH}" $1
