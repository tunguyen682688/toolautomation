# -*- coding: utf-8 -*-
"""settings.py - Hộp thoại Cài đặt: hồ sơ người dùng, Google Sheets/Drive, Excel, đồng bộ.

Không chứa secret trong mã nguồn: chỉ trỏ ĐƯỜNG DẪN file service account JSON.
Chưa có credentials -> ứng dụng vẫn chạy offline-first.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)


class SettingsDialog(QDialog):
    saved = Signal(dict)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Cài đặt")
        self.setMinimumSize(700, 620)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(14, 12, 14, 10)
        self.layout().setSpacing(9)

        self.tabs = QTabWidget()
        self.layout().addWidget(self.tabs, 1)
        self.ed: Dict[str, QWidget] = {}

        self.tabs.addTab(self._tab_general(), "👤 Chung")
        self.tabs.addTab(self._tab_google(), "☁️ Google Sheets")
        self.tabs.addTab(self._tab_sync(), "🔄 Đồng bộ")
        self.tabs.addTab(self._tab_about(), "ℹ️ Hướng dẫn Google API")

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        btn_restore = bb.addButton("Khôi phục mặc định", QDialogButtonBox.ResetRole)
        btn_restore.clicked.connect(self._restore_defaults)
        self.layout().addWidget(bb)

    # ------------------------------------------------------------------ tab chung
    def _tab_general(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.ed["user_name"] = QLineEdit(str(self.settings.get("user_name")))
        self.ed["user_name"].setPlaceholderText("Tên hiển thị khi ghi lịch sử thay đổi")
        form.addRow("Tên người dùng:", self.ed["user_name"])

        self.ed["page_size"] = QSpinBox()
        self.ed["page_size"].setRange(100, 20000)
        self.ed["page_size"].setValue(int(self.settings.get("page_size") or 500))
        form.addRow("Số dòng tối đa mỗi trang:", self.ed["page_size"])

        self.ed["confirm_delete"] = QCheckBox("Hỏi xác nhận trước khi xóa phòng")
        self.ed["confirm_delete"].setChecked(bool(self.settings.get("confirm_delete", True)))
        form.addRow("", self.ed["confirm_delete"])

        self.ed["auto_save"] = QCheckBox("Tự lưu mọi thay đổi ngay lập tức (khuyến nghị)")
        self.ed["auto_save"].setChecked(bool(self.settings.get("auto_save", True)))
        form.addRow("", self.ed["auto_save"])

        db_path = QLineEdit(str(self.settings.get("db_path")))
        db_path.setReadOnly(True)
        db_path.setToolTip("File dữ liệu cục bộ (SQLite) - không chỉnh tay.")
        form.addRow("File dữ liệu:", db_path)

        from config import APP_ENV, env_badge, DATA_DIR, SETTINGS_FILE
        env_row = QLineEdit(f"{env_badge()}  ·  data: {DATA_DIR}  ·  config: {SETTINGS_FILE}")
        env_row.setReadOnly(True)
        env_row.setToolTip(
            "Môi trường đang chạy. Đổi bằng cờ --env dev|staging|prod.\n"
            "Mỗi môi trường có data/ và settings RIÊNG - không ảnh hưởng lẫn nhau.")
        form.addRow("Môi trường:", env_row)
        lay.addLayout(form)

        note = QLabel(
            "<b>Lưu dữ liệu:</b> mọi thay đổi được ghi ngay vào SQLite cục bộ "
            "(có backup trong <i>data/</i>) và đưa vào hàng đợi đồng bộ nếu bật Google. "
            "Mất điện / mất mạng không mất dữ liệu.")
        note.setWordWrap(True)
        note.setTextFormat(Qt.RichText)
        lay.addWidget(note)
        lay.addStretch(1)
        return w

    # ------------------------------------------------------------------ tab Google
    def _tab_google(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.ed["google_enabled"] = QCheckBox("Bật đồng bộ Google Sheets (cần credentials)")
        self.ed["google_enabled"].setChecked(bool(self.settings.get("google_enabled")))
        form.addRow("", self.ed["google_enabled"])

        # credentials file
        row = QHBoxLayout()
        self.ed["credentials_file"] = QLineEdit(str(self.settings.get("credentials_file")))
        self.ed["credentials_file"].setPlaceholderText(r"Ví dụ: C:\...\config\service_account.json")
        btn = QPushButton("Chọn file...")
        btn.clicked.connect(self._pick_credentials)
        row.addWidget(self.ed["credentials_file"], 1)
        row.addWidget(btn)
        form.addRow("Service account JSON:", row)

        self.lbl_creds_status = QLabel(self._creds_status())
        self.lbl_creds_status.setTextFormat(Qt.RichText)
        form.addRow("", self.lbl_creds_status)

        self.ed["spreadsheet_id"] = QLineEdit(str(self.settings.get("spreadsheet_id")))
        self.ed["spreadsheet_id"].setPlaceholderText(
            "Lấy từ URL: docs.google.com/spreadsheets/d/<ĐÂY LÀ ID>/edit")
        form.addRow("Spreadsheet ID:", self.ed["spreadsheet_id"])

        self.ed["rooms_sheet"] = QLineEdit(str(self.settings.get("rooms_sheet")))
        form.addRow("Sheet danh sách phòng:", self.ed["rooms_sheet"])
        self.ed["buildings_sheet"] = QLineEdit(str(self.settings.get("buildings_sheet")))
        form.addRow("Sheet danh mục:", self.ed["buildings_sheet"])
        self.ed["stats_sheet"] = QLineEdit(str(self.settings.get("stats_sheet")))
        form.addRow("Sheet thống kê:", self.ed["stats_sheet"])
        self.ed["map_sheet"] = QLineEdit(str(self.settings.get("map_sheet")))
        self.ed["map_sheet"].setToolTip("Sheet phụ do phần mềm quản lý: ánh xạ ID nội bộ <-> dòng Sheets")
        form.addRow("Sheet ID map:", self.ed["map_sheet"])
        lay.addLayout(form)

        tips = QLabel(
            "<b>Cần làm 4 bước:</b><br>"
            "1. Vào <i>console.cloud.google.com</i> → tạo project → bật <b>Google Sheets API</b> "
            "và <b>Google Drive API</b>.<br>"
            "2. <i>Credentials → Create credentials → Service account</i> → tải key JSON.<br>"
            "3. Đặt đường dẫn file JSON vào ô trên.<br>"
            "4. Mở spreadsheet → <b>Share</b> → thêm email của service account "
            "(dạng <i>xxx@xxx.iam.gserviceaccount.com</i>) quyền <b>Editor</b>.<br>"
            "<b>Đi tab \"Hướng dẫn Google API\" để xem chi tiết + giới hạn quota.</b>")
        tips.setWordWrap(True)
        tips.setTextFormat(Qt.RichText)
        tips.setStyleSheet("color:#475569;")
        lay.addWidget(tips)
        lay.addStretch(1)
        return w

    def _pick_credentials(self):
        start = str(self.ed["credentials_file"].text()) or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file service account JSON",
            str(Path(start).parent) if start else str(Path.home()),
            "JSON (*.json);;All files (*)")
        if path:
            self.ed["credentials_file"].setText(path)
            self.lbl_creds_status.setText(self._creds_status())

    def _creds_status(self) -> str:
        p = str(self.ed["credentials_file"].text()).strip()
        if not p:
            return "<span style='color:#64748B;'>Chưa chọn file - chế độ ngoại tuyến.</span>"
        if Path(p).expanduser().exists():
            return "<span style='color:#16A34A;'>✓ File credentials tồn tại.</span>"
        return f"<span style='color:#DC2626;'>✗ Không tìm thấy: {p}</span>"

    # ------------------------------------------------------------------ tab đồng bộ
    def _tab_sync(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.ed["auto_sync"] = QCheckBox("Tự động đồng bộ nền (khi có mạng)")
        self.ed["auto_sync"].setChecked(bool(self.settings.get("auto_sync", True)))
        form.addRow("", self.ed["auto_sync"])

        self.ed["sync_interval_sec"] = QSpinBox()
        self.ed["sync_interval_sec"].setRange(10, 3600)
        self.ed["sync_interval_sec"].setSingleStep(10)
        self.ed["sync_interval_sec"].setValue(int(self.settings.get("sync_interval_sec") or 60))
        form.addRow("Chu kỳ đồng bộ (giây):", self.ed["sync_interval_sec"])

        self.ed["lock_lease_sec"] = QSpinBox()
        self.ed["lock_lease_sec"].setRange(10, 600)
        self.ed["lock_lease_sec"].setValue(int(self.settings.get("lock_lease_sec") or 60))
        form.addRow("Thời hạn khóa ghi (giây):", self.ed["lock_lease_sec"])

        self.ed["batch_size"] = QSpinBox()
        self.ed["batch_size"].setRange(50, 5000)
        self.ed["batch_size"].setValue(int(self.settings.get("batch_size") or 400))
        form.addRow("Số dòng/lệnh ghi (batch):", self.ed["batch_size"])
        lay.addLayout(form)

        info = QTextEdit()
        info.setReadOnly(True)
        info.setHtml(
            "<h3 style='margin:4px 0'>Cách xử lý xung đột & mất mạng</h3>"
            "<ul>"
            "<li><b>Mất mạng:</b> lệnh nằm trong hàng đợi SQLite, không rơi; có mạng là đồng bộ tiếp "
            "(lũy thừa + giới hạn số lần thử).</li>"
            "<li><b>2 máy cùng sửa 1 dòng:</b> phần mềm đọc lại nội dung dòng trước khi ghi; nếu khác "
            "với hash đã lưu → đánh dấu <i>xung đột</i> và KHÔNG ghi đè ngầm, chờ người xác nhận.</li>"
            "<li><b>Khóa ghi (lease):</b> sheet <i>_Lock</i> trên Google Sheets ngăn 2 máy ghi cùng lúc "
            f"- thời hạn {int(self.settings.get('lock_lease_sec') or 60)}s rồi tự nhả.</li>"
            "<li><b>App_ID_Map:</b> sheet phụ ánh xạ ID nội bộ ↔ số dòng Sheets để cập nhật đúng dòng "
            "(không bao giờ chèn trùng).</li>"
            "</ul>")
        info.setMinimumHeight(220)
        lay.addWidget(info, 1)
        return w

    # ------------------------------------------------------------------ tab hướng dẫn
    def _tab_about(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setHtml("""
