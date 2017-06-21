#!/bin/sh
# 3601 is a daylight savings time hack
rsync -av --modify-window=3601 --delete "${PROJECT_PATH}" /Volumes/PNY256GB/
rsync -av "${DJTOOLS_PATH}" /Volumes/PNY256GB/
