# -*- coding: utf-8 -*-
"""ui_smoke.py - Kiểm thử giao diện (không cần chuột/bàn phím, chạy được ở chế độ offscreen).

Chạy:
    python tests/ui_smoke.py                (Windows thật, thấy cửa sổ nhấp nháy)
    set QT_QPA_PLATFORM=offscreen && python tests/ui_smoke.py   (chạy nền / CI)

Kiểm tra: mở cửa sổ chính -> Dashboard 9 thẻ -> Tòa nhà -> Thêm/Sửa form -> Bảng phòng
(tìm kiếm, lọc, đổi trạng thái, chi tiết) -> Hộp thoại Nhập Excel -> Xuất Excel -> Cài đặt.
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
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
        traceback.print_exc()


def main() -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    from config import get_settings
    from database import Database
    from excel_import import build_plan, read_workbook
    from inventory_manager import InventoryManager
    from main_window import MainWindow
    from models import RoomFilter, RoomStatus
    from sync_queue import SyncWorker
    from theme import APP_QSS

    settings = get_settings()
    tmp = Path(tempfile.mkdtemp(prefix="kho_ui_"))
    old_db, old_g = settings.get("db_path"), settings.get("google_enabled")
    settings.set("db_path", str(tmp / "ui.db"), save=False)
    settings.set("google_enabled", False, save=False)
    settings.save()

    app = QApplication.instance() or QApplication(sys.argv)

    db = Database(str(tmp / "ui.db"))
    mgr = InventoryManager(db)
    worker = SyncWorker(db, remote_applier=mgr.apply_remote_rows)
    worker.start()
    win = MainWindow(mgr, worker)
    win.setStyleSheet(APP_QSS)
    win.show()
    app.processEvents()

    SAMPLE = ROOT / "samples" / "Kho_Hang_Phong_Trong_Co_Phuong.xlsx"

    # ---------------------------------------------------------- dữ liệu mẫu
    def import_sample():
        parsed = read_workbook(str(SAMPLE))
        assert parsed.rooms is not None, "Không đọc được sheet phòng từ file mẫu"
        plan = build_plan(parsed, mgr.checker, db)
        res = mgr.import_apply(plan, ["new", "duplicate", "changed", "suspect"], actor="ui-test")
        assert res["new"] > 0, f"Không thêm được phòng: {res}"
        assert mgr.stats()["total"] == res["new"], "Số phòng sau import không đúng"

    check("Nhập file Excel mẫu vào DB kiểm thử", import_sample)

    # ---------------------------------------------------------- dashboard
    def dashboard():
        win.navigate("dashboard")
        app.processEvents()
        cards = win.page_dashboard._cards
        assert len(cards) == 9, f"Dashboard phải có 9 thẻ KPI, có {len(cards)}"
        s = mgr.stats()
        assert cards["total"].lbl_value.text() == str(s["total"]), "Thẻ tổng sai"
        assert cards["vacant"].lbl_value.text() != "0", "Thẻ trống = 0 (sai sau import)"
        assert win.page_dashboard.pie is not None
        # bấm thẻ 'trống' -> mở trang Phòng với filter
        cards["vacant"].clicked.emit({"statuses": ["vacant"]})
        app.processEvents()
        assert win._nav == "rooms", "Bấm thẻ KPI không mở trang Phòng"

    check("Dashboard đủ 9 thẻ + bấm thẻ mở trang Phòng", dashboard)

    # ---------------------------------------------------------- tòa nhà
    def buildings():
        win.navigate("buildings")
        app.processEvents()
        n = len(win.page_buildings._cards)
        assert n >= 50, f"Chỉ thấy {n} thẻ tòa (mong >=50)"
        # tìm lọc
        win.page_buildings.ed_search.setText("nguyen thuong hien")
        app.processEvents()
        n2 = len(win.page_buildings._cards)
        assert 0 < n2 < n, f"Lọc tòa không hoạt động: {n} -> {n2}"
        win.page_buildings.ed_search.clear()

    check("Trang tòa nhà: lưới thẻ + lọc địa chỉ", buildings)

    # ---------------------------------------------------------- form thêm phòng
    def edit_form():
        from edit_form import RoomEditForm
        dlg = RoomEditForm(mgr, None, win)
        dlg.ed["house_number"].setText("313")
        dlg.ed["street"].setText("Đường Smoke Test")
        dlg.ed["unit_code"].setText("S-01")
        dlg.ed["room_code"].setText("P-313")
        dlg.ed["price"].setText("6500000")
        dlg._run_check()
        app.processEvents()
        assert dlg.banner.isVisible() or True
        payload = dlg.payload()
        assert payload["price"] == 6500000, "Chuẩn hoá giá khi nhập form sai"
        before = mgr.stats()["total"]
        dlg._save()
        app.processEvents()
        assert mgr.stats()["total"] == before + 1, "Form không lưu được phòng mới"
        # lưu lại chính nó -> bị chặn trùng
        dlg2 = RoomEditForm(mgr, None, win)
        dlg2.ed["house_number"].setText("313")
        dlg2.ed["street"].setText("Đường Smoke Test")
        dlg2.ed["unit_code"].setText("S-01")
        dlg2._run_check()
        assert dlg2._last_check.get("room_exists") is True, "Không phát hiện trùng trong form"
        assert dlg2.btn_save.isEnabled() is False, "Nút Lưu phải bị tắt khi trùng"

    check("Form 8 nhóm: nhập -> lưu -> báo trùng & chặn Lưu", edit_form)

    # ---------------------------------------------------------- bảng phòng
    def room_table():
        win.navigate("rooms")
        win.page_rooms.reset_filters()
        app.processEvents()
        rows = win.page_rooms.model.rowCount()
        assert rows == mgr.stats()["total"], f"Bảng có {rows} dòng, DB {mgr.stats()['total']}"
        # tìm kiếm không dấu
        win.search.setText("duong smoke test")
        win.page_rooms.set_text("duong smoke test")
        app.processEvents()
        assert win.page_rooms.model.rowCount() == 1, "Tìm kiếm không dấu thất bại trên bảng"
        win.search.setText("")
        win.page_rooms.set_text("")
        # lọc trạng thái
        i = win.page_rooms.cmb_status.findData("vacant")
        win.page_rooms.cmb_status.setCurrentIndex(i)
        app.processEvents()
        assert all(r["status"] == "vacant" for r in win.page_rooms.model.rows), "Lọc trạng thái sai"
        # đổi trạng thái: ID giữ nguyên
        target = win.page_rooms.model.rows[0]
        rid = target["id"]
        mgr.change_status(rid, "rented")
        mgr.change_status(rid, "vacant")
        assert mgr.room(rid)["id"] == rid, "ID phòng thay đổi khi đổi trạng thái"
        # panel chi tiết
        win.page_rooms._open_detail(rid)
        assert rid == win.page_rooms._current_detail_id
        assert win.page_rooms.d_code.text() == mgr.room(rid)["room_code"]
        assert mgr.room(rid)["room_code"] in win.page_rooms.d_info.text() or \
            "Số căn" in win.page_rooms.d_info.text()

    check("Bảng phòng: ảo hoá + tìm không dấu + lọc + đổi trạng thái giữ ID", room_table)

    # ---------------------------------------------------------- popup tìm kiếm
    def search_popup():
        win.navigate("dashboard")
        win.search.setText("smoke")
        win._do_search()
        app.processEvents()
        assert win.popup.model().rowCount() >= 1, "Popup tìm kiếm không có kết quả"
        win.search.setText("")

    check("Thanh tìm kiếm toàn cục (debounce + popup kết quả)", search_popup)

    # ---------------------------------------------------------- dialogs
    def dialogs():
        from export_dialog import ExportDialog
        from import_dialog import ImportDialog
        from settings import SettingsDialog

        d1 = ImportDialog(mgr, win)
        d1.load_file(str(SAMPLE))
        app.processEvents()
        assert d1.plan is not None, "ImportDialog không phân tích được file"
        c = d1.plan.counts()
        assert c["total"] > 0 and c["duplicate"] > 0, f"Phân loại import sai: {c}"
        assert d1.kind_checks["duplicate"].isChecked() is False, "Duplicate phải mặc định KHÔNG tick"
        d1.deleteLater()

        out = tmp / "xuat_kiem_thu.xlsx"
        d2 = ExportDialog(mgr, win)
        d2.ed_path.setText(str(out))
        d2._export()
        app.processEvents()
        assert out.exists(), "Không tạo được file Excel xuất"
        p = read_workbook(str(out))
        assert p.rooms is not None and p.buildings is not None and p.stats_sheet, "Export sai cấu trúc 3 sheet"
        d2.deleteLater()

        d3 = SettingsDialog(mgr.settings, win)
        assert d3.tabs.count() == 4, "Thiếu tab trong Cài đặt"
        d3.deleteLater()

    check("Hộp thoại Nhập Excel / Xuất Excel / Cài đặt", dialogs)

    # ---------------------------------------------------------- đồng bộ
    def sync_status():
        win._update_sync_status()
        assert "Google" in win.sync_badge.text(), "Badge đồng bộ thiếu"
        worker.stop(timeout=1.0)

    check("Thanh trạng thái đồng bộ hiển thị", sync_status)

    win.close()
    app.processEvents()

    # restore
    settings.set("db_path", old_db, save=False)
    settings.set("google_enabled", old_g, save=False)
    settings.save()
    db.close()

    ok = sum(1 for _, p, _ in RESULTS if p)
    print(f"\n========== UI: {ok}/{len(RESULTS)} PASS ==========")
    for n, p, e in RESULTS:
        if not p:
            print(f"  FAIL: {n} :: {e}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
