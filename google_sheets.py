# -*- coding: utf-8 -*-
"""google_sheets.py - Kết nối Google Sheets API (chính thức) + Google Drive.

NGUYÊN TẮC:
- Offline-first: mọi hàm đều raise ``NotConfigured`` khi chưa có credentials -> ứng dụng vẫn chạy.
- Không chứa API key / tài khoản trong mã nguồn: chỉ trỏ ĐƯỜNG DẪN file service account JSON.
- Ghi theo lô (batch) để tiết kiệm quota, có throttle + retry với backoff cho 429/5xx.
- Khóa ghi (lock lease) + cờ nội dung (content hash) để phát hiện thay đổi/ghi đè từ máy khác.

GIỚI HẠN QUAN TRỌNG CỦA GOOGLE SHEETS API (đọc tại docs.googleapis.com):
- ~300 lệnh READ/phút và ~60-100 lệnh WRITE/phút cho mỗi project (quota riêng cho READ/WRITE)
  -> phần mềm gom nhiều dòng vào 1 lệnh batchUpdate, throttle trước khi gửi.
- Tối đa 10 MB cho 1 request; ~100.000 ô/lệnh giá trị -> chia nhỏ theo ``batch_size``.
- 1 spreadsheet tối đa 10 triệu ô -> hàng nghìn căn hộ x 20 cột vẫn thoải mái.
- API KHÔNG có transaction/lock nguyên tử -> dùng khoá lease + content hash để chống ghi đè,
  và khuyến nghị backend trung tâm nếu nhiều máy cùng ghi liên tục (xem README).
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import get_settings, now_iso
from logger import get_logger

log = get_logger("sheets")

WRITE_SPACING_SEC = 0.65       # ~90 lệnh ghi/phút -> an toàn dưới mọi mức quota
MAX_RANGES_PER_BATCH = 200


class SheetsError(Exception):
    pass


class NotConfigured(SheetsError):
    """Chưa bật / thiếu credentials - KHÔNG phải lỗi mạng."""


@dataclass
class RemoteRow:
    excel_row: int                 # số dòng trên Sheets (1-based)
    cells: List[Any]
    payload: Dict[str, Any]        # đã chuẩn hoá kiểu dữ liệu
    content_hash: str


def content_hash(cells: Sequence[Any]) -> str:
    norm = "|".join("" if v is None else str(v).strip() for v in cells)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:32]


class SheetsClient:
    """Bọc Google Sheets API v4 (service account)."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._service = None
        self._last_write_ts = 0.0
        self._lock_token: Optional[str] = None

    # ------------------------------------------------------------------ config
    @property
    def spreadsheet_id(self) -> str:
        return str(self.settings.get("spreadsheet_id") or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("google_enabled")) and bool(self.spreadsheet_id)

    @property
    def configured(self) -> bool:
        creds = str(self.settings.get("credentials_file") or "")
        return self.enabled and bool(creds) and Path(creds).expanduser().exists()

    @property
    def rooms_sheet(self) -> str:
        return str(self.settings.get("rooms_sheet") or "Kho Hàng Phòng Trống")

    @property
    def map_sheet(self) -> str:
        return str(self.settings.get("map_sheet") or "App_ID_Map")

    @property
    def lock_sheet(self) -> str:
        return "_Lock"

    def status(self) -> str:
        if not self.settings.get("google_enabled"):
            return "Tắt đồng bộ Google"
        if not self.spreadsheet_id:
            return "Chưa nhập Spreadsheet ID"
        if not Path(str(self.settings.get("credentials_file") or "")).expanduser().exists():
            return "Chưa đặt file credentials"
        if self._service is None:
            return "Sẵn sàng (chưa kết nối)"
        return "Đã kết nối"

    # ------------------------------------------------------------------ connect
    def connect(self):
        if not self.enabled:
            raise NotConfigured("Đồng bộ Google chưa được bật (Cài đặt -> Google).")
        creds_file = str(self.settings.get("credentials_file") or "")
        if not creds_file or not Path(creds_file).expanduser().exists():
            raise NotConfigured(f"Không thấy file credentials: {creds_file or '(chưa đặt)'}")
        if self._service is not None:
            return self._service
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as e:
            raise NotConfigured("Chưa cài thư viện Google (pip install -r requirements.txt).") from e
        creds = service_account.Credentials.from_service_account_file(
            str(Path(creds_file).expanduser()),
            scopes=["https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"],
        )
        self._service = build("sheets", "v4", credentials=creds, cacheDiscovery=False)
        log.info("Đã kết nối Google Sheets (spreadsheet=%s...)", self.spreadsheet_id[:12])
        return self._service

    def reset(self) -> None:
        self._service = None

    # ------------------------------------------------------------------ low level
    def _throttle_write(self) -> None:
        wait = WRITE_SPACING_SEC - (time.time() - self._last_write_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_write_ts = time.time()

    @staticmethod
    def _with_retry(fn, attempts: int = 4):
        """Retry có lũy thừa cho 429/5xx/timeout - tuyệt đối không gửi lại lệnh đã thành công."""
        delay = 2.0
        last = None
        for i in range(attempts):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                last = e
                code = getattr(getattr(e, "resp", None), "status", None) or getattr(e, "status_code", None)
                retryable = code in (429, 500, 502, 503, 504) or code is None
                if not retryable or i == attempts - 1:
                    break
                log.warning("Sheets transient error (status=%s) -> thử lại sau %.1fs", code, delay)
                time.sleep(delay)
                delay *= 2
        raise SheetsError(str(last))

    def get_values(self, sheet: str, rng: str = "") -> List[List[Any]]:
        svc = self.connect()
        ref = f"'{sheet}'!{rng}" if rng else f"'{sheet}'"
        resp = self._with_retry(lambda: svc.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id, majorDimension="ROWS", range=ref).execute())
        return resp.get("values", [])

    def batch_update_values(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """data: [{'range': "'Sheet'!B6:T6', 'values': [[...]]}, ...]"""
        if not data:
            return {"totalUpdatedCells": 0}
        svc = self.connect()
        self._throttle_write()
        resp = self._with_retry(lambda: svc.spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ).execute())
        return resp

    def append_values(self, sheet: str, values: List[List[Any]], rng: str = "A1") -> Dict[str, Any]:
        if not values:
            return {}
        svc = self.connect()
        self._throttle_write()
        resp = self._with_retry(lambda: svc.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{sheet}'!{rng}",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"majorDimension": "ROWS", "values": values},
        ).execute())
        return resp

    def ensure_sheet(self, title: str) -> None:
        """Tạo sheet nếu chưa có (dùng cho App_ID_Map / _Lock) - không đụng tới sheet có sẵn."""
        svc = self.connect()
        meta = self._with_retry(lambda: svc.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id, fields="sheets(properties(title))").execute())
        titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if title in titles:
            return
        self._throttle_write()
        self._with_retry(lambda: svc.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute())
        log.info("Đã tạo sheet mới: %s", title)

    # ------------------------------------------------------------------ table read
    def read_table(self, sheet: Optional[str] = None):
        """Đọc nguyên 1 sheet -> SheetTable (nhận diện tiêu đề/ánh xạ cột như khi đọc Excel)."""
        from excel_import import parse_grid

        sheet = sheet or self.rooms_sheet
        values = self.get_values(sheet)
        table = parse_grid(values, sheet)
        if table is None:
            raise SheetsError(f"Sheet '{sheet}' không có dòng tiêu đề dữ liệu hợp lệ.")
        return table

    def pull_rooms(self) -> List[RemoteRow]:
        """Đọc toàn bộ phòng từ Sheets -> list RemoteRow (kèm content hash để phát hiện thay đổi)."""
        from excel_import import room_payload_from_row

        table = self.read_table()
        out: List[RemoteRow] = []
        for row in table.rows:
            payload = room_payload_from_row(row, table.mapping)
            payload["_address_key"] = _addr_key(payload)
            out.append(RemoteRow(excel_row=row["excel_row"], cells=row["cells"],
                                 payload=payload, content_hash=content_hash(row["cells"])))
        return out

    # ------------------------------------------------------------------ id map
    MAP_HEADERS = ["room_id", "sheet", "row", "version", "content_hash", "updated_at",
                   "address_key", "unit_key", "room_code"]

    def read_map(self) -> Dict[str, Dict[str, Any]]:
        """Đọc sheet ánh xạ ID -> số dòng trên Sheets."""
        try:
            values = self.get_values(self.map_sheet, f"A1:I{50000}")
        except Exception:
            return {}
        if not values:
            return {}
        header = [str(v).strip().lower() for v in values[0]]
        idx = {h: i for i, h in enumerate(header)}

        def g(cells, key, default=""):
            i = idx.get(key)
            if i is None or i >= len(cells):
                return default
            return cells[i]

        out = {}
        for r_i, cells in enumerate(values[1:], start=2):
            rid = str(g(cells, "room_id")).strip()
            if not rid:
                continue
            out[rid] = {
                "row": int(_num(g(cells, "row")) or r_i - 1),
                "version": int(_num(g(cells, "version"))),
                "content_hash": str(g(cells, "content_hash")),
                "updated_at": str(g(cells, "updated_at")),
                "address_key": str(g(cells, "address_key")),
                "unit_key": str(g(cells, "unit_key")),
                "room_code": str(g(cells, "room_code")),
            }
        return out

    def write_map(self, entries: List[Dict[str, Any]]) -> None:
        """Ghi toàn bộ sheet App_ID_Map (rewrite A1 -> n) - đơn giản, an toàn, số dòng nhỏ."""
        if not entries:
            return
        self.ensure_sheet(self.map_sheet)
        rows: List[List[Any]] = [list(self.MAP_HEADERS)]
        for e in entries:
            rows.append([e.get("room_id", ""), e.get("sheet", ""), e.get("row", 0), e.get("version", 0),
                         e.get("content_hash", ""), e.get("updated_at", ""), e.get("address_key", ""),
                         e.get("unit_key", ""), e.get("room_code", "")])
        # xoá phần dư (đề phòng số dòng giảm)
        self.batch_update_values([{
            "range": f"'{self.map_sheet}'!A1:I{max(len(rows) + 30, 100)}",
            "values": rows + [[""] * 9 for _ in range(30)],
        }])

    # ------------------------------------------------------------------ lock (lease)
    def acquire_lock(self, name: str = "warehouse", lease_sec: Optional[int] = None) -> bool:
        """Khóa ghi trên Sheets (best-effort lease). Trả False nếu máy khác đang giữ khóa."""
        lease = int(lease_sec or self.settings.get("lock_lease_sec") or 60)
        try:
            self.ensure_sheet(self.lock_sheet)
            values = self.get_values(self.lock_sheet, "A1:D5")
        except NotConfigured:
            raise
        except Exception as e:  # không đọc được khóa -> cho phép ghi (fail-open, có hash bảo vệ)
            log.warning("Không đọc được lock sheet (%s) -> tiếp tục (fail-open)", e)
            return True

        row_idx = None
        for i, cells in enumerate(values, start=1):
            if cells and str(cells[0]).strip() == name:
                row_idx = i
                break
        now = time.time()
        if row_idx:
            cells = values[row_idx - 1]
            try:
                expires = float(str(cells[2]).strip() or 0)
            except ValueError:
                expires = 0.0
            token = str(cells[1]).strip() if len(cells) > 1 else ""
            if expires > now and token and token != self._lock_token:
                return False  # máy khác đang giữ

        token = f"{uuid.uuid4().hex}"
        rng = f"'{self.lock_sheet}'!A{row_idx or 1}:D{row_idx or 1}"
        self.batch_update_values([{"range": rng,
                                   "values": [[name, token, str(now + lease), self.settings.get("user_name", "")]]}])
        self._lock_token = token
        return True

    def release_lock(self, name: str = "warehouse") -> None:
        if not self._lock_token:
            return
        try:
            values = self.get_values(self.lock_sheet, "A1:D5")
            for i, cells in enumerate(values, start=1):
                if cells and str(cells[0]).strip() == name and len(cells) > 1 \
                        and str(cells[1]).strip() == self._lock_token:
                    self.batch_update_values([{"range": f"'{self.lock_sheet}'!A{i}:D{i}",
                                               "values": [["", "", "", ""]]}])
                    break
        except Exception as e:
            log.warning("Không nhả được khóa Sheets: %s", e)
        finally:
            self._lock_token = None

    # ------------------------------------------------------------------ stats sheet
    def push_stats(self, stats: Dict[str, Any], sheet: str) -> None:
        """Ghi số liệu vào sheet 'Thống Kê Nhanh' theo đúng bố cục gốc (giữ nguyên công thức nếu có)."""
        status = stats.get("status", {})
        types = stats.get("types", {})
        rows = [
            ["1. TỔNG QUAN CHỈ SỐ KHO HÀNG", "", "", ""],
            ["Chỉ Số Kho Hàng", "Số Lượng Phòng", "Ghi Chú Cho Sale", ""],
            ["Tổng số phòng trong kho", stats.get("total", 0), "Số mã phòng đang quản lý", ""],
            ["Số phòng TRỐNG Ở NGAY", status.get("vacant", 0), "Ưu tiên chốt dắt khách ngay", ""],
            ["Số phòng SẮP TRỐNG (Cọc trước)", status.get("soon_vacant", 0), "Chào khách nhận nhà tháng tới", ""],
            ["Số phòng ĐÃ KHẢO SÁT (Có ảnh/video 📸)", stats.get("surveyed", 0), "Sẵn sàng gửi media cho khách", ""],
            ["Số phòng HỖ TRỢ XE ĐIỆN ⚡", stats.get("ev", 0), "Dành cho khách đi xe điện", ""],
            ["Số phòng CHO NUÔI PET 🐾", stats.get("pet", 0), "Dành cho khách nuôi chó/mèo", ""],
            ["", "", "", ""],
            ["2. PHÂN LOẠI PHÒNG TRỐNG THEO DẠNG PHÒNG", "", "", ""],
            ["Dạng Phòng", "Tổng Số Phòng", "Trống Ở Ngay", "Có Sạc Xe Điện ⚡"],
        ]
        for t in ["Studio", "1 Phòng Ngủ", "2 Phòng Ngủ", "Duplex", "Penthouse"]:
            d = (stats.get("by_type") or {}).get(t, {})
            rows.append([t, d.get("total", 0), d.get("vacant", 0), d.get("ev", 0)])
        self.batch_update_values([{"range": f"'{sheet}'!A1:D{len(rows)}", "values": rows}])


# ------------------------------------------------------------------ helpers
def _num(v) -> float:
    try:
        return float(str(v).strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _addr_key(payload: Dict[str, Any]) -> str:
    import text_utils as tu
    if payload.get("house_number") is None:
        return ""
    return tu.address_key(payload.get("house_number"), payload.get("street"),
                          payload.get("ward"), payload.get("district"))
