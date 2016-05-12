#!/usr/bin/env python

import sys
import os
import os.path
import shutil

########################################################################
if __name__ == '__main__':
    argv_iter = iter(sys.argv)
    _ = argv_iter.next()
    
    playlist_filename = argv_iter.next()
    output_folder = argv_iter.next()
    
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    for filename in [x.strip() for x in open(playlist_filename).readlines()]:
        print filename
        output_filename = os.path.join(output_folder, os.path.basename(filename))
        shutil.copyfile(filename, output_filename)
        
