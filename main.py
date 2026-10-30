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


def main() -> int:
    from config import get_settings
    from logger import setup_logging, get_logger

    setup_logging()
    log = get_logger("main")

    from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen
    from PySide6.QtGui import QPixmap, QColor, QFont
    from PySide6.QtCore import Qt, QSize

    app = QApplication(sys.argv)
    app.setApplicationName("Kho Phòng Căn Hộ")
    app.setOrganizationName("Tú Nguyễn Land")

    # splash nhanh (ứng dụng lớn -> có cảm giác mở tức thì)
    pix = QPixmap(QSize(560, 300))
    pix.fill(QColor("#2563EB"))
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
        from theme import APP_QSS
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        try:
            QMessageBox.critical(None, "Lỗi khởi động",
                                 "Không tải được module:\n\n" + traceback.format_exc(limit=3))
        except Exception:  # noqa: BLE001
            pass
        return 1

    settings = get_settings()
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
    win.show()
    splash.finish(win)

    stats = mgr.stats()
    log.info("Khởi động: %s phòng, %s tòa, Google=%s",
             stats.get("total"), stats.get("buildings"),
             settings.get("google_enabled"))
    win.lbl_status.setText(
        f"Sẵn sàng · {stats.get('total', 0)} phòng · {stats.get('buildings', 0)} tòa · "
        f"nhấn Ctrl+F để tìm nhanh")

    # lần chạy đầu (DB trống) -> đề nghị nhập luôn file Excel dữ liệu mẫu/thật
    if not stats.get("total"):
        sample = Path(__file__).resolve().parent / "samples" / "Kho_Hang_Phong_Trong_Co_Phuong.xlsx"
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
