import nsist.configreader as cr
import os

cfg = cr.read_and_validate('installer.cfg')
pairs = cr.read_extra_files(cfg)
for f, d in pairs:
    print(f'File: "{f}" -> Dest: {d} | Exists: {os.path.exists(f)}')