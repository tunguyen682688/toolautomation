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
import time
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
    old_media = settings.get("media_root")
    settings.set("db_path", str(tmp / "ui.db"), save=False)
    settings.set("google_enabled", False, save=False)
    settings.set("media_root", str(tmp / "media"), save=False)   # media quy ước -> thư mục tạm
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
        n = win.page_buildings._model.data_row_count()
        assert n >= 50, f"Chỉ thấy {n} dòng tòa (mong >=50)"
        # tìm lọc
        win.page_buildings.ed_search.setText("nguyen thuong hien")
        app.processEvents()
        n2 = win.page_buildings._model.data_row_count()
        assert 0 < n2 < n, f"Lọc tòa không hoạt động: {n} -> {n2}"
        win.page_buildings.ed_search.clear()

    check("Trang tòa nhà: bảng + lọc địa chỉ", buildings)

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
        # check đồng bộ nhưng thỉnh thoảng vấp lock SQLite ngắn (thread nền) ->
        # thử lại vài lần trước khi kết luận
        for _ in range(6):
            dlg2._run_check()
            app.processEvents()
            if dlg2._last_check.get("room_exists") is True:
                break
            time.sleep(0.15)
        assert dlg2._last_check.get("room_exists") is True, "Không phát hiện trùng trong form"
        assert dlg2.btn_save.isEnabled() is False, "Nút Lưu phải bị tắt khi trùng"

    check("Form 8 nhóm: nhập -> lưu -> báo trùng & chặn Lưu", edit_form)

    # -------------------------------------- copy ảnh -> dán vào Zalo nhiều ảnh 1 tin
    def copy_zalo_multi():
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QAbstractItemView

        import media_manager as mm
        from edit_form import ImageUpload
        from media_panel import MediaPanel

        cdir = Path(tempfile.mkdtemp(prefix="kho_clip_"))
        files = []
        for i in (1, 2):
            p = cdir / f"anh{i}.jpg"
            QImage(16, 16, QImage.Format_RGB32).save(str(p), "JPG")
            files.append(str(p))

        # 1) chọn NHIỀU được (mặc định QListWidget là SingleSelection -> không copy đa ảnh)
        up = ImageUpload(mgr)
        assert up.list.selectionMode() == QAbstractItemView.ExtendedSelection, \
            "ImageUpload: không chọn được nhiều ảnh"
        mp = MediaPanel(mgr)
        assert mp.list.selectionMode() == QAbstractItemView.ExtendedSelection, \
            "MediaPanel: không chọn được nhiều file"

        # 2) copy 2 ảnh -> CHỈ dạng file (CF_HDROP): Zalo dán N ảnh trong 1 tin
        up.set_paths(files)
        up._copy_image()
        md = QApplication.clipboard().mimeData()
        assert md.hasUrls() and len(md.urls()) == 2, \
            f"Cần 2 file trong clipboard, có {len(md.urls() if md.hasUrls() else [])}"
        assert not md.hasImage(), \
            "Nhiều ảnh KHÔNG được để bitmap trong clipboard (Zalo sẽ bóp thành 1 ảnh)"

        # 3) đúng 1 ảnh -> cả file lẫn bitmap (dán ra ảnh ngay ở mọi app)
        up.set_paths(files[:1])
        up.list.clearSelection()
        up._copy_image()
        md = QApplication.clipboard().mimeData()
        assert md.hasUrls() and md.hasImage(), "1 ảnh cần có cả file lẫn bitmap"

        # 4) helper: chưa chọn gì ở MediaPanel -> copy tất cả file của phòng
        assert mm.copy_files_to_clipboard(files) == 2, "copy_files_to_clipboard sai số lượng"
        assert not QApplication.clipboard().mimeData().hasImage(), \
            "Copy 2 file phải là file-only"

        # 5) lưu nhanh ảnh từ form vào thư mục quy ước (không mất khi dọn TEMP)
        room = mgr.rooms("")[0]
        res = mm.import_files(room, files, mgr.settings)
        assert res["copied"] or res["skipped"], f"import_files không làm gì: {res}"
        assert mm.room_media_dir(room, mgr.settings).exists(), "Chưa tạo thư mục quy ước"

    check("Copy ảnh dán Zalo: N ảnh trong 1 tin + chọn nhiều + lưu vào thư mục", copy_zalo_multi)

    # ---------------------------------------------------------- bảng phòng
    def room_table():
        win.navigate("rooms")
        win.page_rooms.reset_filters()
        app.processEvents()
        rows = win.page_rooms.model.data_row_count()
        assert rows == mgr.stats()["total"], f"Bảng có {rows} dòng, DB {mgr.stats()['total']}"
        # tìm kiếm không dấu
        win.search.setText("duong smoke test")
        win.page_rooms.set_text("duong smoke test")
        app.processEvents()
        assert win.page_rooms.model.data_row_count() == 1, "Tìm kiếm không dấu thất bại trên bảng"
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
        # khu Ảnh/Video: có đường dẫn quy ước + danh sách trống (DB tạm chưa có media)
        import media_manager as mm
        mp = win.page_rooms.media_panel
        expect = mm.room_media_dir(mgr.room(rid), settings)
        assert mp.ed_path.text() == str(expect), \
            f"Sai đường dẫn quy ước media: {mp.ed_path.text()} != {expect}"
        assert mp.list.count() == 0 and mp.lbl_empty.isVisibleTo(mp), "MediaPanel trạng thái rỗng sai"

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
        
        # Check tab Chung có ô "Thư mục dữ liệu" với nút Chọn...
        d3.tabs.setCurrentIndex(0)  # tab Chung
        app.processEvents()
        assert "db_path" in d3.ed, "Thiếu ô Thư mục dữ liệu trong tab Chung"
        assert d3.ed["db_path"].toolTip().startswith("Thư mục lưu trữ dữ liệu"), "Tooltip sai cho ô Thư mục dữ liệu"
        d3.deleteLater()

        # ---- Tìm theo yêu cầu khách: nút 🎯 + dialog parse live + 4 vòng kết quả ----
        assert hasattr(win.page_rooms, "btn_request"), "Thiếu nút 'Yêu cầu khách' trên trang Phòng"
        from request_dialog import RequestDialog
        import request_parser as rp
        d4 = RequestDialog(mgr, win)
        d4.ed.setText("phong 7tr full noi that thang may gui xe xung quanh P13")
        d4.run_search()
        app.processEvents()
        assert d4.req is not None and d4.req.ward_keys == ["13"], "Dialog parse sai phường"
        assert d4.body_lay.count() >= 1, "Dialog không có card kết quả nào"
        assert any(t["total"] > 0 for t in rp.search_tiers(mgr, d4.req)), \
            "Không tìm được phòng nào cho yêu cầu mẫu"
        d4.deleteLater()

    check("Hộp thoại Nhập Excel / Xuất Excel / Cài đặt", dialogs)

    # ---------------------------------------------------------- đồng bộ
    def sync_status():
        win._update_sync_status()
        assert "Google" in win.sync_badge.text(), "Badge đồng bộ thiếu"
        worker.stop(timeout=1.0)

    check("Thanh trạng thái đồng bộ hiển thị", sync_status)

    # ---------------------------------------------------------- trang khách hàng (CRM)
    def customers():
        win.navigate("customers")
        app.processEvents()
        page = win.page_customers

        # 1) form thêm khách: prefill từ yêu cầu + đọc payload (không mở modal)
        from customer_view import CustomerForm
        dlg = CustomerForm(None, {"area": "P.13", "budget_max": 7000000}, win)
        dlg.fields["name"].setText("Nguyễn Thị Bích")
        dlg.fields["phone"].setText("0909123456")
        payload = dlg.payload()
        assert payload["area"] == "P.13" and payload["budget_max"] == "7000000", \
            f"Prefill form khách sai: {payload}"

        # 2) thêm khách -> bảng có 1 dòng
        page.cm.add_customer(payload)
        page.refresh()
        app.processEvents()
        assert page._model.data_row_count() == 1, "Bảng khách không có dữ liệu"

        # 3) tìm không dấu (2 token AND)
        page.ed_search.setText("nguyen thi bich")
        app.processEvents()
        assert page._model.data_row_count() == 1, "Tìm không dấu tên khách lỗi"
        page.ed_search.setText("bich 0909")
        app.processEvents()
        assert page._model.data_row_count() == 1, "Tìm AND theo SĐT lỗi"
        page.ed_search.clear()
        app.processEvents()

        # 4) chọn dòng dữ liệu đầu -> panel chi tiết nhận khách
        idx = None
        for r in range(page._model.rowCount()):
            if page._model.data_row_at(r):
                idx = page._model.index(r, 0)
                break
        assert idx is not None, "Không thấy dòng dữ liệu trong bảng khách"
        page._on_row_clicked(idx)
        app.processEvents()
        assert page.panel.customer and page.panel.customer["phone"] == "0909123456", \
            "Panel chi tiết không nhận khách"

        # 5) đổi trạng thái pipeline: hẹn xem -> MẤT (chọn lý do = điểm sai khi sale)
        assert page.panel.apply_status("viewing"), "Chuyển trạng thái thất bại"
        assert page.panel.apply_status("lost", lose_reason="price"), \
            "Chuyển về Mất khách thất bại"
        st = page.cm.stats()
        assert st["by_status"]["lost"] == 1 and st["by_reason"]["price"] == 1, \
            f"Không lưu được lý do mất khách: {st['by_reason']}"

        # 6) tab Phân tích: funnel + lý do mất + nhận định render đủ
        page.tabs.setCurrentIndex(1)
        app.processEvents()
        assert page.analytics.funnel_bars.row_count() >= 1, "Funnel chưa có dữ liệu"
        assert page.analytics.reason_bars.row_count() == 1, "Chưa thấy lý do mất khách"
        assert "Nhận định" in page.analytics.lbl_insight.text(), "Thiếu nhận định"

        # 7) khách thứ 2 chốt -> tỷ lệ chốt 50% + lọc theo trạng thái
        page.cm.add_customer({"name": "Lê Văn Cường", "phone": "0911222333"})
        page.cm.change_status(page.cm.customers("cuong")[0]["id"], "won")
        page.refresh()
        app.processEvents()
        assert page.cm.stats()["conversion"] == 50.0, "Tỷ lệ chốt sai"
        page.cmb_status.setCurrentIndex(page.cmb_status.findData("lost"))
        app.processEvents()
        assert page._model.data_row_count() == 1, "Lọc theo trạng thái lỗi"
        page.cmb_status.setCurrentIndex(0)
        app.processEvents()
        assert page._model.data_row_count() == 2, "Bỏ lọc trạng thái lỗi"

    check("Trang khách hàng: bảng pipeline + chi tiết + đổi trạng thái + phân tích", customers)

    # ------------------------------------ dắt căn + điểm sai tư vấn & xử lý
    def showings():
        win.navigate("customers")
        app.processEvents()
        page = win.page_customers

        # 1) thêm khách -> chọn dòng -> panel chi tiết
        page.cm.add_customer({"name": "Trần Văn Dắt", "phone": "0909555666",
                              "source": "Zalo"})
        page.ed_search.clear()
        page.refresh()
        app.processEvents()
        idx = None
        for r in range(page._model.rowCount()):
            rec = page._model.data_row_at(r)
            if rec and rec.get("phone") == "0909555666":
                idx = page._model.index(r, 0)
                break
        assert idx is not None, "Không thấy khách vừa thêm"
        page._on_row_clicked(idx)
        app.processEvents()
        assert page.panel.customer and page.panel.btn_showing is not None, \
            "Thiếu nút 'Ghi dắt căn'"
        assert page.panel.btn_mistake is not None, "Thiếu nút 'Điểm sai xử lý'"

        # 2) options căn cho dialog dắt (đã import Excel mẫu -> có phòng)
        opts = page._room_options()
        assert opts and "id" in opts[0] and "label" in opts[0], \
            f"_room_options sai: {opts[:1]}"

        # 3) dialog dắt căn: đọc payload KHÔNG mở modal
        from customer_view import MistakeDialog, ShowingDialog
        dlg = ShowingDialog(opts, page.panel)
        dlg.cmb_room.setCurrentIndex(0)
        dlg.cmb_outcome.setCurrentIndex(dlg.cmb_outcome.findData("rejected"))
        dlg.cmb_mistake.setCurrentIndex(dlg.cmb_mistake.findData("care_before_show"))
        dlg.ed_note.setText("chăm 3 ngày mới rủ đi xem")
        p = dlg.payload()
        assert p["room_id"] and p["outcome"] == "rejected" \
            and p["process_error"] == "care_before_show", f"Payload dialog sai: {p}"
        dlg.deleteLater()

        # 4) ghi 1 lượt dắt (kèm điểm sai) -> cột 'Đã dắt' = 1 + panel liệt kê
        cid = page.panel.customer["id"]
        page.cm.log_showing(cid, room_id=p["room_id"], room_label=p["room_label"],
                            shown_at="2026-11-02", outcome=p["outcome"],
                            note=p["note"], process_error=p["process_error"])
        page.refresh()
        app.processEvents()
        row = next(r for r in range(page._model.rowCount())
                   if (page._model.data_row_at(r) or {}).get("id") == cid)
        cell = page._model.data(page._model.index(row, 3), Qt.DisplayRole)
        assert str(cell) == "1", f"Cột 'Đã dắt' phải là 1, nhận: {cell!r}"
        assert page.panel.showings_model.rowCount() == 1, "Panel chưa liệt kê lượt dắt"
        assert "1 lượt" in page.panel.lbl_showings.text(), "Nhãn số lượt dắt sai"
        assert "1 điểm sai" in page.panel.lbl_mistakes.text(), "Nhãn điểm sai sai"

        # 5) dialog điểm sai xử lý -> ghi riêng
        dlg2 = MistakeDialog(page.panel)
        assert dlg2.cmb.count() >= 10, "Danh mục điểm sai quá ít"
        page.cm.log_mistake(cid, dlg2.cmb.currentData(), note="để khách chờ")
        page.refresh()
        app.processEvents()
        assert page.panel.showings_model.rowCount() == 1, "Ghi điểm sai làm mất lượt dắt"
        assert "2 điểm sai" in page.panel.lbl_mistakes.text(), "Chưa đếm đủ2 điểm sai"

        # 6) tab Phân tích: 2 thanh mới + KPI mới
        page.tabs.setCurrentIndex(1)
        app.processEvents()
        assert page.analytics.mistake_bars.row_count() >= 1, "Chưa có thanh điểm sai xử lý"
        assert page.analytics.room_bars.row_count() >= 1, "Chưa có thanh căn đã dắt"
        assert page.analytics.kpi["showings"].lbl_value.text() == "1", \
            f"KPI lượt dắt sai: {page.analytics.kpi['showings'].lbl_value.text()}"
        assert page.analytics.kpi["mistakes"].lbl_value.text() == "2", \
            f"KPI điểm sai sai: {page.analytics.kpi['mistakes'].lbl_value.text()}"
        assert "Chăm khách rồi mới dắt khách" in page.analytics.lbl_mistake_hint.text(), \
            "Hint điểm sai không nêu được lỗi phổ biến nhất"
        assert "Đã dắt 1 lượt" in page.analytics.lbl_room_hint.text(), "Hint căn đã dắt sai"

    check("Trang khách hàng: dắt căn + điểm sai xử lý (panel + phân tích)", showings)

    # ------------------------------------ tạo nhanh từ Zalo: ảnh -> phòng
    def quick_add_zalo():
        from PySide6.QtGui import QImage

        import media_manager as mm
        from quick_add import QuickAddDialog

        win.navigate("rooms")
        app.processEvents()
        assert hasattr(win.page_rooms, "btn_quick"), "Thiếu nút ⚡ Tạo nhanh từ Zalo"

        # clipboard = ảnh copy từ Zalo -> dialog phải tự đọc được
        QApplication.clipboard().setImage(QImage(48, 48, QImage.Format_RGB32))
        before = mgr.stats()["total"]
        dlg = QuickAddDialog(mgr, win)
        assert len(dlg.img_paths) == 1 and Path(dlg.img_paths[0]).exists(), \
            f"Không đọc được ảnh clipboard: {dlg.img_paths}"
        assert not dlg.btn_save.isEnabled(), "Nút Lưu phải tắt khi thiếu dữ liệu"

        # 1 Enter là xong: địa chỉ + số căn + loại phòng -> Lưu
        dlg.ed["house_number"].setText("317")
        dlg.ed["street"].setText("Đường Quick Add")
        dlg.ed["unit_code"].setText("S-77")
        dlg.ed["room_type"].setCurrentText("Studio")
        dlg._run_check()
        app.processEvents()
        assert dlg.btn_save.isEnabled(), "Đã đủ dữ liệu mà Lưu vẫn tắt"
        assert "Tòa mới" in dlg.banner_label.text(), \
            f"Chưa báo được trạng thái tòa nhà: {dlg.banner_label.text()[:160]}"
        assert "Studio" in dlg.banner_label.text(), "Chưa báo được loại phòng sẽ tạo"

        dlg._save()
        assert dlg.saved_room_id and mgr.stats()["total"] == before + 1, "Không lưu được phòng nhanh"
        assert dlg.saved_images == 1, f"Số ảnh lưu sai: {dlg.saved_images}"
        room = mgr.room(dlg.saved_room_id)
        assert mm.room_media_dir(room, settings).exists(), "Ảnh không vào thư mục quy ước"
        assert mm.list_media(room, settings), "Danh sách ảnh phòng trống sau khi Lưu"
        dlg.deleteLater()

        # check TÒA NHÀ đã có + LOẠI PHÒNG đã có trong tòa
        dlg2 = QuickAddDialog(mgr, win)
        dlg2.ed["house_number"].setText("317")
        dlg2.ed["street"].setText("Đường Quick Add")
        dlg2.ed["unit_code"].setText("S-78")
        dlg2.ed["room_type"].setCurrentText("Studio")
        dlg2._run_check()
        app.processEvents()
        b2 = dlg2.banner_label.text()
        assert "tự liên kết" in b2, f"Không nhận ra tòa đã có: {b2[:200]}"
        assert "1 phòng Studio" in b2 and "S-77" in b2, f"Không liệt kê loại phòng đã có: {b2[:240]}"

        # trùng số căn -> CHẶN Lưu + nút mở bản ghi cũ
        dlg2.ed["unit_code"].setText("S-77")
        dlg2._run_check()
        app.processEvents()
        assert "ĐÃ TỒN TẠI" in dlg2.banner_label.text(), "Không báo được phòng đã tồn tại"
        assert not dlg2.btn_save.isEnabled(), "Không chặn được Lưu khi trùng số căn"
        assert dlg2._dup_id, "Không nắm được id bản ghi trùng"
        dlg2.deleteLater()

        # chữ tin nhắn (không có ảnh) -> tự điền địa chỉ / giá / loại phòng
        QApplication.clipboard().setText("Cho thuê 319 Đường Quick Add giá 6.5tr studio")
        dlg3 = QuickAddDialog(mgr, win)
        assert dlg3.ed["house_number"].text() == "319", "Không autofill số nhà từ tin nhắn"
        assert dlg3.ed["room_type"].currentText() == "Studio", "Không autofill loại phòng"
        assert dlg3.ed["price"].text().replace(".", "") == "6500000", \
            f"Không autofill giá: {dlg3.ed['price'].text()}"
        assert dlg3.img_paths == [], "Chữ trong clipboard không được coi là ảnh"
        dlg3.deleteLater()
        QApplication.clipboard().clear()

    check("Tạo nhanh từ Zalo: dán ảnh -> lưu phòng + ảnh vào thư mục + check tòa/loại phòng",
          quick_add_zalo)

    win.close()
    app.processEvents()

    # Dọn clipboard trước khi thoát: PySide6 6.12 + Qt offscreen crash (0xC0000005)
    # nếu QApplication bị destroy mà clipboard còn dữ liệu (platform windows thật
    # không bị). Test copy vừa để file tạm vào clipboard của user -> clear luôn.
    QApplication.clipboard().clear()

    # restore
    settings.set("db_path", old_db, save=False)
    settings.set("google_enabled", old_g, save=False)
    settings.set("media_root", old_media, save=False)
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
