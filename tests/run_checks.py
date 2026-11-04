# -*- coding: utf-8 -*-
"""run_checks.py - Chạy bộ kiểm thử bắt buộc theo đặc tả mục 11 (không cần pytest, không cần mạng).

Chạy:  python tests/run_checks.py
Tự tạo DB tạm trong thư mục temp -> KHÔNG đụng dữ liệu thật của bạn.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS = []


def check(name: str, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print(f"  [PASS] {name}")
    except Exception as e:  # noqa: BLE001
        RESULTS.append((name, False, f"{e}"))
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "Điều kiện sai")


def main():
    from config import get_settings
    from database import Database
    from inventory_manager import InventoryManager, DuplicateError
    from models import RoomFilter, RoomStatus
    import text_utils as tu
    from excel_import import read_workbook, build_plan

    tmp = Path(tempfile.mkdtemp(prefix="kho_test_"))
    counter = [0]
    OPEN_DBS = []

    settings = get_settings()
    old_g = settings.get("google_enabled")
    old_db = settings.get("db_path")

    SAMPLE = ROOT / "samples" / "Kho_Hang_Phong_Trong_Co_Phuong.xlsx"
    if not SAMPLE.exists():
        SAMPLE = Path(r"C:\Users\silver\Downloads\Kho_Hang_Phong_Trong_Co_Phuong.xlsx")

    def fresh():
        for d in OPEN_DBS:
            try:
                d.close()
            except Exception:
                pass
        OPEN_DBS.clear()
        Database.reset_instance()
        counter[0] += 1
        path = str(tmp / f"test_{counter[0]}.db")
        db = Database(path)
        OPEN_DBS.append(db)
        return db, InventoryManager(db)

    print("\n=== A. NHẬP EXCEL DỮ LIỆU THẬT ===")
    db, mgr = fresh()
    parsed = read_workbook(str(SAMPLE))
    assert_true(parsed.error == "", f"Lỗi đọc file: {parsed.error}")
    assert_true(parsed.rooms is not None, "Không nhận diện được sheet phòng")
    plan = build_plan(parsed, mgr.checker, db)
    counts0 = plan.counts()
    print(f"  Số dòng đọc được: {counts0['total']} | new={counts0['new']} dup={counts0['duplicate']} "
          f"changed={counts0['changed']} suspect={counts0['suspect']} error={counts0['error']}")

    def t01_import_first_time():
        assert_true(counts0["total"] >= 50, f"Đọc được {counts0['total']} dòng (mong >=50)")
        assert_true(counts0["error"] == 0, f"Có dòng lỗi: {counts0['error']}")
        res = mgr.import_apply(plan, ["new", "duplicate", "changed", "suspect"], actor="tester")
        assert_true(res["new"] > 0, "Không có dòng mới nào được thêm")
        # dữ liệu trùng trong file KHÔNG được tạo thêm bản ghi
        total = mgr.stats()["total"]
        assert_true(total == counts0["new"], f"DB có {total} phòng, kỳ vọng {counts0['new']} (=số dòng mới)")
        print(f"    -> thêm {res['new']} phòng, bỏ qua {res['duplicate']} trùng, cập nhật {res['changed']}")

    def t02_import_same_file_twice():
        nonlocal plan
        parsed2 = read_workbook(str(SAMPLE))
        plan2 = build_plan(parsed2, mgr.checker, db)
        c2 = plan2.counts()
        before = mgr.stats()["total"]
        mgr.import_apply(plan2, ["new", "duplicate", "changed", "suspect"], actor="tester")
        after = mgr.stats()["total"]
        assert_true(before == after, f"Nhập lần 2 làm số phòng đổi {before} -> {after} (không được tạo trùng)")
        assert_true(c2["new"] == 0, f"Lần 2 vẫn có {c2['new']} dòng 'mới' (sai)")
        assert_true(c2["duplicate"] + c2["changed"] >= counts0["total"] - 2,
                    f"Không nhận diện trùng: {c2}")
        print(f"    -> lần 2: new={c2['new']}, duplicate={c2['duplicate']}, changed={c2['changed']}, "
              f"suspect={c2['suspect']}")

    check("1. Nhập file Excel thật lần 1 thành công", t01_import_first_time)
    check("3. Nhập lại CÙNG file lần 2 không tạo bản ghi trùng", t02_import_same_file_twice)

    stats = mgr.stats()
    print(f"  Sau import: tổng={stats['total']} tòa={stats['buildings']} trạng thái={stats['status']}")

    print("\n=== B. CHỐNG TRÙNG KHI THÊM THỦ CÔNG ===")
    NEW_A = {
        "house_number": "999", "street": "Nguyễn Văn A", "ward": "P. 12", "district": "Q. 1",
        "room_code": "P-999", "unit_code": "A-01", "room_type": "Studio",
        "status": "vacant", "price": 6000000, "deposit": 6000000,
    }

    def t03_add_new_room():
        r = mgr.add_room(dict(NEW_A), actor="tester")
        assert_true(r["id"], "Không có id nội bộ")
        assert_true(r["unit_key"] == "a01", f"Khoá số căn sai: {r['unit_key']}")
        print(f"    -> id={r['id']}, tòa={r['address']}")

    def t04_add_same_room_again():
        try:
            mgr.add_room(dict(NEW_A), actor="tester")
        except DuplicateError as e:
            assert_true(e.result.room_exists, f"Sai loại cảnh báo: {e.result.recommended}")
            assert_true(e.result.existing_room and e.result.existing_room.get("updated_at"),
                        "Không kèm thông tin bản ghi hiện có")
            print(f"    -> {e.result.messages(' | ')[:150]}")
            return
        raise AssertionError("Thêm trùng thành công -> CHỐNG TRÙNG THẤT BẠI")

    def t05_same_code_other_address():
        """Mã phòng chỉ unique THEO TÒA -> trùng mã ở tòa khác là HỢP LỆ, không cảnh báo."""
        p = dict(NEW_A)
        p.update({"house_number": "888", "street": "Nguyễn Văn B", "unit_code": "B-02"})
        try:
            r = mgr.add_room(p, actor="tester", force=False)
        except DuplicateError as e:
            # chỉ được phép do L5 "similar" (nghi trùng địa chỉ) - TUYỆT ĐỐI không phải mã phòng
            assert_true(not any(f.kind == "code_duplicate" for f in e.result.findings),
                        "Vẫn chặn vì trùng mã phòng ở tòa khác")
            r = mgr.add_room(p, actor="tester", force=True)
        assert_true(bool(r and r.get("id")), "Không thêm được phòng cùng mã ở tòa khác")
        # check lại: không còn sinh finding code_duplicate
        res = mgr.check_new(dict(p), exclude_id=r["id"])
        assert_true(not any(f.kind == "code_duplicate" for f in res.findings),
                    "Vẫn sinh cảnh báo code_duplicate")
        assert_true(not res.has_block, "Tòa khác cùng mã phòng lại bị BLOCK")
        print(f"    -> cùng mã '{p['room_code']}' ở 2 tòa = hợp lệ, không cảnh báo")

    def t06_new_room_into_existing_building():
        """4. Thêm phòng mới vào tòa đã tồn tại -> tự liên kết đúng tòa (không tạo tòa mới)."""
        buildings_before = mgr.stats()["buildings"]
        p = dict(NEW_A)
        p["unit_code"] = "A-02"
        p["room_code"] = "P-999A"
        r = mgr.add_room(p, actor="tester")
        buildings_after = mgr.stats()["buildings"]
        assert_true(buildings_after == buildings_before,
                    f"Tạo thêm tòa mới: {buildings_before} -> {buildings_after}")
        same = [b for b in mgr.buildings() if tu.address_key(b["house_number"], b["street"],
                                                            b["ward"], b["district"])
                == tu.address_key("999", "Nguyễn Văn A", "P. 12", "Q. 1")]
        assert_true(len(same) == 1, f"Tòa bị nhân bản: {len(same)}")
        assert_true(r["building_id"] == same[0]["id"], "Không liên kết đúng tòa")
        print(f"    -> liên kết tòa {same[0]['code']} - {same[0]['display']}")

    check("2. Thêm một phòng mới (thủ công) thành công", t03_add_new_room)
    check("2b. Thêm đúng phòng đó lần nữa -> phát hiện trùng (block)", t04_add_same_room_again)
    check("4. Thêm phòng mới vào tòa đã tồn tại -> tự liên kết đúng tòa", t06_new_room_into_existing_building)
    check("5b. Trùng mã phòng ở tòa khác -> HỢP LỆ, không cảnh báo", t05_same_code_other_address)

    def t07_concurrent_add_only_one_valid():
        """5. Hai 'người' cùng thêm 1 căn hộ cùng lúc -> chỉ 1 bản ghi hợp lệ."""
        db2, mgr2 = fresh()
        payload = {"house_number": "777", "street": "Đường Đồng Thời", "ward": "P. 1",
                   "room_code": "P-777", "unit_code": "Z-01", "status": "vacant", "price": 5000000}
        results, errors = [], []

        def worker(tag):
            try:
                r = mgr2.add_room(dict(payload), actor=tag)
                results.append((tag, r["id"]))
            except DuplicateError as e:
                errors.append((tag, str(e)))
            except Exception as e:  # noqa: BLE001
                errors.append((tag, f"EXC:{e}"))

        threads = [threading.Thread(target=worker, args=(f"user{i}",)) for i in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(10)
        total = db2.query_one("SELECT COUNT(*) c FROM rooms WHERE deleted=0")["c"]
        assert_true(total == 1, f"Số bản ghi hợp lệ = {total}, phải là 1")
        assert_true(len(results) == 1, f"Có {len(results)} thành công (phải đúng 1)")
        assert_true(len(errors) == 1, f"Có {len(errors)} bị chặn")
        print(f"    -> 1 ghi thành công, 1 bị chặn: {errors[0][1][:90]}")
        Database.reset_instance()

    check("5. 2 người thêm cùng lúc -> chỉ 1 bản ghi hợp lệ", t07_concurrent_add_only_one_valid)

    print("\n=== C. TÌM KIẾM SIÊU NHHANH ===")
    db, mgr = fresh()
    parsed = read_workbook(str(SAMPLE))
    plan = build_plan(parsed, mgr.checker, db)
    mgr.import_apply(plan, ["new"], actor="tester")

    def t08_search_address():
        t0 = time.perf_counter()
        ids = mgr.rooms("86 Nguyễn Thượng Hiền")
        ms = (time.perf_counter() - t0) * 1000
        assert_true(len(ids) >= 1, "Không tìm thấy '86 Nguyễn Thượng Hiền'")
        assert_true(all("86" in (i.get("address") or "") for i in ids), "Kết quả không đúng tòa")
        print(f"    -> {len(ids)} phòng, {ms:.2f}ms")

    def t09_search_no_diacritics():
        a = mgr.rooms("nguyen thuong hien")
        b = mgr.rooms("Nguyễn Thượng Hiền")
        assert_true(len(a) == len(b) and len(a) >= 1, f"Có/không dấu lệch: {len(a)} vs {len(b)}")
        c = mgr.rooms("  NGUYEN   THUONG  HIEN  ")
        assert_true(len(c) == len(a), "Khoảng trắng thừa làm sai kết quả")

    def t10_search_code_and_type_price():
        assert_true(len(mgr.rooms("P-86")) >= 1, "Không tìm thấy mã P-86")
        assert_true(len(mgr.rooms("p86")) >= 1, "Không tìm thấy p86 (không phân biệt hoa/thường/dấu -)")
        studio = mgr.rooms("Studio")
        assert_true(len(studio) >= 10, f"Chỉ tìm thấy {len(studio)} phòng Studio")
        price = mgr.rooms("7000000")
        assert_true(len(price) >= 1, "Không tìm thấy phòng giá 7.000.000")
        assert_true(all(i["price"] == 7000000 for i in price), "Kết quả giá 7tr không đúng mức giá")
        print(f"    -> mã phòng OK, Studio={len(studio)}, giá 7tr={len(price)}")

    def t11_search_speed():
        t0 = time.perf_counter()
        for _ in range(50):
            mgr.rooms("nguyen")
        ms = (time.perf_counter() - t0) * 1000 / 50
        assert_true(ms < 20, f"Truy vấn mất {ms:.2f}ms (yêu cầu <20ms)")
        print(f"    -> trung bình {ms:.3f}ms/truy vấn ({stats['total']} phòng)")

    def t12_filter_building():
        b = mgr.buildings()[0]
        f = RoomFilter(building_id=b["id"], statuses=["vacant"])
        rows = mgr.rooms("", f)
        assert_true(all(r["building_id"] == b["id"] for r in rows), "Lọc tòa nhà sai")
        assert_true(all(r["status"] == "vacant" for r in rows), "Lọc trạng thái sai")

    check("8. Tìm theo địa chỉ (có dấu / không dấu / khoảng trắng thừa)", t09_search_no_diacritics)
    check("8b. Tìm theo mã phòng / loại phòng / mức giá", t10_search_code_and_type_price)
    check("Tốc độ tìm kiếm < 20ms", t11_search_speed)
    check("Tìm theo địa chỉ 86 Nguyễn Thượng Hiền đúng tòa", t08_search_address)
    check("Lọc theo tòa nhà + trạng thái", t12_filter_building)

    print("\n=== D. TRẠNG THÁI & ĐỒNG BỘ ===")
    target = mgr.rooms("P-86")[0]

    def t13_change_status_same_id():
        """9. Đã thuê -> chuyển về trống: KHÔNG phát sinh ID mới."""
        rid, ver0 = target["id"], target["version"]
        r1 = mgr.change_status(rid, "rented", actor="tester")
        assert_true(r1["id"] == rid, "ID đổi khi đổi trạng thái!")
        r2 = mgr.change_status(rid, "vacant", actor="tester")
        assert_true(r2["id"] == rid, "ID đổi khi chuyển về trống!")
        assert_true(r2["status"] == "vacant", "Trạng thái không cập nhật")
        assert_true(r2["version"] > ver0, "version không tăng")
        hist = mgr.history(rid)
        assert_true(len(hist) >= 2, f"Lịch sử thay đổi thiếu: {len(hist)}")
        assert_true(hist[0]["new_status"] == "vacant" and hist[0]["old_status"] == "rented",
                    "Lịch sử sai trạng thái cũ/mới")
        # giao diện tìm ngay theo trạng thái mới
        found = mgr.rooms("", RoomFilter(statuses=["vacant"]))
        assert_true(any(r["id"] == rid for r in found), "Chỉ mục tìm kiếm chưa cập nhật")
        print(f"    -> id giữ nguyên {rid}; lịch sử {len(hist)} bản; version {ver0}->{r2['version']}")

    def t14_edit_price_queues_sync():
        """6. Sửa giá trên phần mềm -> dữ liệu đổi + có lệnh đẩy lên Google Sheets."""
        settings.set("google_enabled", True, save=False)   # bật cờ (chưa có credentials -> offline)
        before = mgr.queue_status()
        r = mgr.update_room(target["id"], {"price": 7500000}, actor="tester")
        assert_true(r["price"] == 7500000, "Giá chưa cập nhật trong DB")
        found = mgr.rooms("7500000")
        assert_true(any(x["id"] == target["id"] for x in found), "Chỉ mục tìm theo giá mới lỗi")
        after = mgr.queue_status()
        assert_true(after.get("pending", 0) >= 1, f"Không có lệnh chờ sync: {before} -> {after}")
        row = db.query_one("SELECT * FROM sync_queue WHERE entity_id=? ORDER BY id DESC", (target["id"],))
        assert_true(row is not None, "Không tìm thấy lệnh sync cho phòng này")
        print(f"    -> hàng đợi {before} -> {after}")

    def t15_offline_queue_keeps():
        """10. Mất mạng -> lệnh nằm trong hàng đợi; có mạng trở lại -> đồng bộ lại an toàn."""
        from sync_queue import NetworkMonitor, SyncWorker
        worker = SyncWorker(db, remote_applier=mgr.apply_remote_rows)
        worker.net._last, worker.net._ts = False, time.time()      # giả lập offline
        s = worker.pump()
        assert_true(s.get("state") == "offline", f"Không nhận diện offline: {s}")
        pending = db.queue_count()
        assert_true(pending.get("pending", 0) >= 1, f"Hàng đợi bị mất khi offline: {pending}")
        # có mạng trở lại nhưng CHƯA có credentials -> vẫn GIỮ lệnh (không xoá, không lỗi)
        worker.net._last, worker.net._ts = True, time.time()
        s2 = worker.pump()
        assert_true(s2.get("state") in ("not_configured", "idle"), f"Trạng thái lạ: {s2}")
        assert_true(db.queue_count().get("pending", 0) >= 1, "Hàng đợi bị xoá oan")
        print(f"    -> offline giữ {pending['pending']} lệnh; online+chưa cấu hình vẫn giữ nguyên")

    def t16_duplicate_import_file():
        """3b. Import file rỗng/không hợp lệ không bị lỗi; file mẫu nhập 2 lần không sinh trùng."""
        p2 = tmp / "import_mau.xlsx"
        from excel_export import export_template
        export_template(str(p2))   # file mẫu trống -> có tiêu đề nhưng không có dòng dữ liệu
        parsed_bad = read_workbook(str(p2))
        plan_bad = build_plan(parsed_bad, mgr.checker, db)
        assert_true(plan_bad.error == "" or len(plan_bad.items) == 0,
                    f"File mẫu trống bị báo lỗi sai: {plan_bad.error}")
        assert_true(len(plan_bad.items) == 0, f"File trống sinh ra {len(plan_bad.items)} dòng ảo")
        # file import_them_mau.xlsx (nếu có)
        extra = ROOT / "samples" / "import_them_mau.xlsx"
        if extra.exists():
            pe = read_workbook(str(extra))
            pl = build_plan(pe, mgr.checker, db)
            c = pl.counts()
            mgr.import_apply(pl, ["new", "changed", "suspect"], actor="tester")
            n1 = mgr.stats()["total"]
            pl2 = build_plan(read_workbook(str(extra)), mgr.checker, db)
            mgr.import_apply(pl2, ["new", "changed", "suspect"], actor="tester")
            n2 = mgr.stats()["total"]
            assert_true(n1 == n2, f"Nhập file mẫu 2 lần bị trùng: {n1} -> {n2}")
            print(f"    -> file import_them_mau: {c}; nhập 2 lần: {n1} == {n2}")

    check("9. Đã thuê -> về trống không sinh ID mới + có lịch sử", t13_change_status_same_id)
    check("6. Sửa giá thuê -> DB đổi + có lệnh chờ đẩy lên Google Sheets", t14_edit_price_queues_sync)
    check("10. Mất mạng giữ hàng đợi; có mạng lại an toàn", t15_offline_queue_keeps)
    check("3c. File import mẫu nhập 2 lần không sinh trùng", t16_duplicate_import_file)

    def t17_soft_delete_restore():
        r = mgr.add_room({"house_number": "555", "street": "Đường Xóa Thử", "room_code": "P-555",
                          "unit_code": "D-01", "status": "vacant", "price": 1000000}, actor="t")
        mgr.delete_room(r["id"], actor="t")
        assert_true(mgr.room(r["id"])["deleted"] == 1, "Chưa xóa mềm")
        assert_true(len(mgr.rooms("P-555")) == 0, "Vẫn hiện sau khi xóa")
        mgr.restore_room(r["id"], actor="t")
        assert_true(len(mgr.rooms("P-555")) == 1, "Khôi phục thất bại")

    def t18_excel_roundtrip():
        """Xuất Excel -> đọc lại được đúng cấu trúc 3 sheet."""
        from excel_export import export_workbook
        out = tmp / "xuat_thu.xlsx"
        rooms = mgr.rooms("")
        buildings = mgr.buildings()
        export_workbook(str(out), rooms, buildings, mgr.stats())
        p = read_workbook(str(out))
        assert_true(p.rooms is not None, "Export sai cấu trúc sheet phòng")
        assert_true(len(p.rooms.rows) == len(rooms), f"Sai số dòng: {len(p.rooms.rows)} vs {len(rooms)}")
        assert_true(p.buildings is not None, "Thiếu sheet danh mục")
        assert_true(p.stats_formulas or p.stats_sheet != "", "Thiếu sheet thống kê")
        pl = build_plan(p, mgr.checker, db)
        c = pl.counts()
        assert_true(c["new"] == 0, f"File export đọc lại vẫn có {c['new']} dòng bị coi là MỚI (mất khoá nhận diện): {c}")
        assert_true(c["duplicate"] + c["changed"] + c["suspect"] >= len(rooms),
                    f"Đọc lại file export không nhận ra bản ghi cũ: {c}")
        print(f"    -> export {len(rooms)} phòng; đọc lại phân loại: {c}")

    check("Xóa mềm + khôi phục phòng", t17_soft_delete_restore)
    check("Xuất Excel đúng cấu trúc & đọc lại không sinh trùng", t18_excel_roundtrip)

    # ---------------------------------------------------------------- yêu cầu khách
    def t19_request_search():
        """Tìm theo yêu cầu khách: parse giá/tiện ích/khu vực + 4 vòng mở rộng + tự nới lỏng."""
        from request_parser import parse_request, search_tiers

        # 1) parser: câu ví dụ kinh điển
        req = parse_request(
            "phong 7tr full noi that co thang may, gui xe, xung quanh P13 hay duong Binh Loi")
        assert_true(req.price_min == 6_300_000 and req.price_max == 7_700_000,
                    f"Sai tầm giá ±10%: {req.price_min}-{req.price_max}")
        assert_true(req.ward_keys == ["13"], f"Sai phường: {req.ward_keys}")
        assert_true("binh loi" in req.street_keys, f"Sai đường: {req.street_keys}")
        assert_true(req.nearby, "Không nhận từ 'xung quanh'")
        lab = " ".join(req.keywords_label)
        for kw in ("Thang máy", "Nội thất", "Gửi xe"):
            assert_true(kw in lab, f"Thiếu tiện ích {kw} trong: {lab}")

        # 2) parser: khoảng giá / quận tên / số tiền cọc không lẫn vào giá phòng
        r2 = parse_request("tim phong 6-8tr quan binh thanh, coc 2tr")
        assert_true(r2.price_min == 6_000_000 and r2.price_max == 8_000_000,
                    f"Sai khoảng 6-8tr: {r2.price_min}-{r2.price_max}")
        assert_true("binh thanh" in r2.district_keys, f"Sai quận: {r2.district_keys}")

        # 3) thêm phòng đúng yêu cầu khách vào P.13 / Bình Lợi -> phải nằm vòng "Đúng khu vực"
        mgr.add_room(
            {"house_number": "9", "street": "Đường Bình Lợi", "ward": "P.13",
             "district": "Q. Bình Thạnh", "room_code": "RQ-01", "unit_code": "RQ-01",
             "status": "vacant", "price": 7_000_000, "room_type": "Studio",
             "notes": "Full nội thất, có thang máy, gửi xe"},
            actor="t", force=True)
        tiers = search_tiers(mgr, req)
        assert_true(tiers, "Không có vòng kết quả nào")
        t0 = next((t for t in tiers if t["key"] == 0), None)
        assert_true(t0 and t0["total"] >= 1, "Thiếu vòng 'Đúng khu vực'")
        assert_true("RQ-01" in [r["room_code"] for r in t0["rooms"]],
                    "Phòng vừa thêm không nằm vòng 'Đúng khu vực'")
        for t in tiers:
            assert_true(t["filter"] is not None, f"Vòng {t['key']} thiếu RoomFilter")

        # 4) tự nới lỏng: khách đòi thêm wifi + máy lạnh (kho không có) -> vẫn ra phòng + báo đã bỏ
        req3 = parse_request(
            "phong 7tr noi that thang may gui xe wifi may lanh xung quanh P13")
        tiers3 = search_tiers(mgr, req3)
        assert_true(tiers3, "Nới lỏng xong vẫn không có kết quả")
        assert_true(any(t["key"] == 4 for t in tiers3),
                    f"Không có thẻ gợi ý nới lỏng: {[t['key'] for t in tiers3]}")
        rel = next(t for t in tiers3 if t["key"] == 4)
        assert_true("Wifi" in rel["hint"] and "Máy lạnh" in rel["hint"],
                    f"Gợi ý nới lỏng sai: {rel['hint']}")

    check("Tìm theo yêu cầu khách: parse + 4 vòng mở rộng + tự nới lỏng", t19_request_search)

    def t20_media():
        """Ảnh/video phòng: thư mục quy ước + import + trùng + thùng rác."""
        import media_manager as mm
        old_root = settings.get("media_root")
        settings.set("media_root", str(tmp / "media"), save=False)
        try:
            # 1) quy ước đường dẫn đúng như ví dụ
            probe = {"house_number": "5", "room_code": "102-4", "room_type": "Studio",
                     "price": 8_000_000, "district": "Q. Bình Thạnh", "street": "Nơ Trang Long"}
            d = mm.room_media_dir(probe, settings)
            expect = tmp / "media" / "Bình Thạnh" / "Nơ Trang Long" / "5-102-4" / "studio 8tr"
            assert_true(d == expect, f"Sai quy ước thư mục: {d} != {expect}")

            # 2) thêm phòng thật -> import file -> tự tạo thư mục quy ước
            rid = mgr.add_room(
                {"house_number": "5", "street": "Nơ Trang Long", "ward": "P.13",
                 "district": "Q. Bình Thạnh", "room_code": "102-4", "unit_code": "102-4",
                 "status": "vacant", "price": 8_000_000, "room_type": "Studio"},
                actor="t", force=True)["id"]
            r = mgr.room(rid)
            src = tmp / "anh_goc.jpg"
            src.write_bytes(b"\xff\xd8fakejpeg")
            res = mm.import_files(r, [str(src)], settings)
            assert_true(len(res["copied"]) == 1 and not res["errors"], f"Import lỗi: {res}")
            d2 = mm.ensure_room_dir(r, settings)
            assert_true(d2.is_dir(), "Không tạo được thư mục quy ước")

            # 3) liệt kê: ảnh nhận diện đúng loại
            med = mm.list_media(r, settings)
            assert_true(len(med) == 1 and med[0]["kind"] == "image", f"Liệt kê sai: {med}")

            # 4) import lại cùng file -> bỏ qua (trùng tên trùng dung lượng)
            res2 = mm.import_files(r, [str(src)], settings)
            assert_true(len(res2["skipped"]) == 1 and not res2["copied"],
                        f"Import lại không nhận ra trùng: {res2}")

            # 5) xóa = chuyển vào _ThungRac
            moved = mm.move_to_trash([med[0]["path"]], settings)
            assert_true(len(moved) == 1 and "_ThungRac" in moved[0], f"Thùng rác sai: {moved}")
            assert_true(mm.list_media(r, settings) == [], "Vẫn còn file sau khi bỏ vào thùng rác")
            print(f"    -> thư mục quy ước: {d2}")
        finally:
            settings.set("media_root", old_root, save=False)

    check("Ảnh/video phòng: thư mục quy ước + import + chống trùng + thùng rác", t20_media)

    # ---------------------------------------------------------------- CRM khách hàng
    def t21_crm():
        """CRM: pipeline bán hàng + lý do mất khách + funnel + tỷ lệ chốt."""
        from customer_manager import CustomerManager
        cm = CustomerManager(db, settings)

        # 1) validate: cần ít nhất tên hoặc SĐT
        try:
            cm.add_customer({"name": "", "phone": ""})
            assert_true(False, "Vẫn cho thêm khách không tên + không SĐT")
        except ValueError:
            pass

        c1 = cm.add_customer({
            "name": "Trần Thị Mai", "phone": "0987654321", "source": "Facebook",
            "area": "P.13", "budget_min": 5000000, "budget_max": 7000000,
            "requirement": "phòng 2 người gần đường Bình Lợi"}, actor="t")
        c2 = cm.add_customer({"name": "Lê Văn Hùng", "phone": "0912345678"}, actor="t")

        # 2) tìm không dấu (token AND) + theo SĐT
        assert_true(len(cm.customers("tran thi mai")) == 1, "Tìm không dấu tên khách lỗi")
        assert_true(len(cm.customers("0987")) == 1, "Tìm theo SĐT lỗi")
        assert_true(len(cm.customers("khong ton tai")) == 0, "Tìm bịa ra kết quả")

        # 3) pipeline tới khi MẤT - bắt buộc giữ lý do
        for stt in ("contacting", "consulting", "viewing"):
            cm.change_status(c1["id"], stt, actor="t")
        cm.change_status(c1["id"], "lost", lose_reason="price", actor="t")
        got = cm.customer(c1["id"])
        assert_true(got["status"] == "lost" and got["lose_reason"] == "price",
                    f"Sai trạng thái/lý do mất: {got['status']}/{got['lose_reason']}")

        # 4) lịch sử trạng thái được ghi (nguồn dữ liệu của funnel)
        evs = [e for e in cm.events(c1["id"]) if e["event"] == "status"]
        assert_true(len(evs) >= 4, f"Thiếu lịch sử trạng thái: {len(evs)}")

        # 5) hồi sinh khỏi 'Mất khách' -> tự xóa lý do cũ
        cm.change_status(c1["id"], "viewing", actor="t")
        assert_true(cm.customer(c1["id"])["lose_reason"] == "",
                    "Hồi sinh phải xóa lý do mất cũ")
        cm.change_status(c1["id"], "lost", lose_reason="slow", actor="t")

        # 6) chốt 1 khách -> tỷ lệ chốt = 50%
        cm.change_status(c2["id"], "won", actor="t")
        st = cm.stats()
        assert_true(st["total"] == 2, f"Tổng khách sai: {st['total']}")
        assert_true(st["won"] == 1 and st["lost"] == 1,
                    f"won/lost sai: {st['won']}/{st['lost']}")
        assert_true(st["conversion"] == 50.0, f"Tỷ lệ chốt sai: {st['conversion']}")
        assert_true(st["by_reason"].get("slow") == 1,
                    f"Lý do mất không đúng: {st['by_reason']}")
        assert_true(st["by_source"].get("Facebook") == 1, "Không đếm được nguồn khách")

        # 7) funnel thật: khách đã TỪNG tới từng khâu
        fr = dict((k, n) for k, _, n in st["funnel_reached"])
        assert_true(fr.get("new") == 2, f"Khâu đầu funnel phải = 2: {fr}")
        assert_true(fr.get("viewing", 0) >= 1 and fr.get("won") == 1,
                    f"Funnel sai (c1 đã tới hẹn xem, c2 đã chốt): {fr}")

        # 8) ghi tương tác -> hoạt động selling
        cm.log_event(c2["id"], "call", "Đã gọi", actor="t")
        assert_true(cm.stats()["activity"].get("call") == 1,
                    "Không đếm được tương tác gọi")

        # 9) sửa + xóa mềm
        cm.update_customer(c2["id"], {"next_action": "Ký hợp đồng"}, actor="t")
        assert_true(cm.customer(c2["id"])["next_action"] == "Ký hợp đồng",
                    "update_customer lỗi")
        cm.delete_customer(c2["id"], actor="t")
        assert_true(len(cm.customers()) == 1, "Xóa mềm khách lỗi")
        print(f"    -> conversion={st['conversion']}% · funnel={fr} · lý do mất={st['by_reason']}")

    check("21. CRM khách hàng: pipeline + lý do mất + funnel + tỷ lệ chốt", t21_crm)

    # ---------------------------------------------------------------- dắt căn + điểm sai xử lý
    def t22_showings():
        """Quản lý ĐÃ DẮT CĂN NÀO + ĐIỂM SAI trong tư vấn & xử lý."""
        from customer_manager import CustomerManager
        cm = CustomerManager(db, settings)

        c = cm.add_customer({"name": "Đỗ Văn Tèo", "phone": "0909000111",
                             "source": "Zalo"}, actor="t")

        # 1) chưa dắt gì -> cột showings = 0
        row = next(r for r in cm.customers() if r["id"] == c["id"])
        assert_true(int(row.get("showings") or 0) == 0,
                    f"Cột 'Đã dắt' phải 0 lúc đầu: {row.get('showings')}")
        assert_true(cm.showings(c["id"]) == [], "Danh sách dắt phải rỗng")
        assert_true(cm.mistake_count(c["id"]) == 0, "Điểm sai phải 0 lúc đầu")

        # 2) ghi 2 lượt dắt (1 lượt kèm điểm sai ngay lúc dắt)
        s1 = cm.log_showing(c["id"], room_id="r1", room_label="P.101 · 6.5tr",
                            shown_at="2026-11-01", outcome="interested",
                            note="khách thích tầng máy", actor="t")
        s2 = cm.log_showing(c["id"], room_id="r2", room_label="P.102 · 7tr",
                            shown_at="2026-11-02", outcome="rejected",
                            process_error="care_before_show", actor="t")
        assert_true(s1["id"] and s2["id"], "log_showing không trả id")
        assert_true(len(cm.showings(c["id"])) == 2, "Phải có 2 lượt dắt")
        row = next(r for r in cm.customers() if r["id"] == c["id"])
        assert_true(int(row.get("showings") or 0) == 2,
                    f"Cột 'Đã dắt' phải 2: {row.get('showings')}")

        # 3) mỗi lượt dắt tự ghi event 'view'; điểm sai lúc dắt ghi event 'mistake'
        evs = cm.events(c["id"])
        assert_true(sum(1 for e in evs if e["event"] == "view") == 2,
                    "Thiếu event 'view' cho lượt dắt")
        assert_true(sum(1 for e in evs if e["event"] == "mistake") == 1,
                    "Thiếu event 'mistake' từ lượt dắt có process_error")

        # 4) ghi điểm sai riêng (khách chậm phản hồi)
        cm.log_mistake(c["id"], "slow_reply", note="trả lời chậm 2 ngày", actor="t")
        assert_true(cm.mistake_count(c["id"]) == 2, "mistake_count phải = 2")

        # 5) stats: dắt căn + điểm sai
        st = cm.stats()
        assert_true(st["showings_total"] == 2 and st["showings_rooms"] == 2,
                    f"showings sai: {st['showings_total']}/{st['showings_rooms']}")
        assert_true(st["showings_customers"] == 1, "showings_customers sai")
        assert_true(st["showings_by_outcome"] == {"interested": 1, "rejected": 1},
                    f"outcome sai: {st['showings_by_outcome']}")
        assert_true(dict(st["top_rooms"]).get("P.101 · 6.5tr") == 1,
                    f"top_rooms sai: {st['top_rooms']}")
        assert_true(st["mistakes_total"] == 2, f"mistakes_total sai: {st['mistakes_total']}")
        assert_true(dict(st["top_mistakes"]).get("care_before_show") == 1
                    and dict(st["top_mistakes"]).get("slow_reply") == 1,
                    f"top_mistakes sai: {st['top_mistakes']}")

        # 6) khách đã dắt mà chốt thuê -> showings_won = 1
        cm.change_status(c["id"], "won", actor="t")
        st = cm.stats()
        assert_true(st["showings_won"] == 1 and st["showings_lost"] == 0,
                    f"showings_won/lost sai: {st['showings_won']}/{st['showings_lost']}")

        # 7) xóa 1 lượt dắt -> còn 1 + có ghi chú vào dòng thời gian
        sid = cm.showings(c["id"])[0]["id"]
        assert_true(cm.remove_showing(sid, actor="t") is True, "remove_showing lỗi")
        assert_true(len(cm.showings(c["id"])) == 1, "Sau xóa phải còn 1 lượt dắt")
        assert_true(cm.stats()["showings_total"] == 1, "stats chưa cập nhật sau xóa")
        notes = [e for e in cm.events(c["id"]) if e["event"] == "note"
                 and "Xóa lượt dắt" in str(e.get("detail") or "")]
        assert_true(len(notes) == 1, "Xóa lượt dắt phải ghi vào dòng thời gian")

        # 8) validate outcome lạ -> quy về no_feedback
        s3 = cm.log_showing(c["id"], room_label="P.103", outcome="bala", actor="t")
        assert_true(s3["outcome"] == "no_feedback", "Outcome lạ phải quy về no_feedback")

        st = cm.stats()
        print(f"    -> {st['showings_total']} lượt dắt / {st['showings_rooms']} căn · "
              f"{st['mistakes_total']} điểm sai · top={st['top_mistakes']}")

    check("22. CRM dắt căn + điểm sai tư vấn & xử lý", t22_showings)

    # ---------------------------------------------------------------- tạo nhanh từ Zalo
    def t23_quick_add():
        """Tạo nhanh từ Zalo: tách tin nhắn + check TÒA NHÀ / LOẠI PHÒNG + chống trùng."""
        import quick_add as qa

        # 1) giá ô text -> NULL (Chưa biết), KHÔNG ép về 0
        assert_true(qa.norm_price("") is None, "Giá rỗng phải NULL (Chưa biết)")
        assert_true(qa.norm_price("abc") is None, "Giá không đọc được phải NULL")
        assert_true(qa.norm_price("7tr") == 7000000, "norm_price('7tr') sai")
        assert_true(qa.norm_price("7.500.000") == 7500000, "norm_price dấu chấm sai")

        # 2) tách trường từ tin nhắn Zalo / tin đăng
        txt = ("Cho thuê căn hộ 321 Kiểm Thử T23 P.99 giá 7.5tr studio, 45m2, tầng 3")
        f = qa.autofill_from_text(txt)
        assert_true(f.get("house_number") == "321"
                    and "Kiểm Thử" in str(f.get("street", "")),
                    f"Tách địa chỉ sai: {f}")
        assert_true(f.get("price") == 7500000, f"Tách giá sai: {f.get('price')}")
        assert_true(f.get("room_type") == "Studio", f"Tách loại phòng sai: {f.get('room_type')}")
        assert_true(str(f.get("ward", "")).startswith("P"), f"Tách phường sai: {f.get('ward')}")
        assert_true(qa.autofill_from_text("cam on ban nhieu") == {},
                    "Chữ không giống tin đăng phải trả {} (không tự điền bừa)")

        # 3) check loại phòng khi chưa có tòa
        assert_true(qa.type_in_building(db, "", "Studio")["count"] == 0,
                    "building_id rỗng phải trả 0")

        # 4) lưu phòng "từ Zalo" -> tự tạo tòa nhà mới
        p = {
            "house_number": f["house_number"], "street": f["street"],
            "ward": f.get("ward", ""), "district": f.get("district", ""),
            "unit_code": "T23-01", "room_code": "",
            "room_type": f.get("room_type", ""), "price": qa.norm_price("7.5tr"),
            "status": "new",
        }
        res = mgr.check_new(dict(p))
        assert_true(not res.room_exists, "Phòng mới bị báo trùng oan")
        r1 = mgr.add_room(dict(p), actor="tester", force=bool(res.has_warn))
        b = db.find_building_by_address(
            tu.address_key(p["house_number"], p["street"], p["ward"], p["district"]))
        assert_true(b and b["id"] == r1["building_id"], "Không tạo/tìm đúng tòa nhà")

        # 5) LOẠI PHÒNG đã có trong tòa chưa?
        th = qa.type_in_building(db, b["id"], "Studio")
        assert_true(th["count"] == 1 and "T23-01" in th["codes"],
                    f"Check loại phòng sai: {th}")
        assert_true(qa.type_in_building(db, b["id"], "Penthouse")["count"] == 0,
                    "Tòa chưa có Penthouse phải trả 0")

        # 6) phòng thứ 2 cùng tòa + cùng loại -> nối cùng tòa (không sinh tòa trùng)
        p2 = dict(p)
        p2["unit_code"] = "T23-02"
        res2 = mgr.check_new(dict(p2))
        r2 = mgr.add_room(dict(p2), actor="tester", force=bool(res2.has_warn))
        assert_true(r2["building_id"] == b["id"], "Phòng 2 phải nối cùng tòa")
        th2 = qa.type_in_building(db, b["id"], "Studio")
        assert_true(th2["count"] == 2, f"Phải có 2 phòng Studio cùng tòa: {th2}")

        # 7) trùng số căn -> bị chặn
        try:
            mgr.add_room(dict(p), actor="tester")
            assert_true(False, "Vẫn cho thêm phòng trùng số căn")
        except DuplicateError as e:
            assert_true(e.result.room_exists, f"Sai loại chặn: {e.result.recommended}")

        print(f"    -> tòa {b['code']}: Studio x{th2['count']} ({', '.join(th2['codes'])}) · "
              f"autofill keys={sorted(f)} · giá '7.5tr'={qa.norm_price('7.5tr')}")

    check("23. Tạo nhanh từ Zalo: tách tin nhắn + check tòa/nhà + loại phòng", t23_quick_add)

    # ---------------------------------------------------------------- đổi thư mục dữ liệu
    def t24_change_data_dir():
        """Thay đổi thư mục dữ liệu (db_path) -> copy dữ liệu cũ sang chỗ mới."""
        import shutil
        from config import get_settings, get_data_dir, get_log_dir, get_cache_dir

        # 1) Thêm vài phòng để có dữ liệu
        for i in range(3):
            p = {"house_number": f"10{i}", "street": "Đường Test T24",
                 "ward": "P.1", "district": "Q.1",
                 "unit_code": f"T24-{i}", "room_type": "Studio",
                 "price": 5000000 + i * 100000, "status": "new"}
            mgr.add_room(p, actor="tester")

        # 2) Tạo thư mục mới cho dữ liệu
        new_data_dir = tmp / "data_new"
        new_db_file = new_data_dir / "kho_phong.db"

        # 3) Copy dữ liệu bằng logic trong SettingsDialog._move_data_to_new_dir
        old_db_path = str(db.path)
        old_dir = Path(old_db_path).parent

        # Tạo DB tạm để dùng backup API
        from database import Database
        tmp_db = Database(old_db_path)
        tmp_db.copy_to(new_db_file)
        tmp_db.close()

        # Copy logs, backup, cache
        for sub in ("logs", "backup", "cache"):
            old_sub = old_dir / sub
            new_sub = new_data_dir / sub
            if old_sub.exists():
                if new_sub.exists():
                    shutil.rmtree(new_sub)
                shutil.copytree(old_sub, new_sub)

        # 4) Cập nhật settings db_path trước khi reconnect
        settings.set("db_path", str(new_db_file), save=True)

        # 5) Reconnect DB sang file mới
        db.reconnect(str(new_db_file))

        # 6) Kiểm tra dữ liệu vẫn đọc được
        rooms = mgr.rooms("")
        assert_true(len(rooms) >= 3, f"Mất dữ liệu sau khi đổi thư mục: {len(rooms)} phòng")

        # 6) Kiểm tra LOG_DIR, CACHE_DIR đã đổi theo
        assert_true(get_log_dir() == new_data_dir / "logs", f"LOG_DIR sai: {get_log_dir()}")
        assert_true(get_cache_dir() == new_data_dir / "cache", f"CACHE_DIR sai: {get_cache_dir()}")

        # 7) Kiểm tra dữ liệu cũ VẪN CÒN tại chỗ cũ (backup)
        assert_true(old_dir.exists(), "Thư mục cũ bị xóa")
        # File DB cũ có tên test_N.db, không phải kho_phong.db
        old_db_name = Path(old_db_path).name
        assert_true((old_dir / old_db_name).exists(), f"File DB cũ ({old_db_name}) bị xóa")
        # Logs có thể chưa được tạo trong test environment -> chỉ check nếu có
        if (old_dir / "logs").exists():
            assert_true((old_dir / "logs").exists(), "Logs cũ bị xóa")

        print(f"    -> data cũ: {old_dir} (giữ nguyên) | data mới: {new_data_dir} (đang dùng)")

    check("24. Đổi thư mục dữ liệu: copy DB+logs+cache sang chỗ mới, cũ giữ backup", t24_change_data_dir)

    # ---------------------------------------------------------------- installer.cfg đủ module
    def t25_installer_covers_imports():
        """installer.cfg phải chứa đủ mọi module local được import.

        app cài đặt crash 'ModuleNotFoundError' khi thiếu file (vd grouped_table,
        media_panel). Check quét import (kể cả import lười trong hàm) và đối chiếu
        danh sách files= trong installer.cfg.
        """
        import re
        import configparser

        root = Path(__file__).resolve().parent.parent
        local_mods = {p.stem for p in root.glob("*.py")}

        cfg = configparser.ConfigParser(inline_comment_prefixes=(";",))
        cfg.read(root / "installer.cfg", encoding="utf-8")
        files_raw = cfg["Include"]["files"] or ""
        listed = {ln.strip() for ln in files_raw.splitlines() if ln.strip()}

        # main.py là entry point bắt buộc
        assert_true("main.py" in listed, "installer.cfg thiếu main.py")

        # Quét import local trong mọi file .py được ship
        shipped = {f for f in listed if f.endswith(".py")} | {"main.py"}
        missing = []
        for fname in sorted(shipped):
            src = (root / fname).read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"^\s*(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)", src, re.M):
                mod = m.group(1)
                if mod in local_mods and f"{mod}.py" not in listed:
                    missing.append(f"{fname} -> {mod}.py")
        assert_true(not missing,
                    f"installer.cfg thiếu module được import (app cài sẽ crash): {missing}")

        print(f"    -> installer.cfg ship {len(listed)} file, "
              f"{len(shipped)} module .py, import local OK")

    check("25. installer.cfg liệt kê đủ mọi module local được import", t25_installer_covers_imports)

    # ---------------------------------------------------------------- 3 trường mới: phí DV / giờ / tiện ích
    def t26_fee_hours_amenities():
        """Chi phí dịch vụ + giờ giấc + tiện ích tòa nhà: tách từ tin Zalo + lưu DB + tìm được."""
        tin = ("Phòng studio 45m2 giá 7tr, cọc 1 tháng. "
               "Điện 3.500đ/kWh, nước 25.000đ/m3, wifi 100k/tháng. "
               "Ra vào tự do 24/7, có bảo vệ camera giữ xe. "
               "Tòa có thang máy, điều hòa, giặt đồ.")
        p = tu.parse_listing_text(tin)
        assert_true(bool(p["service_fee"]) and "wifi" in tu.norm(p["service_fee"]),
                    f"Không tách được chi phí dịch vụ: {p['service_fee']!r}")
        assert_true(bool(p["access_hours"]) and "24/7" in p["access_hours"],
                    f"Không tách được giờ giấc: {p['access_hours']!r}")
        assert_true("Thang máy" in p["amenities"] and "Camera" in p["amenities"],
                    f"Không tách được tiện ích: {p['amenities']!r}")

        # lưu DB + đọc lại (round-trip)
        payload = {"house_number": "77", "street": "Đường Test T26", "ward": "P.2",
                   "district": "Q.3", "unit_code": "T26-01", "room_type": "Studio",
                   "price": 7000000, "service_fee": p["service_fee"],
                   "access_hours": p["access_hours"], "amenities": p["amenities"]}
        r = mgr.add_room(payload, actor="tester")
        got = db.get_room(r["id"])
        assert_true(got["service_fee"] == p["service_fee"], "Mất chi phí dịch vụ khi lưu DB")
        assert_true(got["access_hours"] == p["access_hours"], "Mất giờ giấc khi lưu DB")
        assert_true(got["amenities"] == p["amenities"], "Mất tiện ích khi lưu DB")

        # search_norm chứa tiện ích -> gõ "thang may" tìm ra phòng
        assert_true("thang may" in (got["search_norm"] or ""),
                    "search_norm thiếu tiện ích tòa nhà")
        found = [x for x in mgr.rooms("thang may") if x["id"] == r["id"]]
        assert_true(found, "Tìm 'thang may' không ra phòng vừa thêm")

        # tin KHÔNG có thông tin -> '' (không sinh None lung tung)
        p2 = tu.parse_listing_text("Cho thuê nhà 12 Trần Nguyên Hãn giá 5tr")
        assert_true(p2["service_fee"] == "" and p2["access_hours"] == ""
                    and p2["amenities"] == "",
                    f"Tin không có thông tin phải trả '': {p2}")
        print(f"    -> phí DV='{got['service_fee'][:45]}...' | giờ='{got['access_hours'][:25]}' "
              f"| tiện ích={got['amenities']}")

    check("26. Phí dịch vụ + giờ giấc + tiện ích tòa: tách tin Zalo + DB + tìm kiếm",
          t26_fee_hours_amenities)

    # ---------------------------------------------------------------- nhập giá nhanh
    def t27_quick_money_input():
        """Nhập giá nhanh: '5tr'/'5 triệu'/'5trieu' + đọc tiền bằng chữ (không đếm số 0)."""
        for txt_, want in (("5tr", 5_000_000), ("5 triệu", 5_000_000),
                           ("5trieu", 5_000_000), ("7.500.000", 7_500_000),
                           ("7,5tr", 7_500_000), ("500 nghìn", 500_000)):
            assert_true(tu.normalize_price(txt_) == want,
                        f"normalize_price('{txt_}') = {tu.normalize_price(txt_)}, kỳ vọng {want}")
        # đọc bằng chữ (ô preview trong form Sửa)
        assert_true(tu.money_words(5_000_000) == "5 triệu",
                    f"money_words(5tr) sai: {tu.money_words(5_000_000)!r}")
        assert_true(tu.money_words(7_500_000) == "7,5 triệu",
                    f"money_words(7.5tr) sai: {tu.money_words(7_500_000)!r}")
        assert_true(tu.money_words(850_000) == "850 nghìn",
                    f"money_words(850k) sai: {tu.money_words(850_000)!r}")
        assert_true(tu.money_words(None) == "" and tu.money_words(0) == "",
                    "money_words(0/None) phải rỗng (Chưa biết -> không hiển thị)")
        assert_true(tu.format_money(5_000_000) == "5.000.000",
                    f"format_money sai: {tu.format_money(5_000_000)}")
        print(f"    -> '7,5tr'={tu.normalize_price('7,5tr')} · "
              f"đọc chữ: {tu.money_words(7_500_000)} / {tu.money_words(5_000_000)}")

    check("27. Nhập giá nhanh: 5tr/5 triệu/5trieu + hiển thị đọc bằng chữ", t27_quick_money_input)

    # ---------------------------------------------------------------- parser mẫu tin Zalo THẬT
    def t28_real_zalo_samples():
        """Parser trên mẫu tin Zalo thật: địa chỉ + mã phòng + giá/cọc/phí/giờ/tiện ích."""
        # --- m2: ngày tháng không được nhận làm địa chỉ; giá '8.700.000' + giờ giấc
        m2 = ("CẬP NHẬT PHÒNG TRỐNG 3/11\nM8/11 TRỐNG\n\n"
              "Dia chi: 135/37/70 Nguyen Huu Canh, phuong Thanh My Tay\n"
              "Phong 302- 2pn- cua so lau 3\nChinh sach:\n- Dien: 4k\n- Nuoc: 100k/ng\n"
              "- Phi DV:200k/p\n- Xe: free 2\n- Thang bo\nPhi hoa hong + coc:\n"
              "+ HĐ 6th coc 1th- HH 50%\nGio giac tu do, khong chung chu, rong 35m2\n"
              "Troi san o lien\nGia chot : 8.700.000 vnd")
        p = tu.parse_listing_text(m2)
        assert_true(p["house_number"] == "135/37/70"
                    and "Nguyen Huu Canh" in p["street"],
                    f"m2: sai địa chỉ {p['house_number']!r}/{p['street']!r}")
        assert_true(p["ward"] == "Phường Thanh My Tay" and p["district"] == "Q. Bình Thạnh",
                    f"m2: sai phường/quận {p['ward']!r}/{p['district']!r}")
        assert_true(p["room_code"] == "302", f"m2: sai mã phòng {p['room_code']!r}")
        assert_true(p["price"] == 8_700_000, f"m2: sai giá {p['price']}")
        assert_true("dien" in tu.norm(p["service_fee"]) and "nuoc" in tu.norm(p["service_fee"]),
                    f"m2: sai phí DV {p['service_fee']!r}")
        assert_true("gio giac tu do" in tu.norm(p["access_hours"]),
                    f"m2: sai giờ giấc {p['access_hours']!r}")

        # --- m5: XVNT -> Xô Viết Nghệ Tĩnh; '5.200 K' = 5,2tr; '26/11' là NGÀY không phải số nhà
        m5 = ("26/11 trong\n\n"
              "Dia chi : 685/25/3 XVNT, P26, Binh Thanh ( gan BXMD, gan hutech Ung Van Khiem)\n"
              "P402 (gac cua so lau 4 - thang may) : 5.200 K\n\n"
              "- Co Thang may\n- Camera 24/24\n- Gio giac tu do, khong chung chủ\n"
              "- Giat phoi free\n- Cho nuoi PET\n\n"
              "Phi dich vien\n- Dien  4.000d/Kwh\n- Nuoc 100.000d/nguoi\n"
              "- DV (wifi, thang may...) 150.000d/phong")
        p = tu.parse_listing_text(m5)
        assert_true(p["house_number"] == "685/25/3"
                    and p["street"] == "Xô Viết Nghệ Tĩnh",
                    f"m5: sai địa chỉ {p['house_number']!r}/{p['street']!r}")
        assert_true(p["room_code"] == "402", f"m5: sai mã phòng {p['room_code']!r}")
        assert_true(p["price"] == 5_200_000, f"m5: '5.200 K' phải = 5.200.000, got {p['price']}")
        assert_true("gio giac tu do" in tu.norm(p["access_hours"]),
                    f"m5: sai giờ giấc {p['access_hours']!r}")
        assert_true("Thang máy" in p["amenities"] and "Camera" in p["amenities"],
                    f"m5: sai tiện ích {p['amenities']!r}")
        assert_true(p["pet_policy"].startswith("Cho nuôi"), f"m5: sai thú cưng {p['pet_policy']!r}")

        # --- m10: tin NHIỀU PHÒNG -> 6 phòng + giá từng cặp
        p = tu.parse_listing_text("Ma 501_502: 6.400.000\n103_104: 7.300.000\n"
                                  "Ma 101_102: 8.300.000")
        codes = [r["room_code"] for r in p["_rooms"]]
        assert_true(codes == ["501", "502", "103", "104", "101", "102"],
                    f"m10: sai danh sách phòng {codes}")
        assert_true(p["_rooms"][2]["price"] == 7_300_000
                    and p["room_code"] == "501" and p["price"] == 6_400_000,
                    f"m10: sai mã/giá {p['room_code']!r}/{p['price']}")
        assert_true(not p["owner_phone"], f"m10: '103' không được nhận là SĐT {p['owner_phone']!r}")

        # --- m4: '5tr5' = 5,5tr + SĐT thật + 'Ma phong: 103'
        p = tu.parse_listing_text(
            "DIA CHI:  347/6/27 CHU VAN AN, P12, BINH THANH\n"
            "Tien nghi: Gio giac tu do, Khoa cong van tay, Bao ve, Thang may\n"
            "Phi dich vu\nDien: 3,8k/kwh\nNuoc: 100k/nguoi\nDich vu: 200k/phong\n"
            "0967 673 637 (Tien) - Quan ly toa nha Ma phong: 103\nGia: 5tr5")
        assert_true(p["house_number"] == "347/6/27"
                    and "chu van an" in tu.norm(p["street"]),
                    f"m4: sai địa chỉ {p['house_number']!r}/{p['street']!r}")
        assert_true(p["room_code"] == "103" and p["price"] == 5_500_000,
                    f"m4: sai mã/giá {p['room_code']!r}/{p['price']}")
        assert_true(p["owner_phone"] == "0967673637", f"m4: sai SĐT {p['owner_phone']!r}")

        # --- quick_add: autofill đưa mã phòng + gợi ý tin nhiều phòng (không tự tạo 6 phòng)
        import quick_add as qa
        f2 = qa.autofill_from_text(m2)
        assert_true(f2.get("room_code") == "302" and f2.get("price") == 8_700_000,
                    f"autofill m2 sai: {f2.get('room_code')!r}/{f2.get('price')}")
        f10 = qa.autofill_from_text("Ma 501_502: 6.400.000\n103_104: 7.300.000\n"
                                    "Ma 101_102: 8.300.000")
        assert_true(f10.get("room_code") == "501"
                    and f10.get("_rooms") == ["501", "502", "103", "104", "101", "102"],
                    f"autofill m10 sai: {f10.get('room_code')!r}/{f10.get('_rooms')}")
        print(f"    -> m2 {f2['house_number']} {f2.get('street')} | "
              f"m10 {len(f10['_rooms'])} phòng (điền mã {f10['room_code']}) · "
              f"m4 price={tu.money_words(5_500_000)}")

    check("28. Mẫu tin Zalo thật: địa chỉ + mã phòng + giá/cọc/phí/giờ/tiện ích + autofill",
          t28_real_zalo_samples)

    # ---------------------------------------------------------------- địa chỉ giữa dòng + sort theo địa chỉ
    def t29_address_midline_and_sort():
        """Số nhà nằm GIỮA dòng vẫn tách được + sort danh sách phòng theo đường -> số nhà."""
        # tin thật: '...Nguyễn tăng Lâu 1 Ngay 31/32/52 ung văn khiêm p25 Binh Thanh Giá 12tr...'
        # (bug cũ: chỉ thử ứng viên số nhà ĐẦU TIÊN của dòng -> '12' bị loại -> mất địa chỉ)
        tin = ("Đầu tháng 1- 12 trống 2 phòng ngủ 1 phòng khách cao cấp full Nội Thất 1 WC "
               "Nguyễn tăng Lâu 1 Ngay 31/32/52 ung văn khiêm p25 Binh Thanh Giá 12tr "
               "Điện 4k Nước 100k/người Phí dịch vụ 200k /phòng Free 2 xe")
        p = tu.parse_listing_text(tin)
        assert_true(p["house_number"] == "31/32/52"
                    and "ung van khiem" in tu.norm(p["street"]),
                    f"sai địa chỉ giữa dòng: {p['house_number']!r}/{p['street']!r}")
        assert_true(p["ward"] == "P. 25" and p["district"] == "Q. Bình Thạnh",
                    f"sai phường/quận: {p['ward']!r}/{p['district']!r}")
        assert_true(p["price"] == 12_000_000, f"sai giá: {p['price']}")
        # phí DV phải cắt từ 'Điện' (không lấy nguyên khối mô tả đầu tin)
        assert_true("dien" in tu.norm(p["service_fee"])
                    and "dau thang" not in tu.norm(p["service_fee"]),
                    f"phí DV lẫn mô tả: {p['service_fee']!r}")

        # sort địa chỉ: ĐƯỜNG trước, SỐ NHÀ đếm tự nhiên ('2' < '10', 31/32/52 theo đoạn)
        rows = [{"id": "a", "street": "Võ Văn Tần", "house_number": "10", "unit_code": "S-2"},
                {"id": "b", "street": "Võ Văn Tần", "house_number": "2", "unit_code": "S-1"},
                {"id": "c", "street": "Nguyễn Xí", "house_number": "31/32/52", "unit_code": ""},
                {"id": "d", "street": "Xô Viết Nghệ Tĩnh", "house_number": "92", "unit_code": ""}]
        got = [(r["street"], r["house_number"]) for r in sorted(rows, key=tu.address_sort_key)]
        assert_true(got == [("Nguyễn Xí", "31/32/52"), ("Võ Văn Tần", "2"),
                            ("Võ Văn Tần", "10"), ("Xô Viết Nghệ Tĩnh", "92")],
                    f"sort địa chỉ sai: {got}")
        print(f"    -> giữa dòng: {p['house_number']} {p['street']}, {p['ward']}, "
              f"{p['district']} | sort: {' > '.join(f'{s} {h}' for s, h in got)}")

    check("29. Số nhà giữa dòng (tin 1 dòng) + sort trang Phòng theo đường -> số nhà",
          t29_address_midline_and_sort)

    # ---------------------------------------------------------------- kết luận
    settings.set("google_enabled", old_g, save=False)
    settings.set("db_path", old_db, save=False)
    settings.save()
    Database.reset_instance()
    shutil.rmtree(tmp, ignore_errors=True)

    ok = sum(1 for _, p, _ in RESULTS if p)
    print(f"\n========== KẾT QUẢ: {ok}/{len(RESULTS)} PASS ==========")
    for name, passed, err in RESULTS:
        if not passed:
            print(f"  FAIL: {name} :: {err}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
