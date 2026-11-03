# app_entry.py - Entry point cho pynsist installer
# File này sẽ được copy vào pkgs/ và launch script sẽ import từ đây

import sys
import os

# Thêm thư mục cài đặt (chứa main.py, config.py, ...) vào sys.path
# __file__ sẽ là .../pkgs/app_entry.py khi cài đặt
pkgs_dir = os.path.dirname(os.path.abspath(__file__))
installdir = os.path.dirname(pkgs_dir)  # thư mục gốc cài đặt
sys.path.insert(0, installdir)

# Gọi main thực sự
from main import main

if __name__ == '__main__':
    main()