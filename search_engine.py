# -*- coding: utf-8 -*-
"""search_engine.py - Chỉ mục tìm kiếm trong bộ nhớ (in-memory inverted index) + bộ nhớ đệm kết quả.

Mục tiêu (ưu tiên số 1 của đặc tả): trả kết quả < 5ms với hàng nghìn căn hộ,
không phân biệt hoa/thường, có/không dấu tiếng Việt, khoảng trắng thừa.

Cách hoạt động:
- Mỗi phòng 1 tài liệu ``search_norm`` (đã bỏ dấu, hạ chữ) -> cắt token -> postings.
- Truy vấn = giao các tập token (token >= 2 ký tự cho phép khớp tiền tố qua bisect).
- Bộ lọc (trạng thái/giá/tòa nhà/loại phòng...) áp lên tập ứng viên sẵn có.
- KQCache theo (query, filter, rev) để thao tác lặp lại không tốn chi phí.
"""
from __future__ import annotations

import bisect
import threading
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import text_utils as tu
from models import RoomFilter
from logger import get_logger

log = get_logger("search")

_MAX_CACHE = 128


@dataclass
class Doc:
    id: str
    norm: str
    tokens: Set[str]
    building_id: str
    status: str
    room_type: str
    price: int
    ev: bool
    pet: bool
    surveyed: bool
    foreign_guest: bool
    needs_verify: bool
    deleted: bool
    code_key: str
    addr_key: str
    sort_key: str


def _make_doc(row: Dict) -> Doc:
    norm_text = row.get("search_norm") or ""
    toks = set(tu.tokens(norm_text))
    code_key = row.get("room_code_key") or tu.room_code_key(row.get("room_code", ""))
    if code_key:
        toks.add(code_key)
    unit_key = row.get("unit_key") or ""
    if unit_key:
        toks.add(unit_key)
    price = int(row.get("price") or 0)
    if price:
        toks.add(str(price))
    return Doc(
        id=row["id"],
        norm=norm_text,
        tokens=toks,
        building_id=row.get("building_id", ""),
        status=row.get("status", ""),
        room_type=tu.norm(row.get("room_type", "")),
        price=price,
        ev=bool(row.get("ev_support")),
        pet=bool(row.get("pet_ok")),
        surveyed=bool(row.get("surveyed")),
        foreign_guest=bool(row.get("foreign_guest")),
        needs_verify=bool(row.get("needs_verify")),
        deleted=bool(row.get("deleted")),
        code_key=code_key,
        addr_key=tu.norm_key(f"{row.get('address','')} {row.get('unit_code','')}"),
        sort_key=(code_key or tu.norm_key(row.get("unit_code", "")) or row["id"]).lower(),
    )


