# -*- mode: python ; coding: utf-8 -*-
"""KhoPhongCanHo.spec - cấu hình đóng gói bản build Windows bằng PyInstaller.

Chạy:  pyinstaller --clean KhoPhongCanHo.spec
Kết quả: dist/KhoPhongCanHo/KhoPhongCanHo.exe  (thư mục đi kèm -> mở nhanh, dễ cập nhật)

Ghi chú:
- Không dùng --onefile vì PySide6 giải nén ~200MB mỗi lần mở -> mở chậm ~8-15s.
  Bản onedir mở trong ~1-2s và vẫn là "1 thư mục copy là chạy".
- Thư mục dữ liệu (data/), cấu hình (config/) được TẠO BÊN CẠNH file exe.
"""

import sys

block_cipher = None

# --- thư viện Google chỉ được import lỏng lẻo (trong hàm) -> phải khai báo tường minh ---
HIDDEN = [
    "googleapiclient",
    "googleapiclient.discovery",
    "googleapiclient.http",
    "googleapiclient.errors",
    "google.oauth2",
    "google.oauth2.service_account",
    "google.auth",
    "google.auth.transport",
    "google.auth.transport.requests",
    "google.auth.transport.urllib3",
    "google.auth.exceptions",
    "google_auth_httplib2",
    "httplib2",
    # openpyxl đọc/ghi Excel
    "openpyxl",
    "openpyxl.workbook",
    "openpyxl.worksheet",
    "openpyxl.styles",
    "openpyxl.utils",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("samples", "samples")],          # dữ liệu mẫu đi kèm bản build
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # loại module không dùng tới -> giảm dung lượng đáng kể
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtUiTools",
        "PySide6.QtHelp", "PySide6.QtNetworkAuth", "PySide6.QtRemoteObjects",
        "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
        "PySide6.QtTextToSpeech", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
        "PySide6.QtXml", "PySide6.QtBluetooth", "PySide6.QtNfc",
        "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtPassthroughCamera",
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtQuickWidgets",
        "PySide6.QtLabsAnimation", "PySide6.QtLabsPlatform", "PySide6.QtLabsSettings",
        "PySide6.QtLabsSharedImage", "PySide6.QtLabsWaveformScene",
        "tkinter", "matplotlib", "numpy", "pandas", "PIL",
        "pytest", "IPython", "setuptools", "distutils",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KhoPhongCanHo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # ứng dụng GUI -> không hiện cửa sổ console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="KhoPhongCanHo",          # dist/KhoPhongCanHo/
)
