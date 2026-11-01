# -*- coding: utf-8 -*-
"""media_manager.py - Quản lý ảnh/video phòng lưu CỤC BỘ theo thư mục quy ước.

Quy ước đường dẫn (mặc định gốc là "Data Image" cạnh app, đổi được trong Cài đặt):

    <gốc>/<Quận>/<Đường>/<Số nhà>-<Mã phòng>/<loại phòng> <giá>tr

Ví dụ khách hàng đưa:
    Data Image/Bình Thạnh/Nơ Trang Long/5-102-4/studio 8tr

- Ảnh/video chụp bằng điện thoại chỉ cần copy vào đúng thư mục là app tự liệt kê
  (FileSystem là nguồn sự thật - KHÔNG lưu media trong SQLite).
- Khi thêm media từ app: tự tạo đủ cây thư mục theo quy ước, trùng tên trùng dung lượng
  thì bỏ qua, trùng tên khác dung lượng thì tự đổi tên "abc (2).jpg".
- Xóa trong app = chuyển vào "<gốc>/_ThungRac/" (không mất file ngay).
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List

from logger import get_logger

log = get_logger("media")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp"}

_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_TRASH_DIR = "_ThungRac"


# ------------------------------------------------------------------ helpers
def sanitize_segment(text: str, max_len: int = 60) -> str:
    """Làm tên thư mục an toàn Windows nhưng GIỮ nguyên dấu tiếng Việt
    (VD: 'Nơ Trang Long' giữ nguyên; ký tự cấm \\ / : * ? " < > | -> '-')."""
    s = _ILLEGAL.sub("-", str(text or "")).strip().strip(".")
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip("-").strip()          # bỏ '-' thừa ở hai đầu (từ ký tự cấm)
    return s[:max_len].strip(" .-") or "(khác)"


def clean_district(district: str) -> str:
    """"Q. Bình Thạnh" -> "Bình Thạnh"; "Quận 3" -> "3" (giữ dấu tiếng Việt)."""
    s = str(district or "").strip()
    s = re.sub(r"^(?:quận|q)\.?\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


def _price_tr(price: Any) -> str:
    """8000000 -> '8tr'; 8500000 -> '8.5tr'."""
    try:
        m = float(price or 0) / 1_000_000.0
    except (TypeError, ValueError):
        return ""
    if m <= 0:
        return ""
    return f"{m:g}tr"


def room_dir_name(room: Dict[str, Any]) -> str:
    """"5-102-4" = số nhà - mã phòng (thiếu gì ghép phần còn lại)."""
    house = sanitize_segment(str(room.get("house_number") or ""), 30)
    code = sanitize_segment(str(room.get("room_code") or room.get("unit_code") or ""), 30)
    parts = [p for p in (house, code) if p and p != "(khác)"]
    return "-".join(parts) if parts else "(chưa mã)"


def room_leaf_name(room: Dict[str, Any]) -> str:
    """"studio 8tr" = loại phòng + giá (thiếu loại -> 'phong', thiếu giá -> chỉ loại)."""
    rtype = sanitize_segment(str(room.get("room_type") or ""), 40).lower()
    rtype = "" if rtype == "(khác)" else rtype
    tr = _price_tr(room.get("price"))
    if rtype and tr:
        return f"{rtype} {tr}"
    if rtype:
        return rtype
    return f"phong {tr}" if tr else "phong"


# ------------------------------------------------------------------ đường dẫn quy ước
def media_root(settings) -> Path:
    """Gốc thư mục media: settings['media_root'], tương đối -> cạnh thư mục chạy app."""
    raw = str(settings.get("media_root") or "Data Image").strip() or "Data Image"
    p = Path(raw)
    return p if p.is_absolute() else Path.cwd() / p


def room_media_dir(room: Dict[str, Any], settings) -> Path:
    """Đường dẫn quy ước của phòng (CHƯA tạo):
    <gốc>/<Quận>/<Đường>/<số nhà>-<mã phòng>/<loại> <giá>tr"""
    root = media_root(settings)
    district = sanitize_segment(clean_district(room.get("district")), 50)
    street = sanitize_segment(room.get("street"), 60)
    return root / district / street / room_dir_name(room) / room_leaf_name(room)


def ensure_room_dir(room: Dict[str, Any], settings) -> Path:
    """Tạo đủ cây thư mục quy ước (nếu chưa có) -> trả về Path."""
    d = room_media_dir(room, settings)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ liệt kê / thêm / xóa
def kind_of(path: Path) -> str:
    return ("image" if path.suffix.lower() in IMAGE_EXTS
            else "video" if path.suffix.lower() in VIDEO_EXTS else "other")


def list_media(room: Dict[str, Any], settings) -> List[Dict[str, Any]]:
    """Danh sách file media của phòng (ảnh trước, video sau, tên A-Z). Quét trực tiếp thư mục."""
    d = room_media_dir(room, settings)
    if not d.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for f in d.iterdir():
            if not f.is_file() or f.name.startswith("."):
                continue
            st = f.stat()
            out.append({
                "name": f.name,
                "path": str(f),
                "kind": kind_of(f),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
    except OSError as e:
        log.warning("Không đọc được thư mục %s: %s", d, e)
        return []
    order = {"image": 0, "video": 1, "other": 2}
    out.sort(key=lambda m: (order.get(m["kind"], 3), m["name"].lower()))
    return out


def _unique_dest(d: Path, name: str) -> Path:
    """Trùng tên (không phân biệt hoa thường - NTFS) -> thêm ' (2)', ' (3)'..."""
    base, ext = Path(name).stem, Path(name).suffix
    cand = d / name
    low = name.lower()
    try:
        taken = {f.name.lower() for f in d.iterdir() if f.is_file()}
    except OSError:
        taken = set()
    i = 2
    while low in taken:
        cand = d / f"{base} ({i}){ext}"
        low = cand.name.lower()
        i += 1
    return cand


def import_files(room: Dict[str, Any], src_paths: List[str], settings,
                 delete_source: bool = False) -> Dict[str, List[str]]:
    """Copy (hoặc di chuyển) file vào thư mục quy ước của phòng. Tự tạo thư mục.

    Trùng tên + trùng dung lượng -> bỏ qua (đã có rồi);
    trùng tên + khác dung lượng -> tự đổi tên ' (2)'.
    """
    dest_dir = ensure_room_dir(room, settings)
    res: Dict[str, List[str]] = {"copied": [], "skipped": [], "errors": []}
    for src in src_paths:
        try:
            s = Path(src)
            if not s.is_file():
                res["errors"].append(f"{src}: không tồn tại")
                continue
            dest = dest_dir / s.name
            if dest.exists() and dest.stat().st_size == s.stat().st_size:
                res["skipped"].append(str(dest))
                if delete_source:
                    s.unlink(missing_ok=True)
                continue
            dest = _unique_dest(dest_dir, s.name)
            if delete_source:
                shutil.move(str(s), str(dest))
            else:
                shutil.copy2(str(s), str(dest))
            res["copied"].append(str(dest))
        except Exception as e:  # noqa: BLE001
            log.warning("Import media lỗi %s: %s", src, e)
            res["errors"].append(f"{src}: {e}")
    return res


def move_to_trash(paths: List[str], settings) -> List[str]:
    """'Xóa' = chuyển vào <gốc>/_ThungRac/ (giữ thư mục con của phòng) - không mất ngay."""
    root = media_root(settings)
    moved: List[str] = []
    for p in paths:
        try:
            s = Path(p)
            if not s.is_file():
                continue
            # thư mục cha của file (tên phòng) -> _ThungRac/<tên phòng>/
            trash = root / _TRASH_DIR / sanitize_segment(s.parent.name, 60)
            trash.mkdir(parents=True, exist_ok=True)
            dest = _unique_dest(trash, s.name)
            shutil.move(str(s), str(dest))
            moved.append(str(dest))
        except Exception as e:  # noqa: BLE001
            log.warning("Chuyển thùng rác lỗi %s: %s", p, e)
    return moved


def human_size(n: int) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def age_label(mtime: float) -> str:
    days = max(0, int((time.time() - mtime) / 86400))
    if days <= 0:
        return "hôm nay"
    if days < 30:
        return f"{days} ngày trước"
    return f"{days // 30} tháng trước"