<h2 style="margin-top:0">Cấu hình Google API (chi tiết)</h2>
<ol>
<li>Mở <b>console.cloud.google.com</b> → <i>Create project</i> (ví dụ: <code>kho-phong</code>).</li>
<li><i>APIs &amp; Services → Library</i> → bật <b>Google Sheets API</b> và <b>Google Drive API</b>.</li>
<li><i>APIs &amp; Services → Credentials → Create credentials → Service account</i>:
  <ul>
    <li>Tên: <code>kho-sync</code> → Create → bỏ trống quyền → Done.</li>
    <li>Vào service account → <i>Keys → Add key → Create new key (JSON)</i> → tải file.</li>
  </ul>
</li>
<li>Đặt file JSON vào <code>config\\service_account.json</code> (file này KHÔNG được commit lên git)
  rồi trỏ đường dẫn trong tab <b>Google Sheets</b>.</li>
<li>Mở spreadsheet của bạn → <b>Share</b> → thêm email service account
  (<code>...@...iam.gserviceaccount.com</code>) với quyền <b>Editor</b>.</li>
<li>Copy <b>Spreadsheet ID</b> từ URL:
  <code>https://docs.google.com/spreadsheets/d/<b>1AbC...xyz</b>/edit</code></li>
<li>Bật checkbox <b>Đồng bộ Google Sheets</b> → Lưu.</li>
</ol>

