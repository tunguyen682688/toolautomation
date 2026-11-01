# -*- coding: utf-8 -*-
"""main.py - Điểm khởi động ứng dụng quản lý kho phòng căn hộ.

Chạy:  python main.py

Kiến trúc:
- SQLite (offline-first) + chỉ mục tìm kiếm trong bộ nhớ  -> mở là dùng ngay, tìm < 5ms
- InventoryManager là lớp nghiệp vụ duy nhất mà giao diện gọi
- SyncWorker (thread nền) đồng bộ Google Sheets khi được cấu hình; giao diện chỉ poll deque
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

# đảm bảo import được module cùng thư mục khi chạy `python main.py` từ mọi nơi
sys.path.insert(0, str(Path(__file__).resolve().parent))


def resource_path(rel: str) -> Path:
    """Đường dẫn file dữ liệu đi kèm (hoạt động cả khi đã đóng gói bằng PyInstaller)."""
    base = getattr(sys, "_MEIPASS", None)          # bản build (onefile/onedir)
    if base:
        return Path(base) / rel
    return Path(__file__).resolve().parent / rel


def app_dir() -> Path:
    """Thư mục chứa file thực thi (bản build) hoặc thư mục nguồn (chạy `python main.py`)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _finish_selftest(app, win, mgr, db, log) -> None:
    """Tự kiểm tra bản build (chạy với `--selftest`): nhập mẫu -> mở trang -> tìm -> xuất Excel."""
    errs: list = []
    lines: list = []

    def check(name: str, ok: bool, extra: str = ""):
        tag = "PASS" if ok else "FAIL"
        lines.append(f"  [{tag}] {name} {'' if ok else extra}")
        print(lines[-1])
        if not ok:
            errs.append(f"{name} {extra}")

    print("=== SELFTEST BAN BUILD ===")
    try:
        app.processEvents()

        # 1) nhập file Excel mẫu (đi kèm bản build)
        sample = resource_path("samples") / "Kho_Hang_Phong_Trong_Co_Phuong.xlsx"
        check("Tìm thấy file dữ liệu mẫu đi kèm", sample.exists(), str(sample))
        if sample.exists():
            from excel_import import build_plan, read_workbook
            parsed = read_workbook(str(sample))
            plan = build_plan(parsed, mgr.checker, db)
            res = mgr.import_apply(plan, ["new", "duplicate", "changed", "suspect"], actor="selftest")
            check("Nhập Excel thành công", res.get("new", 0) > 0, str(res))
            check("Số phòng sau import đúng",
                  mgr.stats()["total"] == res.get("new"), str(mgr.stats()["total"]))

        # 2) Dashboard 9 thẻ
        win.navigate("dashboard")
        app.processEvents()
        check("Dashboard có 9 thẻ KPI", len(win.page_dashboard._cards) == 9)

        # 3) trang tòa nhà
        win.navigate("buildings")
        app.processEvents()
        n_bld = win.page_buildings._model.data_row_count()
        check("Trang tòa nhà hiển thị bảng", n_bld >= 10, str(n_bld))

        # 4) bảng phòng + tìm kiếm không dấu
        win.navigate("rooms")
        app.processEvents()
        rows = win.page_rooms.model.data_row_count()
        check("Bảng phòng có dữ liệu", rows > 0, str(rows))
        n = len(mgr.rooms("nguyen thuong hien"))
        check("Tìm kiếm không dấu trả kết quả", n > 0, str(n))
        n2 = len(mgr.rooms("P-86"))
        check("Tìm theo mã phòng", n2 >= 1, str(n2))

        # 5) xuất Excel
        import tempfile
        out = Path(tempfile.mkdtemp(prefix="kho_xuat_")) / "selftest.xlsx"
        from excel_export import export_workbook
        export_workbook(str(out), mgr.rooms(""), mgr.buildings(), mgr.stats())
        check("Xuất Excel thành công", out.exists() and out.stat().st_size > 5000,
              f"{out.stat().st_size if out.exists() else 0} bytes")

        # 6) tìm được file cấu hình / ghi log
        from config import DATA_DIR, CONFIG_DIR, APP_ENV, SETTINGS_FILE, DB_FILE
        check("Ghi được dữ liệu cạnh file exe",
              DATA_DIR.exists() and CONFIG_DIR.exists(), str(DATA_DIR))
        # 7) môi trường được tách riêng
        check(f"Data nằm trong thư mục env '{APP_ENV}'",
              DATA_DIR.name == APP_ENV and str(DB_FILE).startswith(str(DATA_DIR)),
              str(DATA_DIR))
        check("Settings riêng theo env",
              SETTINGS_FILE.name == f"settings_{APP_ENV}.json"
              and SETTINGS_FILE.parent.exists(), str(SETTINGS_FILE))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        errs.append(f"EXCEPTION: {e}")

    print(f"========== SELFTEST: {'OK' if not errs else str(len(errs)) + ' LOI'} ==========")
    for e in errs:
        print("  LOI:", e)
        lines.append(f"  LOI: {e}")
    lines.insert(0, f"========== SELFTEST: {'OK' if not errs else str(len(errs)) + ' LOI'} ==========")

    # bản build là GUI (không có console) -> ghi kết quả ra file để đọc được
    try:
        from config import DATA_DIR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "selftest_result.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    log.info("SELFTEST kết thúc: %s", "OK" if not errs else errs)
    app.exit(0 if not errs else 1)


