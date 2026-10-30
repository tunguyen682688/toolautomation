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

DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
LOG_DIR = DATA_DIR / "logs"
CACHE_DIR = DATA_DIR / "cache"
SAMPLES_DIR = BUNDLE_DIR / "samples"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
DB_FILE = DATA_DIR / "kho_phong.db"

for _d in (DATA_DIR, CONFIG_DIR, LOG_DIR, CACHE_DIR, SAMPLES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULTS: Dict[str, Any] = {
    # --- người dùng / hiển thị ---
    "user_name": "Admin",
    "language": "vi",
    "page_size": 500,
    "auto_save": True,
    "confirm_delete": True,
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
