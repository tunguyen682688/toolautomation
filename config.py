# -*- coding: utf-8 -*-
"""config.py - Đường dẫn thư mục + lưu cấu hình ứng dụng (file JSON, không hardcode secret trong mã nguồn).

Bí mật Google (service account JSON) chỉ được trỏ bằng ĐƯỜNG DẪN file trong config/settings.json.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

if getattr(sys, "frozen", False):
    # bản build (.exe) -> dữ liệu / cấu hình nằm CẠNH file exe (ghi được, không bị xóa khi đóng app)
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))   # file đọc-đi-kèm (samples)
else:
    BASE_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = BASE_DIR

# ------------------------------------------------------------------ MÔI TRƯỜNG
# 3 môi trường riêng biệt, mỗi env có data/ và settings riêng:
#   dev     - phát triển (mặc định khi chạy từ nguồn: python main.py)
#   staging - kiểm thử trước khi đưa vào sử dụng thật
#   prod    - sản xuất (mặc định khi chạy bản build .exe)
# Chọn:  python main.py --env staging   hoặc   KhoPhongCanHo.exe --env staging
#        (hoặc biến môi trường KHO_APP_ENV=staging)
VALID_ENVS = ("dev", "staging", "prod")
DEFAULT_ENV = "prod" if getattr(sys, "frozen", False) else "dev"


def _resolve_env() -> str:
    """Đọc môi trường: --env <ten> > biến KHO_APP_ENV > mặc định theo chế độ chạy."""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--env" and i + 1 < len(argv):
            v = argv[i + 1].strip().lower()
            return v if v in VALID_ENVS else DEFAULT_ENV
        if a.startswith("--env="):
            v = a.split("=", 1)[1].strip().lower()
            return v if v in VALID_ENVS else DEFAULT_ENV
    v = (os.environ.get("KHO_APP_ENV") or "").strip().lower()
    return v if v in VALID_ENVS else DEFAULT_ENV


APP_ENV = _resolve_env()

# ------------------------------------------------------------------ ĐƯỜNG DẪN (theo env)
# Các đường dẫn này được tính khi import; DB thực tế dùng settings.get("db_path")
# Thư mục logs/cache/theo dõi db_path -> dùng get_data_dir() lúc runtime.
DATA_DIR = BASE_DIR / "data" / APP_ENV          # data/dev, data/staging, data/prod (mặc định)
CONFIG_DIR = BASE_DIR / "config"
LOG_DIR = DATA_DIR / "logs"
CACHE_DIR = DATA_DIR / "cache"
SAMPLES_DIR = BUNDLE_DIR / "samples"
SETTINGS_FILE = CONFIG_DIR / f"settings_{APP_ENV}.json"
DB_FILE = DATA_DIR / "kho_phong.db"

# đường dẫn của phiên bản CŨ (trước khi tách môi trường) -> dùng để migrate 1 lần
LEGACY_DB_FILE = BASE_DIR / "data" / "kho_phong.db"
LEGACY_SETTINGS_FILE = CONFIG_DIR / "settings.json"


def _data_dir_from_db_path(db_path: str) -> Path:
    """Tính thư mục dữ liệu (chứa logs, cache, backup) từ đường dẫn file DB."""
    return Path(db_path).parent


def get_data_dir() -> Path:
    """Thư mục dữ liệu hiện tại (theo setting db_path, fallback DATA_DIR)."""
    from config import get_settings
    s = get_settings()
    return _data_dir_from_db_path(s.get("db_path"))


def get_log_dir() -> Path:
    return get_data_dir() / "logs"


def get_cache_dir() -> Path:
    return get_data_dir() / "cache"


def _migrate_legacy() -> None:
    """Di chuyển dữ liệu phiên bản cũ (data/kho_phong.db, config/settings.json)
    vào môi trường mặc định — chỉ khi đang ở env mặc định và env đích chưa có dữ liệu."""
    if APP_ENV != DEFAULT_ENV:
        return                                   # env do người dùng chọn -> không tự chuyển
    try:
        if LEGACY_DB_FILE.exists() and not DB_FILE.exists():
            import shutil
            DB_FILE.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("", "-wal", "-shm"):  # kèm file phụ của SQLite
                src = Path(str(LEGACY_DB_FILE) + suffix)
                if src.exists():
                    shutil.move(str(src), str(DB_FILE) + suffix)
        if LEGACY_SETTINGS_FILE.exists() and not SETTINGS_FILE.exists():
            import shutil
            shutil.move(str(LEGACY_SETTINGS_FILE), str(SETTINGS_FILE))
    except OSError:
        pass                                     # migrate thất bại -> dữ liệu cũ vẫn nguyên vẹn


for _d in (DATA_DIR, CONFIG_DIR, LOG_DIR, CACHE_DIR, SAMPLES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

_migrate_legacy()


def env_badge() -> str:
    """Nhãn môi trường hiển thị trên UI: DEV / STAGING / PROD."""
    return APP_ENV.upper()


def is_prod() -> bool:
    return APP_ENV == "prod"

DEFAULTS: Dict[str, Any] = {
    # --- người dùng / hiển thị ---
    "user_name": "Admin",
    "language": "vi",
    "page_size": 500,
    "auto_save": True,
    "confirm_delete": True,
    "ui_theme": "dark",              # dark | light (giao diện 2 chế độ)
    # --- đồng bộ Google ---
    "google_enabled": False,
    "credentials_file": "",           # ví dụ: config/service_account.json (KHÔNG chứa trong mã nguồn)
    "spreadsheet_id": "",
    "rooms_sheet": "Kho Hàng Phòng Trống",
    "buildings_sheet": "Danh Mục Địa Điểm & Chủ Nhà",
    "stats_sheet": "Thống Kê Nhanh",
    "map_sheet": "App_ID_Map",
    "auto_sync": True,
    "sync_interval_sec": 60,
    "batch_size": 400,
    "request_timeout": 30,
    "lock_lease_sec": 60,
    # --- Excel ---
    "last_import_dir": "",
    "last_export_dir": "",
    # --- đường dẫn ---
    "db_path": str(DB_FILE),
    "media_root": "Data Image",       # gốc thư mục ảnh/video phòng (tương đối -> cạnh app)
}


class Settings:
    """Đọc/ghi settings.json (thread-safe, ghi atomic)."""

    def __init__(self, path: Path = SETTINGS_FILE):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------ IO
    def load(self) -> None:
        with self._lock:
            data = {}
            if self.path.exists():
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            self._data = dict(DEFAULTS)
            self._data.update(data or {})

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    # ------------------------------------------------------------------ API
    def get(self, key: str, default=None) -> Any:
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with self._lock:
            self._data[key] = value
            if save:
                self.save()

    def update(self, values: Dict[str, Any], save: bool = True) -> None:
        with self._lock:
            self._data.update(values)
            if save:
                self.save()

    def all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)

    # ------------------------------------------------------------------ helpers
    @property
    def google_ready(self) -> bool:
        """True khi đã cấu hình đầy đủ để đồng bộ Google Sheets."""
        creds = str(self.get("credentials_file") or "")
        sid = str(self.get("spreadsheet_id") or "")
        if not (self.get("google_enabled") and creds and sid):
            return False
        return Path(creds).expanduser().exists()


_settings = Settings()


def get_settings() -> Settings:
    return _settings


def now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def now_ms() -> float:
    return time.time() * 1000.0
