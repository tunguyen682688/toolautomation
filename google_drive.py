# -*- coding: utf-8 -*-
"""google_drive.py - Quản lý ảnh/video/tài liệu trên Google Drive + mở nhanh liên kết.

Google Drive CHỈ dùng để lưu media/tài liệu (không dùng làm nơi lưu bảng dữ liệu kho).
Tương tự Sheets: không credentials -> mọi hàm raise NotConfigured, phần mềm vẫn chạy bình thường.
"""
from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import get_settings
from logger import get_logger

log = get_logger("drive")


class DriveError(Exception):
    pass


class NotConfigured(DriveError):
    pass


def open_url(url: str) -> bool:
    """Mở link bằng trình duyệt mặc định (Drive / Zalo / Google Sheets)."""
    if not url:
        return False
    u = str(url).strip()
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    try:
        return webbrowser.open(u)
    except Exception as e:
        log.warning("Không mở được URL %s: %s", u, e)
        return False


def open_phone(phone: str) -> bool:
    """Mở nhanh số điện thoại (tel:) - dùng cho sale gọi khách/chủ nhà."""
    import re
    digits = "".join(re.findall(r"\d+", phone or ""))
    if not digits:
        return False
    return open_url(f"tel:{digits}")


def open_zalo(link: str) -> bool:
    return open_url(link)


def open_drive(link: str) -> bool:
    return open_url(link)


class DriveClient:
    """Bọc Google Drive API (tùy chọn): liệt kê folder, upload media."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._service = None

    @property
    def configured(self) -> bool:
        creds = str(self.settings.get("credentials_file") or "")
        return bool(creds) and Path(creds).expanduser().exists()

    def connect(self):
        if self._service is not None:
            return self._service
        if not self.configured:
            raise NotConfigured("Chưa cấu hình credentials cho Google Drive.")
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
        except ImportError as e:
            raise NotConfigured("Chưa cài thư viện Google (pip install -r requirements.txt).") from e
        creds = service_account.Credentials.from_service_account_file(
            str(Path(str(self.settings.get("credentials_file"))).expanduser()),
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        self._service = build("drive", "v3", credentials=creds, cacheDiscovery=False)
        return self._service

    def folder_id_from_link(self, link: str) -> str:
        """Trích folder ID từ URL Drive."""
        if not link:
            return ""
        s = str(link)
        for marker in ("/folders/", "id="):
            if marker in s:
                tail = s.split(marker, 1)[1]
                return tail.split("?")[0].split("&")[0].strip("/")
        return ""

    def list_folder(self, folder_link: str, limit: int = 50) -> List[Dict[str, Any]]:
        fid = self.folder_id_from_link(folder_link)
        if not fid:
            return []
        svc = self.connect()
        q = f"'{fid}' in parents and trashed=false"
        res = svc.files().list(q=q, pageSize=limit,
                               fields="files(id,name,mimeType,webViewLink,thumbnailLink)").execute()
        return res.get("files", [])

    def upload(self, file_path: str, folder_link: str = "") -> Dict[str, Any]:
        svc = self.connect()
        from googleapiclient.http import MediaFileUpload

        meta: Dict[str, Any] = {"name": Path(file_path).name}
        fid = self.folder_id_from_link(folder_link)
        if fid:
            meta["parents"] = [fid]
        media = MediaFileUpload(file_path, resumable=True)
        f = svc.files().create(body=meta, media_body=media, fields="id,name,webViewLink").execute()
        log.info("Đã upload lên Drive: %s", f.get("name"))
        return f

    def open_folder(self, folder_link: str) -> bool:
        return open_drive(folder_link)