<h2>Giới hạn quota của Google Sheets API (quan trọng)</h2>
<ul>
<li><b>Đọc (read):</b> khoảng <b>300 lệnh/phút</b>; <b>Ghi (write):</b> khoảng <b>60–100 lệnh/phút</b>
    cho mỗi project (theo tài liệu docs.googleapis.com - có thể Google điều chỉnh).</li>
<li>Phần mềm đã an toàn: gom nhiều dòng vào <b>1 lệnh batchUpdate</b>, giãn cách ~0.65s giữa các lần ghi,
    retry có lũy thừa khi gặp <code>429/5xx</code>.</li>
<li>Giới hạn <b>10 MB/request</b>, ~<b>100.000 ô</b>/lệnh giá trị - file kho của bạn (~60 dòng x 21 cột)
   <b>rất xa</b> so với giới hạn này.</li>
<li>Một spreadsheet tối đa <b>10 triệu ô</b> → thoải mái cho hàng nghìn căn hộ.</li>
<li>API KHÔNG có transaction nguyên tử → phần mềm dùng <b>khóa lease (_Lock)</b> +
    <b>content hash</b> để chống ghi đè; nếu nhiều người ghi liên tục, hãy cân nhắc backend trung tâm
    (Postgres/Firebase) thay vì Sheets.</li>
</ul>

<h2>Lưu ý an toàn dữ liệu</h2>
<ul>
<li>Dữ liệu chính lưu trong <code>data\\kho_phong.db</code> (SQLite, WAL) - backup theo ngày tại
    <code>data\\logs\\</code>.</li>
<li>Bật <b>Google Sheets</b> chỉ để đồng bộ/kết nối multi-device; tắt vẫn chạy đầy đủ chức năng.</li>
</ul>
""")
        lay.addWidget(txt)
        return w

    # ------------------------------------------------------------------ save
    def _restore_defaults(self):
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "Khôi phục mặc định",
                                "Đưa toàn bộ cài đặt về mặc định?") != QMessageBox.Yes:
            return
        from config import DEFAULTS
        self.settings.update(dict(DEFAULTS))
        self.accept()

    def _save(self):
        vals: Dict[str, Any] = {}
        for key, w in self.ed.items():
            if isinstance(w, QLineEdit):
                vals[key] = w.text().strip()
            elif isinstance(w, QCheckBox):
                vals[key] = w.isChecked()
            elif isinstance(w, QSpinBox):
                vals[key] = int(w.value())
        self.settings.update(vals)
        self.saved.emit(vals)
        self.accept()
