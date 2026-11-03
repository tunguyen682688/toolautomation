# Custom launch script for pynsist
# Adds both installdir and pkgs to sys.path

import sys
import os
import site

scriptdir, script = os.path.split(os.path.abspath(__file__))
installdir = scriptdir
pkgdir = os.path.join(scriptdir, 'pkgs')

# Add BOTH installdir (for app_entry.py) AND pkgs (for dependencies)
sys.path.insert(0, installdir)
sys.path.insert(0, pkgdir)
site.addsitedir(pkgdir)
os.environ['PYTHONPATH'] = installdir + os.pathsep + pkgdir + os.pathsep + os.environ.get('PYTHONPATH', '')

appdata = os.environ.get('APPDATA', None) or os.path.expanduser('~')

if 'pythonw' in sys.executable:
    kw = {'errors': 'replace'} if (sys.version_info[0] >= 3) else {}
    sys.stdout = sys.stderr = open(os.path.join(appdata, script+'.log'), 'w', **kw)
else:
    def excepthook(etype, value, tb):
        import traceback
        traceback.print_exception(etype, value, tb)
        with open(os.path.join(appdata, script+'.log'), 'w') as f:
            traceback.print_exception(etype, value, tb, file=f)
    sys.excepthook = excepthook


if __name__ == '__main__':
    from app_entry import main
    main()