def main() -> int:
    import os

    SELFTEST = "--selftest" in sys.argv
    if SELFTEST:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # chạy nền, không cần màn hình
        # console Windows hay là cp1252 -> bắt buộc UTF-8 để in được tiếng Việt (không crash)
        for _s in (sys.stdout, sys.stderr):
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    from config import get_settings
    from logger import setup_logging, get_logger

    setup_logging()
    log = get_logger("main")

    from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen
    from PySide6.QtGui import QPixmap, QColor, QFont
    from PySide6.QtCore import Qt, QSize

    # ---- HIGH-DPI / RESPONSIVE: phải đặt TRƯỚC khi tạo QApplication ----
    # Màn hình Windows scale 125%/150%/200% -> giữ tỉ lệ gốc (không làm mờ, không cắt UI)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("Kho Phòng Căn Hộ")
    app.setOrganizationName("Tú Nguyễn Land")

    from config import APP_ENV, env_badge, DATA_DIR
    log.info("Môi trường: %s (data: %s)", APP_ENV, DATA_DIR)

    # splash nhanh (ứng dụng lớn -> có cảm giác mở tức thì) - màu theo theme
    import theme as theme_mod
    _settings_pre = get_settings()
    theme_mod.set_theme(str(_settings_pre.get("ui_theme", "dark")))
    pix = QPixmap(QSize(560, 300))
    pix.fill(QColor(theme_mod.c("accent")))
    splash = QSplashScreen(pix)
    splash.showMessage("Đang tải dữ liệu kho phòng...",
                       int(Qt.AlignBottom | Qt.AlignHCenter), QColor("#FFFFFF"))
    splash.show()
    app.processEvents()

    try:
        from database import Database
        from inventory_manager import InventoryManager
        from sync_queue import SyncWorker
        from main_window import MainWindow
        APP_QSS = theme_mod.APP_QSS
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        try:
            QMessageBox.critical(None, "Lỗi khởi động",
                                 "Không tải được module:\n\n" + traceback.format_exc(limit=3))
        except Exception:  # noqa: BLE001
            pass
        return 1

    settings = _settings_pre
    if SELFTEST:
        # dùng DB tạm -> không đụng dữ liệu thật của người dùng
        import tempfile
        _tmp = Path(tempfile.mkdtemp(prefix="kho_selftest_"))
        settings.set("db_path", str(_tmp / "selftest.db"), save=False)
        settings.set("google_enabled", False, save=False)
        log.info("SELFTEST: dùng DB tạm %s", _tmp)

    try:
        db = Database.instance()
        mgr = InventoryManager(db)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        QMessageBox.critical(None, "Lỗi cơ sở dữ liệu",
                             "Không mở được file dữ liệu SQLite:\n\n" + traceback.format_exc(limit=3))
        return 1

    # worker đồng bộ nền (an toàn: chỉ ghi vào deque, UI poll bằng QTimer)
    worker = SyncWorker(db, remote_applier=mgr.apply_remote_rows)
    worker.start()

    win = MainWindow(mgr, worker)
    win.setStyleSheet(APP_QSS)
    win.showMaximized()                            # mở full màn hình từ đầu
    splash.finish(win)

    stats = mgr.stats()
    log.info("Khởi động: %s phòng, %s tòa, Google=%s",
             stats.get("total"), stats.get("buildings"),
             settings.get("google_enabled"))
    win.lbl_status.setText(
        f"Sẵn sàng · {stats.get('total', 0)} phòng · {stats.get('buildings', 0)} tòa · "
        f"nhấn Ctrl+F để tìm nhanh")

    # lần chạy đầu (DB trống) -> đề nghị nhập luôn file Excel dữ liệu mẫu/thật
    if not stats.get("total") and not SELFTEST:
        sample = resource_path("samples") / "Kho_Hang_Phong_Trong_Co_Phuong.xlsx"
        if sample.exists():
            ans = QMessageBox.question(
                win, "Chưa có dữ liệu",
                f"Cơ sở dữ liệu đang trống.\n\n"
                f"Bạn có muốn nhập ngay file dữ liệu mẫu?\n{sample.name}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ans == QMessageBox.Yes:
                try:
                    from excel_import import build_plan, read_workbook
                    parsed = read_workbook(str(sample))
                    if parsed.rooms:
                        plan = build_plan(parsed, mgr.checker, db)
                        res = mgr.import_apply(plan, ["new", "duplicate", "changed", "suspect"])
                        win.refresh_all()
                        QMessageBox.information(
                            win, "Nhập thành công",
                            f"Đã thêm {res.get('new', 0)} phòng từ file mẫu.\n"
                            f"(Bỏ qua {res.get('duplicate', 0)} dòng trùng.)")
                except Exception as e:  # noqa: BLE001
                    log.exception("Nhập file mẫu lỗi")
                    QMessageBox.warning(win, "Không nhập được file mẫu", str(e))

    if SELFTEST:
        # ---- tự kiểm tra bản build: nhập dữ liệu mẫu, mở các trang, tìm kiếm ----
        from PySide6.QtCore import QTimer
        QTimer.singleShot(600, lambda: _finish_selftest(app, win, mgr, db, log))

    code = app.exec()
    # dọn dẹp
    try:
        worker.stop(timeout=2.0)
    except Exception:  # noqa: BLE001
        pass
    try:
        Database.reset_instance()
    except Exception:  # noqa: BLE001
        pass
    return int(code or 0)


if __name__ == "__main__":
    sys.exit(main())