class SearchIndex:
    """Chỉ mục tìm kiếm phòng. An toàn thread: mọi thao tác đều giữ RLock."""

    def __init__(self, db):
        self.db = db
        self._lock = threading.RLock()
        self.docs: Dict[str, Doc] = {}
        self.postings: Dict[str, Set[str]] = {}
        self.tokens_sorted: List[str] = []
        self.rev = 0
        self._cache: Dict[Tuple, List[str]] = {}

    # ------------------------------------------------------------------ build
    def rebuild(self) -> int:
        """Nạp lại toàn bộ từ DB (gọi 1 lần lúc mở chương trình / F5)."""
        from database import _ROOM_SELECT  # tránh import vòng

        rows = [dict(r) for r in self.db.query(_ROOM_SELECT + " WHERE r.deleted=0")]
        with self._lock:
            self.docs.clear()
            self.postings.clear()
            for row in rows:
                self._add_locked(_make_doc(row))
            self._rebuild_sorted()
            self._cache.clear()
            self.rev += 1
        log.debug("rebuild index: %d phòng", len(rows))
        return len(rows)

    def update_room(self, row: Dict) -> None:
        with self._lock:
            self.remove_room(row.get("id", ""))
            if not row.get("deleted"):
                self._add_locked(_make_doc(row))
            self._rebuild_sorted()
            self._cache.clear()
            self.rev += 1

    def remove_room(self, room_id: str) -> None:
        with self._lock:
            doc = self.docs.pop(room_id, None)
            if doc:
                for t in doc.tokens:
                    s = self.postings.get(t)
                    if s is not None:
                        s.discard(room_id)
                        if not s:
                            del self.postings[t]
            self._rebuild_sorted()
            self._cache.clear()
            self.rev += 1

    def _add_locked(self, doc: Doc) -> None:
        self.docs[doc.id] = doc
        for t in doc.tokens:
            self.postings.setdefault(t, set()).add(doc.id)

    def _rebuild_sorted(self) -> None:
        self.tokens_sorted = sorted(self.postings.keys())

    # ------------------------------------------------------------------ query
    def _candidates(self, text: str) -> Optional[Set[str]]:
        """Giao các tập token; None = không giới hạn (query rỗng)."""
        toks = tu.tokens(text)
        if not toks:
            return None
        sets: List[Set[str]] = []
        for t in toks:
            if len(t) == 1:
                s = set(self.postings.get(t, ()))
            else:
                # exact + prefix (bắt đầu bằng token -> gõ "nguyent" vẫn ra Nguyễn Thượng Hiền)
                s = set(self.postings.get(t, ()))
                i = bisect.bisect_left(self.tokens_sorted, t)
                while i < len(self.tokens_sorted) and self.tokens_sorted[i].startswith(t):
                    s |= self.postings[self.tokens_sorted[i]]
                    i += 1
            if not s:
                return set()  # 1 token không khớp => toàn bộ rỗng
            sets.append(s)
        sets.sort(key=len)
        out = sets[0]
        for s in sets[1:]:
            out = out & s
            if not out:
                break
        return out

    @staticmethod
    def _match_filters(doc: Doc, f: Optional[RoomFilter]) -> bool:
        if f is None:
            return not doc.deleted
        if not f.include_deleted and doc.deleted:
            return False
        if f.building_id and doc.building_id != f.building_id:
            return False
        if f.statuses and doc.status not in set(f.statuses):
            return False
        if f.room_types and doc.room_type not in {tu.norm(x) for x in f.room_types}:
            return False
        if f.price_min is not None and doc.price < f.price_min:
            return False
        if f.price_max is not None and doc.price > f.price_max:
            return False
        if f.ev_support is not None and doc.ev != f.ev_support:
            return False
        if f.pet_allowed is not None and doc.pet != f.pet_allowed:
            return False
        if f.foreign_guest is not None and doc.foreign_guest != f.foreign_guest:
            return False
        if f.surveyed is not None and doc.surveyed != f.surveyed:
            return False
        if f.needs_verify is not None and doc.needs_verify != f.needs_verify:
            return False
        return True

    def _score(self, doc: Doc, q_raw: str, q_key: str) -> float:
        score = 0.0
        if q_key:
            if doc.code_key == q_key:
                score += 1000
            elif doc.code_key.startswith(q_key):
                score += 500
            if q_key in doc.addr_key:
                score += 200
        nq = tu.norm(q_raw)
        if nq and nq in doc.norm:
            score += 120
        if doc.price and q_key and q_key.isdigit() and int(q_key) == doc.price:
            score += 300
        return score

    def query(self, text: str = "", f: Optional[RoomFilter] = None) -> List[str]:
        """Trả về list id phòng đã sắp xếp theo độ liên quan."""
        with self._lock:
            rev = self.rev
            cache_key = (tu.norm(text), None if f is None else f.key())
            hit = self._cache.get(cache_key)
            if hit is not None:
                return list(hit)

            cand = self._candidates(text)
            if cand is None:
                cand = set(self.docs.keys())

            q_key = tu.norm_key(text)
            out: List[Tuple[float, str, str]] = []
            for rid in cand:
                doc = self.docs.get(rid)
                if doc is None:
                    continue
                if not self._match_filters(doc, f):
                    continue
                out.append((-self._score(doc, text, q_key), doc.sort_key, rid))
            out.sort()
            ids = [rid for _, _, rid in out]

            if len(self._cache) >= _MAX_CACHE:
                self._cache.pop(next(iter(self._cache)), None)
            self._cache[cache_key] = list(ids)
            if rev != self.rev:  # có thay đổi trong lúc tra -> không lưu
                self._cache.pop(cache_key, None)
            return ids

    def count(self, text: str = "", f: Optional[RoomFilter] = None) -> int:
        return len(self.query(text, f))

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------------------------ building search
    def search_buildings(self, buildings: Sequence[Dict], text: str) -> List[Dict]:
        """Lọc danh sách tòa nhà theo text (danh sách ~vài trăm -> quét trực tiếp là đủ nhanh)."""
        q = tu.norm(text)
        if not q:
            return list(buildings)
        q_keys = [t for t in tu.tokens(q) if t]
        out = []
        for b in buildings:
            hay = b.get("search_norm") or ""
            if all(t in hay for t in q_keys):
                out.append(b)
        return out
