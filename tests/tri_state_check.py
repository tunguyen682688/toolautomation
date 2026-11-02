# -*- coding: utf-8 -*-
"""tri_state_check.py - Kiểm tra sâu phân biệt 3 trạng thái Chưa biết/Có/Không.

Chạy:  python tests/tri_state_check.py

Phủ các đường: form/payload -> _room_record -> SQLite (NULL) -> đọc lại ->
panel/bảng hiển thị -> export Excel -> import lại -> chống trùng -> migration DB cũ.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print(f"  [PASS] {name}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False, str(e)))
        print(f"  [FAIL] {name}: {e}")
        import traceback
        traceback.print_exc()


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "Điều kiện sai")


def main():
    from config import get_settings
    from database import Database
    from inventory_manager import InventoryManager

    tmp = Path(tempfile.mkdtemp(prefix="kho_tri_"))
    settings = get_settings()
    old_db, old_g = settings.get("db_path"), settings.get("google_enabled")
    settings.set("google_enabled", False, save=False)

    def fresh(name="tri.db"):
        Database.reset_instance()
        path = str(tmp / name)
        db = Database(path)
        return db, InventoryManager(db)

    # -------------------------------------------------- 1. round-trip toàn bộ None
    def t01_roundtrip_none():
        db, mgr = fresh()
        b = mgr.ensure_building({"house_number": "42", "street": "Đường Tri Test",
                                 "ward": "P.9", "district": "Q.T"}, "t")
        payload = {"building_id": b["id"], "house_number": "42", "street": "Đường Tri Test",
                   "ward": "P.9", "district": "Q.T",
                   "room_code": "TRI-1", "unit_code": "T-1", "status": "new",
                   "price": None, "deposit": None, "floor": None, "area": None,
                   "capacity": None, "ev_support": None, "foreign_guest": None,
                   "pet_policy": None, "surveyed": None, "rating": None}
        r = mgr.add_room(payload, "t", force=True)
        r2 = mgr.room(r["id"])
        for k in ("price", "deposit", "floor", "area", "capacity", "ev_support",
                  "foreign_guest", "pet_policy", "surveyed", "rating"):
            assert_true(r2.get(k) is None,
                        f"add_room: {k} = {r2.get(k)!r}, kỳ vọng None (Chưa biết)")
        # NULL trong DB thật (không phải default 0/'')
        row = db.query_one("SELECT price, ev_support, pet_policy, floor, surveyed "
                           "FROM rooms WHERE id=?", (r["id"],))
        assert_true(row["price"] is None and row["ev_support"] is None
                    and row["pet_policy"] is None and row["floor"] is None
                    and row["surveyed"] is None,
                    f"DB phải là NULL: {dict(row)}")

    # -------------------------------------------------- 2. update về None không bị sập về 0
    def t02_update_to_none():
        db, mgr = fresh("tri2.db")
        b = mgr.ensure_building({"house_number": "43", "street": "Đường Tri 2"}, "t")
        r = mgr.add_room({"building_id": b["id"], "house_number": "43", "street": "Đường Tri 2",
                          "room_code": "TRI-2", "unit_code": "T-2", "status": "vacant",
                          "price": 7000000, "ev_support": 1, "surveyed": 1,
                          "pet_policy": "Không nuôi"}, "t", force=True)
        # có -> chưa biết
        mgr.update_room(r["id"], {"price": None, "ev_support": None, "surveyed": None,
                                  "pet_policy": None}, "t")
        r2 = mgr.room(r["id"])
        assert_true(r2["price"] is None, f"price sau update None = {r2['price']!r}")
        assert_true(r2["ev_support"] is None, f"ev_support = {r2['ev_support']!r}")
        assert_true(r2["surveyed"] is None, f"surveyed = {r2['surveyed']!r}")
        assert_true(r2["pet_policy"] is None, f"pet_policy = {r2['pet_policy']!r}")
        # chưa biết -> Không (0) -> KHÁC None
        mgr.update_room(r["id"], {"ev_support": 0, "surveyed": 0}, "t")
        r3 = mgr.room(r["id"])
        assert_true(r3["ev_support"] == 0 and r3["surveyed"] == 0,
                    f"0 phải giữ nguyên: ev={r3['ev_support']!r} sv={r3['surveyed']!r}")
        # Không -> Có
        mgr.update_room(r["id"], {"ev_support": 1}, "t")
        assert_true(mgr.room(r["id"])["ev_support"] == 1, "ev_support 1 không lưu được")

    # -------------------------------------------------- 3. export -> import giữ nguyên 3 trạng thái
    def t03_excel_roundtrip():
        from excel_export import export_workbook
        from excel_import import read_workbook, build_plan
        db, mgr = fresh("tri3.db")
        b = mgr.ensure_building({"house_number": "44", "street": "Đường Tri 3"}, "t")
        mk = lambda code, **kw: mgr.add_room(  # noqa: E731
            {"building_id": b["id"], "house_number": "44", "street": "Đường Tri 3",
             "room_code": code, "unit_code": code, "status": "vacant",
             "price": 6500000, **kw}, "t", force=True)
        r_none = mk("TRI-3A", price=None, ev_support=None, surveyed=None, pet_policy=None)
        r_zero = mk("TRI-3B", price=6500000, ev_support=0, surveyed=0, pet_policy="Không nuôi")
        r_one = mk("TRI-3C", price=7500000, ev_support=1, surveyed=1, pet_policy="Cho nuôi Mèo")
        out = tmp / "tri_roundtrip.xlsx"
        export_workbook(str(out), mgr.rooms(""), mgr.buildings(), mgr.stats())
        plan = build_plan(read_workbook(str(out)), mgr.checker, db)
        c = plan.counts()
        assert_true(c["new"] == 0, f"Import lại file export sinh dòng MỚI: {c}")
        # payload sau khi đọc lại phải phân biệt được 3 trạng thái
        by_code = {it.payload.get("room_code"): it.payload for it in plan.items}
        p3a = by_code.get("TRI-3A")
        assert_true(p3a is not None, "Không đọc lại được TRI-3A")
        assert_true(p3a.get("price") is None, f"TRI-3A price = {p3a.get('price')!r} (cần None)")
        assert_true(p3a.get("ev_support") is None, f"TRI-3A ev = {p3a.get('ev_support')!r}")
        assert_true(p3a.get("surveyed") is None, f"TRI-3A surveyed = {p3a.get('surveyed')!r}")
        p3b = by_code.get("TRI-3B")
        assert_true(p3b.get("ev_support") == 0 and p3b.get("surveyed") == 0,
                    f"TRI-3B ev/surveyed = {p3b.get('ev_support')!r}/{p3b.get('surveyed')!r} (cần 0/0)")
        assert_true(p3b.get("price") == 6500000, f"TRI-3B price = {p3b.get('price')!r}")
        p3c = by_code.get("TRI-3C")
        assert_true(p3c.get("ev_support") == 1 and p3c.get("surveyed") == 1,
                    f"TRI-3C ev/surveyed = {p3c.get('ev_support')!r}/{p3c.get('surveyed')!r} (cần 1/1)")
        # áp dụng import -> KHÔNG được ghi đè None bằng gì khác
        mgr.import_apply(plan, ["new", "duplicate", "changed", "suspect"], actor="t")
        r = mgr.room(r_none["id"])
        assert_true(r["price"] is None and r["ev_support"] is None and r["surveyed"] is None,
                    f"Sau import lại TRI-3A thành {r['price']!r}/{r['ev_support']!r}/{r['surveyed']!r}")
        z = mgr.room(r_zero["id"])
        assert_true(z["ev_support"] == 0 and z["surveyed"] == 0 and z["price"] == 6500000,
                    f"Sau import lại TRI-3B thành {z['ev_support']!r}/{z['surveyed']!r}/{z['price']!r}")
        o = mgr.room(r_one["id"])
        assert_true(o["ev_support"] == 1 and o["surveyed"] == 1 and o["price"] == 7500000,
                    f"Sau import lại TRI-3C thành {o['ev_support']!r}/{o['surveyed']!r}")

    # -------------------------------------------------- 4. tìm kiếm / vân tay / hiển thị
    def t04_search_and_display():
        from database import build_room_search_norm
        from duplicate_checker import fingerprint
        from room_view import RoomTableModel
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        db, mgr = fresh("tri4.db")
        norm = build_room_search_norm({"price": None, "deposit": None, "floor": None,
                                       "room_code": "P-1"})
        assert_true("none" not in norm.split(), f"search_norm chứa chữ 'none': {norm!r}")
        # vân tay phân biệt None vs 0
        fp_unknown = fingerprint({"price": None, "ev_support": None, "surveyed": None})
        fp_zero = fingerprint({"price": 0, "ev_support": 0, "surveyed": 0})
        assert_true(fp_unknown != fp_zero,
                    "fingerprint: None (Chưa biết) phải KHÁC 0 (Không)")
        fp_zero2 = fingerprint({"price": 0, "ev_support": 0, "surveyed": 0})
        assert_true(fp_zero == fp_zero2, "fingerprint: 0 không ổn định")
        # hiển thị bảng phân biệt rõ ràng
        app = QApplication.instance() or QApplication(sys.argv[:1])
        model = RoomTableModel(mgr)
        row_unknown = {"price": None, "deposit": None, "ev_support": None,
                       "foreign_guest": None, "surveyed": None, "area": None,
                       "status": "vacant", "pet_policy": None}
        row_no = {"price": 6500000, "deposit": None, "ev_support": 0,
                  "foreign_guest": 0, "surveyed": 0, "area": "45",
                  "status": "vacant", "pet_policy": "Không nuôi"}
        disp = lambda r, k: model.cell_data(r, k, Qt.DisplayRole)  # noqa: E731
        assert_true(disp(row_unknown, "price") == "Chưa biết", disp(row_unknown, "price"))
        assert_true("6.500.000" in disp(row_no, "price"), disp(row_no, "price"))
        assert_true("Chưa biết" in disp(row_unknown, "ev_support"), disp(row_unknown, "ev_support"))
        assert_true(disp(row_no, "ev_support") == "✕ Không", disp(row_no, "ev_support"))
        assert_true("Chưa biết" in disp(row_unknown, "surveyed"), disp(row_unknown, "surveyed"))
        assert_true(disp(row_no, "surveyed") == "Chưa KS", disp(row_no, "surveyed"))

    # -------------------------------------------------- 5. migration DB cũ NOT NULL
    def t05_migrate_old_db():
        old = tmp / "old_style.db"
        if old.exists():
            old.unlink()
        conn = sqlite3.connect(str(old))
        conn.executescript("""
        CREATE TABLE buildings (
            id TEXT PRIMARY KEY, code TEXT NOT NULL, house_number TEXT NOT NULL DEFAULT '',
            street TEXT NOT NULL DEFAULT '', ward TEXT NOT NULL DEFAULT '',
            district TEXT NOT NULL DEFAULT '', display TEXT NOT NULL DEFAULT '',
            address_key TEXT NOT NULL, owner_name TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '', zalo_group TEXT NOT NULL DEFAULT '',
            ev_policy TEXT NOT NULL DEFAULT '', pet_policy TEXT NOT NULL DEFAULT '',
            commission TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
            search_norm TEXT NOT NULL DEFAULT '', external_ref TEXT NOT NULL DEFAULT '',
            sync_state TEXT NOT NULL DEFAULT 'local', version INTEGER NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL DEFAULT '');
        CREATE TABLE rooms (
            id TEXT PRIMARY KEY, building_id TEXT NOT NULL,
            room_code TEXT NOT NULL DEFAULT '', room_code_key TEXT NOT NULL DEFAULT '',
            unit_code TEXT NOT NULL DEFAULT '', unit_key TEXT NOT NULL DEFAULT '',
            floor TEXT NOT NULL DEFAULT '', room_type TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new', surveyed INTEGER NOT NULL DEFAULT 0,
            price INTEGER NOT NULL DEFAULT 0, deposit INTEGER NOT NULL DEFAULT 0,
            area TEXT NOT NULL DEFAULT '', capacity TEXT NOT NULL DEFAULT '',
            ev_support INTEGER NOT NULL DEFAULT 0, pet_policy TEXT NOT NULL DEFAULT '',
            pet_ok INTEGER NOT NULL DEFAULT 0, rating TEXT NOT NULL DEFAULT '',
            owner_phone TEXT NOT NULL DEFAULT '', zalo_group TEXT NOT NULL DEFAULT '',
            drive_link TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
            foreign_guest INTEGER NOT NULL DEFAULT 0, needs_verify INTEGER NOT NULL DEFAULT 0,
            search_norm TEXT NOT NULL DEFAULT '', external_ref TEXT NOT NULL DEFAULT '',
            sync_state TEXT NOT NULL DEFAULT 'local', version INTEGER NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL DEFAULT '');
        INSERT INTO buildings(id, code, address_key, display) VALUES ('B1','B1','42 duong cu','42 Đường Cũ');
        -- dữ liệu kiểu cũ: ô trống thành 0/'' (đúng như app cũ từng lưu)
        INSERT INTO rooms(id, building_id, room_code, room_code_key, unit_key, price, deposit,
                          floor, capacity, pet_policy, ev_support, surveyed, status, created_at, updated_at)
        VALUES ('R1','B1','CU-1','cu1','cu1', 0, 0, '', '', '', 0, 0, 'vacant','t','t');
        -- dữ liệu thật: đã rõ Có/Không -> PHẢI giữ nguyên sau migration
        INSERT INTO rooms(id, building_id, room_code, room_code_key, unit_key, price, deposit,
                          floor, capacity, pet_policy, ev_support, surveyed, status, created_at, updated_at)
        VALUES ('R2','B1','CU-2','cu2','cu2', 7000000, 3500000, '3', '2Ng', 'Không nuôi', 0, 1, 'vacant','t','t');
        """)
        conn.commit()
        conn.close()

        Database.reset_instance()
        db = Database(str(old))          # mở lại -> migrate tự build lại bảng
        info = {r[1]: r for r in db.query("PRAGMA table_info(rooms)")}
        for c in ("price", "ev_support", "surveyed", "floor", "pet_policy"):
            assert_true(info[c][3] == 0, f"cột {c} vẫn còn NOT NULL sau migration")
        r1 = dict(db.query_one("SELECT * FROM rooms WHERE id='R1'"))
        assert_true(r1["price"] is None and r1["deposit"] is None,
                    f"R1 price/ditelist 0 cũ phải -> NULL: {r1['price']!r}/{r1['deposit']!r}")
        assert_true(r1["floor"] is None and r1["capacity"] is None
                    and r1["pet_policy"] is None,
                    f"R1 chuỗi rỗng cũ phải -> NULL: {r1['floor']!r}/{r1['pet_policy']!r}")
        assert_true(r1["ev_support"] == 0 and r1["surveyed"] == 0,
                    f"R1 ev/surveyed = 0 phải GIỮ 0 (Không/Chưa KS): "
                    f"{r1['ev_support']!r}/{r1['surveyed']!r}")
        r2 = dict(db.query_one("SELECT * FROM rooms WHERE id='R2'"))
        assert_true(r2["price"] == 7000000 and r2["ev_support"] == 0
                    and r2["surveyed"] == 1 and r2["floor"] == "3"
                    and r2["pet_policy"] == "Không nuôi",
                    f"R2 dữ liệu thật bị đổi sau migration: {r2}")
        # index chống trùng vẫn tồn tại
        idx = [r[1] for r in db.query("PRAGMA index_list(rooms)")]
        assert_true("ux_rooms_identity" in idx, f"Mất index chống trùng: {idx}")
        # và sau migration thì lưu NULL được
        mgr = InventoryManager(db)
        mgr.update_room("R1", {"ev_support": None, "price": None}, "t")
        back = db.query_one("SELECT ev_support, price FROM rooms WHERE id='R1'")
        assert_true(back["ev_support"] is None and back["price"] is None,
                    f"Migration xong nhưng vẫn không lưu được NULL: {dict(back)}")
        db.close()

    check("1. add_room toàn None -> đọc lại toàn None (NULL trong DB)", t01_roundtrip_none)
    check("2. update Có<->Chưa biết<->Không không bị sập kiểu", t02_update_to_none)
    check("3. Xuất -> nhập Excel giữ nguyên 3 trạng thái", t03_excel_roundtrip)
    check("4. Search norm / fingerprint / hiển thị bảng phân biệt rõ", t04_search_and_display)
    check("5. Migration DB cũ NOT NULL: build lại bảng + chuyển dữ liệu đúng", t05_migrate_old_db)

    settings.set("google_enabled", old_g, save=False)
    settings.set("db_path", old_db, save=False)
    settings.save()
    Database.reset_instance()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    ok = sum(1 for _, p, _ in RESULTS if p)
    print(f"\n========== TRI-STATE: {ok}/{len(RESULTS)} PASS ==========")
    for n, p, e in RESULTS:
        if not p:
            print(f"  FAIL: {n} :: {e}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
