# -*- coding: utf-8 -*-
"""customer_manager.py - CRM: khách hàng tiềm năng + phân tích sale.

Mục đích: theo dõi khách từ lúc liên hệ tới khi CHỐT THUÊ hoặc MẤT, và trả
lời câu hỏi "mình SAI ĐIỂM NÀO khi sale":
- Funnel: khách rơi ở khâu nào (mới -> liên hệ -> tư vấn -> xem -> cọc -> chốt)?
- Lý do mất khách (lose_reason) tập trung ở đâu: giá? vị trí? phản hồi chậm?
- Nguồn khách nào ra nhiều / ra nhiều khách CHỐT?
- Tỷ lệ chốt (%) trên tập khách đã kết thúc.

Dữ liệu: SQLite cục bộ (offline-first), bảng `customers` + `customer_events`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import text_utils as tu
from config import now_iso
from database import Database, row_to_dict
from logger import get_logger
from models import CustomerStatus, LOSE_REASONS, new_id

log = get_logger("crm")

# các trường được phép ghi từ payload
_FIELDS = ("name", "phone", "zalo", "source", "status", "lose_reason",
           "requirement", "area", "room_type", "budget_min", "budget_max",
           "room_id", "rating", "next_action", "follow_up", "notes")

# các khâu của funnel bán hàng ('paused' không phải khâu, 'lost' là rơi RA ngoài)
FUNNEL_STAGES = ("new", "contacting", "consulting", "viewing", "deposit", "won")


def _opt_int(v) -> Optional[int]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def build_customer_search_norm(c: Dict[str, Any]) -> str:
    """Chuỗi tìm kiếm không dấu: tên + SĐT + zalo + yêu cầu + khu vực + ghi chú."""
    parts = [c.get("name"), c.get("phone"), c.get("zalo"), c.get("requirement"),
             c.get("area"), c.get("room_type"), c.get("next_action"), c.get("notes")]
    return tu.norm(" ".join(str(p) for p in parts if p))


class CustomerManager:
    """CRUD + pipeline trạng thái + thống kê phân tích sale."""

    def __init__(self, db: Database, settings=None):
        self.db = db
        self.settings = settings

    # ================================================================ CRUD
    def add_customer(self, payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        phone = str(payload.get("phone") or "").strip()
        if not name and not phone:
            raise ValueError("Cần ít nhất TÊN hoặc SỐ ĐIỆN THOẠI của khách hàng.")
        actor = actor or (self.settings.get("user_name") if self.settings else "") or "Admin"
        cid = new_id("CU")
        ts = now_iso()
        rec = {"id": cid}
        for k in _FIELDS:
            v = payload.get(k)
            if k in ("budget_min", "budget_max"):
                rec[k] = _opt_int(v)
            elif k == "rating":
                rec[k] = max(0, min(5, _opt_int(v) or 0))
            elif k == "status":
                rec[k] = CustomerStatus.from_text(v) if v else "new"
            else:
                s = str(v).strip() if v is not None else ""
                rec[k] = s
        if not rec["source"]:
            rec["source"] = "Zalo"
        rec["search_norm"] = build_customer_search_norm(rec)
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO customers (id, name, phone, zalo, source, status,"
                " lose_reason, requirement, area, room_type, budget_min, budget_max,"
                " room_id, rating, next_action, follow_up, notes, search_norm,"
                " version, deleted, created_at, updated_at, updated_by)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,?,?,?)",
                (cid, rec["name"], rec["phone"], rec["zalo"], rec["source"],
                 rec["status"], rec["lose_reason"], rec["requirement"], rec["area"],
                 rec["room_type"], rec["budget_min"], rec["budget_max"],
                 rec["room_id"], rec["rating"], rec["next_action"],
                 rec["follow_up"], rec["notes"], rec["search_norm"],
                 ts, ts, actor))
            self._log_event(conn, cid, "note",
                            f"Thêm khách (nguồn: {rec['source']})", actor=actor)
        return self.customer(cid) or rec

    def update_customer(self, cid: str, changes: Dict[str, Any],
                        actor: str = "", note: str = "") -> Dict[str, Any]:
        actor = actor or (self.settings.get("user_name") if self.settings else "") or "Admin"
        with self.db.write() as conn:
            current = self._get(conn, cid)
            if not current:
                raise KeyError(f"Không tìm thấy khách {cid}")
            sets, vals = [], []
            for k, v in changes.items():
                if k not in _FIELDS or k in ("id",):
                    continue
                if k in ("budget_min", "budget_max"):
                    val = _opt_int(v)
                elif k == "rating":
                    val = max(0, min(5, _opt_int(v) or 0))
                elif k == "status":
                    val = CustomerStatus.from_text(v)
                else:
                    val = str(v).strip() if v is not None else ""
                sets.append(f"{k}=?")
                vals.append(val)
            # đổi trạng thái qua update -> cũng ghi lịch sử (nhất quán với change_status)
            new_status = changes.get("status")
            if new_status and CustomerStatus.from_text(new_status) != current["status"]:
                self._apply_status_change(conn, current, changes, actor, note)
                return self.customer(cid) or current
            if not sets:
                return current
            merged = {**current, **{k: changes[k] for k in
                                    changes if k in _FIELDS}}
            sets.append("search_norm=?")
            vals.append(build_customer_search_norm(merged))
            sets.append("version=version+1")
            sets.append("updated_at=?")
            vals.append(now_iso())
            sets.append("updated_by=?")
            vals.append(actor)
            vals.append(cid)
            conn.execute(f"UPDATE customers SET {', '.join(sets)} WHERE id=?", vals)
            if note:
                self._log_event(conn, cid, "note", note, actor=actor)
        return self.customer(cid) or current

    def delete_customer(self, cid: str, actor: str = "") -> bool:
        actor = actor or (self.settings.get("user_name") if self.settings else "") or "Admin"
        with self.db.write() as conn:
            cur = conn.execute(
                "UPDATE customers SET deleted=1, version=version+1,"
                " updated_at=?, updated_by=? WHERE id=?",
                (now_iso(), actor, cid))
            if cur.rowcount:
                self._log_event(conn, cid, "note", "Xóa khách (thùng rác)", actor=actor)
            return bool(cur.rowcount)

    def customer(self, cid: str) -> Optional[Dict[str, Any]]:
        with self.db._lock:
            row = self.db.query_one("SELECT * FROM customers WHERE id=?", (cid,))
        return row_to_dict(row) if row else None

    def customers(self, text: str = "", status: Optional[str] = None,
                  source: Optional[str] = None) -> List[Dict[str, Any]]:
        """Danh sách khách (mới nhất trước) - lọc theo trạng thái/nguồn/tìm kiếm."""
        sql = "SELECT * FROM customers WHERE deleted=0"
        params: List[Any] = []
        if status:
            sql += " AND status=?"
            params.append(status)
        if source:
            sql += " AND source=?"
            params.append(source)
        q = tu.norm(text)
        if q:
            # tìm không dấu: so norm_key từng token trong search_norm
            sql += " AND search_norm LIKE ?"
            params.append(f"%{q}%")
        sql += " ORDER BY updated_at DESC"
        with self.db._lock:
            rows = self.db.query(sql, params)
        out = [row_to_dict(r) for r in rows]
        if q:
            # LIKE trên norm đã bỏ dấu nhưng còn khoảng trắng -> chốt bằng token
            toks = [t for t in q.split() if t]
            out = [c for c in out
                   if all(t in c.get("search_norm", "") for t in toks)]
        return out

    def events(self, cid: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self.db._lock:
            rows = self.db.query(
                "SELECT * FROM customer_events WHERE customer_id=?"
                " ORDER BY id DESC LIMIT ?", (cid, limit))
        return [row_to_dict(r) for r in rows]

    # ================================================================ pipeline
    def change_status(self, cid: str, new_status: str, actor: str = "",
                      lose_reason: str = "", note: str = "",
                      room_id: str = "") -> Dict[str, Any]:
        """Đổi trạng thái pipeline - luôn ghi lịch sử (events) kèm lý do mất."""
        actor = actor or (self.settings.get("user_name") if self.settings else "") or "Admin"
        new_status = CustomerStatus.from_text(new_status)
        with self.db.write() as conn:
            current = self._get(conn, cid)
            if not current:
                raise KeyError(f"Không tìm thấy khách {cid}")
            if current["status"] != new_status:
                self._apply_status_change(
                    conn, current,
                    {"status": new_status, "lose_reason": lose_reason,
                     "room_id": room_id},
                    actor, note)
            elif note:
                self._log_event(conn, cid, "note", note, actor=actor)
        return self.customer(cid) or current

    def _apply_status_change(self, conn, current: Dict, changes: Dict,
                             actor: str, note: str = ""):
        new_status = changes.get("status") or current["status"]
        lose = changes.get("lose_reason") or ""
        if new_status == "lost":
            lose = lose or current.get("lose_reason") or "other"
        else:
            lose = ""          # hồi sinh khỏi "Mất khách" -> bỏ lý do cũ
        sets = ["status=?", "lose_reason=?", "version=version+1",
                "updated_at=?", "updated_by=?"]
        vals: List[Any] = [new_status, lose, now_iso(), actor]
        rid = changes.get("room_id")
        if rid:
            sets.append("room_id=?")
            vals.append(str(rid))
        vals.append(current["id"])
        conn.execute(f"UPDATE customers SET {', '.join(sets)} WHERE id=?", vals)
        self._log_event(conn, current["id"], "status",
                        note or (f"{CustomerStatus.label(current['status'])}"
                                 f" -> {CustomerStatus.label(new_status)}"
                                 + (f" ({lose})" if new_status == "lost" else "")),
                        old_status=current["status"], new_status=new_status,
                        room_id=str(rid or current.get("room_id") or ""),
                        actor=actor)

    def log_event(self, cid: str, event: str, detail: str = "",
                  room_id: str = "", actor: str = "") -> None:
        """Ghi 1 tương tác: call (gọi) | zalo (nhắn) | view (xem phòng) | note."""
        actor = actor or (self.settings.get("user_name") if self.settings else "") or "Admin"
        with self.db.write() as conn:
            self._log_event(conn, cid, event, detail, room_id=room_id, actor=actor)

    @staticmethod
    def _log_event(conn, cid: str, event: str, detail: str = "",
                   old_status: str = "", new_status: str = "",
                   room_id: str = "", actor: str = "") -> None:
        conn.execute(
            "INSERT INTO customer_events"
            " (customer_id, event, detail, old_status, new_status, room_id,"
            "  created_at, actor) VALUES (?,?,?,?,?,?,?,?)",
            (cid, event, detail, old_status, new_status, room_id,
             now_iso(), actor))

    @staticmethod
    def _get(conn, cid: str) -> Optional[Dict[str, Any]]:
        row = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
        return row_to_dict(row) if row else None

    # ================================================================ phân tích
    def stats(self) -> Dict[str, Any]:
        """Số liệu cho trang Phân tích Sale (funnel + lý do mất + nguồn + chốt)."""
        with self.db._lock:
            rows = self.db.query(
                "SELECT id, status, lose_reason, source, created_at"
                " FROM customers WHERE deleted=0")
            ev_rows = self.db.query(
                "SELECT event, COUNT(*) c FROM customer_events GROUP BY event")
            stage_rows = self.db.query(
                "SELECT customer_id, new_status FROM customer_events"
                " WHERE new_status<>''")
            won_rows = self.db.query(
                "SELECT c.created_at a, e.created_at b FROM customers c"
                " JOIN customer_events e ON e.customer_id = c.id"
                " AND e.new_status='won' WHERE c.deleted=0")
        total = len(rows)
        by_status: Dict[str, int] = {k: 0 for k in CustomerStatus.ORDER}
        by_source: Dict[str, int] = {}
        by_reason: Dict[str, int] = {}
        for r in rows:
            st = r["status"] or "new"
            by_status[st] = by_status.get(st, 0) + 1
            src = r["source"] or "Khác"
            by_source[src] = by_source.get(src, 0) + 1
            if st == "lost":
                key = r["lose_reason"] or "other"
                by_reason[key] = by_reason.get(key, 0) + 1
        won = by_status.get("won", 0)
        lost = by_status.get("lost", 0)
        closed = won + lost
        funnel = [(k, CustomerStatus.label(k), by_status.get(k, 0))
                  for k in CustomerStatus.ORDER if k not in ("paused",)]

        # ---- FUNNEL THẬT: khách đã TỪNG tới tối đa khâu nào (từ lịch sử trạng thái)
        stage_pos = {k: i for i, k in enumerate(FUNNEL_STAGES)}
        max_pos: Dict[str, int] = {r["id"]: 0 for r in rows}   # khách nào cũng bắt đầu ở khâu 'new'
        for r in rows:
            p = stage_pos.get(r["status"] or "new")
            if p is not None and p > max_pos.get(r["id"], 0):
                max_pos[r["id"]] = p
        for e in stage_rows:
            p = stage_pos.get(e["new_status"] or "")
            cid = e["customer_id"]
            if p is not None and cid in max_pos and p > max_pos[cid]:
                max_pos[cid] = p
        exact = [0] * len(FUNNEL_STAGES)
        for p in max_pos.values():
            exact[p] += 1
        reached: List[int] = []
        acc = 0
        for i in range(len(FUNNEL_STAGES) - 1, -1, -1):
            acc += exact[i]
            reached.insert(0, acc)      # reached[i] = số khách đã TỪNG tới khâu i
        funnel_reached = [(k, CustomerStatus.label(k), reached[i])
                          for i, k in enumerate(FUNNEL_STAGES)]

        top_reasons = sorted(
            ((k, dict(LOSE_REASONS).get(k, k or "Khác"), n)
             for k, n in by_reason.items() if n),
            key=lambda x: -x[2])
        activity = {r["event"]: r["c"] for r in ev_rows}
        # số ngày trung bình từ lúc thêm khách -> chốt (chỉ khách đã chốt)
        days = []
        import datetime as _dt
        for r in won_rows:
            try:
                a = _dt.datetime.fromisoformat(r["a"])
                b = _dt.datetime.fromisoformat(r["b"])
                days.append(max(0, (b - a).total_seconds() / 86400.0))
            except (TypeError, ValueError):
                pass
        return {
            "total": total,
            "by_status": by_status,
            "by_source": by_source,
            "by_reason": by_reason,
            "won": won,
            "lost": lost,
            "active": sum(by_status.get(k, 0) for k in CustomerStatus.ACTIVE),
            "paused": by_status.get("paused", 0),
            "conversion": round(won * 100.0 / closed, 1) if closed else None,
            "funnel": funnel,
            "funnel_reached": funnel_reached,   # (khâu, nhãn, số khách đã từng tới)
            "top_reasons": top_reasons,
            "activity": activity,
            "won_avg_days": round(sum(days) / len(days), 1) if days else None,
        }
