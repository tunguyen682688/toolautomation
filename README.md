# 🏠 KHO PHÒNG CĂN HỘ — Quản lý kho căn hộ cho thuê

Phần mềm máy tính (desktop, PySide6) quản lý kho phòng căn hộ cho thuê, dùng **Google Sheets làm nguồn dữ liệu
trung tâm** nhưng **hoạt động được hoàn toàn ngoại tuyến (offline-first)** với SQLite.

Ưu tiên thiết kế theo đặc tả: **tìm kiếm cực nhanh → cập nhật tức thì → chống trùng dữ liệu →
import/export Excel → đồng bộ Google Sheets**, giao diện đẹp xếp sau.

---

## 1. Cài đặt trên Windows

### Yêu cầu
- Windows 10/11, Python **3.10 – 3.12** (đã test trên Python 3.12 64-bit).
- Không cần cài thêm phần mềm nào khác (SQLite có sẵn trong Python).

### Các bước

```powershell
# 1) Vào thư mục dự án
cd D:\Workspace\SoftwareDevelopment\toolautomation

# 2) (Khuyến nghị) tạo môi trường ảo
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3) cài thư viện
pip install -r requirements.txt

# 4) chạy chương trình
python main.py
```

> **Lưu ý quan trọng:** Dự án **không dùng pandas/numpy** vì môi trường Windows có chính sách
> AppControl chặn DLL của numpy. Excel được đọc/ghi trực tiếp bằng `openpyxl` → nhẹ và nhanh hơn.

### File cấu trúc

```
toolautomation/
├── main.py               ← điểm khởi động (chạy file này)
├── main_window.py        ← cửa sổ chính, điều hướng, tìm kiếm, phím tắt, poll sự kiện
├── database.py           ← SQLite (khóa ghi BEGIN IMMEDIATE, unique index chống trùng)
├── inventory_manager.py  ← lớp nghiệp vụ trung tâm (mọi thay đổi đều qua đây)
├── search_engine.py      ← chỉ mục tìm kiếm trong bộ nhớ (inverted index, < 5ms)
├── duplicate_checker.py  ← kiểm tra trùng 5 lớp
├── excel_import.py       ← đọc Excel thông minh (nhận diện sheet + tiêu đề + ánh xạ cột)
├── excel_export.py       ← xuất Excel đúng cấu trúc 3 sheet, GIỮ công thức Thống Kê
├── google_sheets.py      ← Google Sheets API (batch, throttle, retry, khóa lease, content hash)
├── google_drive.py       ← mở link Drive/Zalo/tel & upload media
├── sync_queue.py         ← hàng đợi đồng bộ + worker thread nền + NetworkMonitor
├── models.py             ← trạng thái phòng, cột dữ liệu, filter, dataclass
├── config.py             ← SettingsStore (config/settings.json) + đường dẫn
├── text_utils.py         ← chuẩn hoá tiếng Việt (bỏ dấu, khoá nhận diện, giá tiền...)
├── logger.py / theme.py  ← nhật ký & chủ đề giao diện (QSS)
├── dashboard.py          ← Dashboard 9 chỉ số, biểu đồ, lịch sử thay đổi
├── building_view.py      ← lưới thẻ tòa nhà (FlowLayout) + form tòa
├── room_view.py          ← bảng phòng ảo hoá + bộ lọc + panel chi tiết + menu chuột phải
├── edit_form.py          ← form 8 nhóm + kiểm tra trùng debounce + Lưu / Lưu & thêm tiếp
├── import_dialog.py      ← nhập Excel: ánh xạ cột, xem trước 5 loại, không tự ghi đè
├── export_dialog.py      ← xuất Excel (giữ công thức) + file mẫu trống
├── settings.py           ← hộp thoại Cài đặt (Chung / Google / Đồng bộ / Hướng dẫn Google API)
├── data/                 ← dữ liệu (kho_phong.db), cache, logs  (tự tạo)
├── config/               ← settings.json + service_account.json (bạn tự đặt, KHÔNG commit)
├── samples/              ← dữ liệu mẫu kiểm thử
└── tests/                ← bộ kiểm thử (18 + 8 tình huống giao diện)
```

---

## 2. Cấu hình Google API (chi tiết, có thể làm sau)

> **Chưa có credentials?** Không sao — phần mềm chạy **hoàn chỉnh ngoại tuyến**: dữ liệu nằm trong
> `data/kho_phong.db`. Khi nào có Google API thì bật sau, mọi thay đổi không bị mất.

### Bước 1 — Tạo project & bật API
1. Vào **https://console.cloud.google.com** → **Create project** (ví dụ: `kho-phong`).
2. **APIs & Services → Library** → tìm và **Enable**:
   - **Google Sheets API**
   - **Google Drive API**

### Bước 2 — Tạo Service Account
1. **APIs & Services → Credentials → Create credentials → Service account**.
2. Tên: `kho-sync` → **Create and continue** → bỏ trống quyền → **Done**.
3. Bấm vào service account vừa tạo → tab **Keys → Add key → Create new key → JSON** → tải về.
4. Đặt file tải được vào `config\service_account.json`.

### Bước 3 — Chia sẻ spreadsheet cho service account
1. Mở spreadsheet của bạn → nút **Share**.
2. Nhập email của service account (dạng
   `kho-sync@ten-project.iam.gserviceaccount.com`) → quyền **Editor**.

### Bước 4 — Nạp ID & đường dẫn vào phần mềm
1. Lấy **Spreadsheet ID** từ URL:
   `https://docs.google.com/spreadsheets/d/`**`1AbC...xyz`**`/edit`
2. Mở phần mềm → **⚙ Cài đặt (Ctrl+Shift+S) → tab ☁️ Google Sheets**:
   - tick **Bật đồng bộ Google Sheets**
   - chọn file `service_account.json`
   - dán **Spreadsheet ID**
   - kiểm tra tên 3 sheet (`Kho Hàng Phòng Trống`, `Danh Mục Địa Điểm & Chủ Nhà`, `Thống Kê Nhanh`)
3. **Lưu** → trạng thái sidebar chuyển sang 🟢.

### Những sheet do phần mềm quản lý
| Sheet | Vai trò |
|---|---|
| `Kho Hàng Phòng Trống` | dữ liệu phòng (nguồn trung tâm) |
| `Danh Mục Địa Điểm & Chủ Nhà` | danh mục 55+ tòa |
| `Thống Kê Nhanh` | báo cáo — **giữ nguyên công thức COUNTIF/COUNTIFS** |
| `App_ID_Map` | ánh xạ **ID nội bộ ↔ số dòng** trên Sheets (phần mềm tự tạo) |
| `_Lock` | **khóa ghi (lease)** chống 2 máy ghi cùng lúc (phần mềm tự tạo) |

### ⚠ Giới hạn quota của Google Sheets API (đọc tại docs.googleapis.com)
- **Đọc (read):** ~**300 lệnh/phút**; **Ghi (write):** ~**60–100 lệnh/phút** cho mỗi project
  (Google có thể điều chỉnh — luôn kiểm tra lại tài liệu chính thức).
- Tối đa **10 MB/request**, ~**100.000 ô** mỗi lệnh giá trị; một spreadsheet tối đa **10 triệu ô**.
- API **không có transaction nguyên tử** → phần mềm dùng **khóa lease `_Lock` + content hash**
  để không ghi đè; nếu đội nhiều người ghi liên tục, cân nhắc backend trung tâm
  (Postgres/Firebase) thay vì Sheets.
- Phần mềm đã tự tiết kiệm quota: **gom batch** (`batch_size`, mặc định 400 dòng/lệnh),
  **giãn cách ~0.65s** giữa các lệnh ghi, **retry lũy thừa** khi gặp `429/5xx`,
  và **gộp (supersede) các lệnh pending** của cùng bản ghi.

---

## 3. Phím tắt

| Phím | Chức năng |
|---|---|
| `Ctrl+F` | Tìm kiếm nhanh (không dấu, không phân biệt hoa thường) |
| `Ctrl+N` | Thêm phòng mới |
| `Ctrl+I` | Nhập Excel |
| `Ctrl+E` | Xuất Excel |
| `Ctrl+Shift+S` | Cài đặt |
| `F5` | Làm mới toàn bộ |
| `Ctrl+1/2/3` | Tổng quan / Tòa nhà / Phòng |
| `Esc` | Đóng popup tìm kiếm |

---

## 4. Dữ liệu mẫu kiểm thử

| File | Nội dung |
|---|---|
| `samples/Kho_Hang_Phong_Trong_Co_Phuong.xlsx` | dữ liệu thật 3 sheet: 58 dòng phòng (header dòng 5), 55 tòa, sheet Thống Kê đầy công thức |
| `samples/import_them_mau.xlsx` | 7 dòng cố ý: **new=3, duplicate=1, changed=1, suspect=1, error=1** |

Lần chạy đầu nếu DB trống, chương trình sẽ **đề nghị nhập ngay file mẫu**.

---

## 5. Bộ kiểm thử (chạy được ngay, không cần mạng)

### 5.1. Kiểm thử backend — 18 tình huống

```powershell
$env:PYTHONIOENCODING='utf-8'     # console Windows cp1252 -> tránh lỗi hiển thị UTF-8
python tests\run_checks.py
# kỳ vọng: KẾT QUẢ: 18/18 PASS
```

### 5.2. Kiểm thử giao diện — 8 tình huống (chạy nền được)

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:QT_QPA_PLATFORM='offscreen'          # bỏ dòng này để thấy cửa sổ
python tests\ui_smoke.py
# kỳ vọng: UI: 8/8 PASS
```

### 5.3. 10 tình huống kiểm thử bắt buộc (đối chiếu với đặc tả)

| # | Tình huống | Cách kiểm | Kỳ vọng |
|---|---|---|---|
| **1** | Dashboard hiển thị đủ chỉ số | Chạy `python main.py` → trang Tổng quan | Đủ **9 thẻ KPI** (tổng/trống/sắp trống/thuê/cọc+giữ/khảo sát/xe điện/pet/tòa), biểu đồ trạng thái, lịch sử gần nhất; **bấm thẻ → mở trang Phòng kèm lọc** |
| **2** | Thêm phòng mới & chống trùng | `Ctrl+N` → nhập địa chỉ + số căn + mã phòng → Lưu; rồi nhập **đúng lại** lần nữa | Lần 1 lưu OK (tự gắn đúng tòa đã có); lần 2 hiện **⛔ PHÒNG NÀY ĐÃ TỒN TẠI** kèm thông tin bản cũ + nút **“Mở bản ghi cũ”**, **nút Lưu bị tắt** |
| **3** | Nhập Excel dữ liệu trùng/khác kiểu | `Ctrl+I` → chọn `samples/import_them_mau.xlsx` (2 lần liên tiếp) | Phân loại đúng **5 loại**; mặc định **chỉ tick “Dữ liệu mới”**; trùng/lỗi **không được tick**; nhập lần 2 **không sinh thêm bản ghi** |
| **4** | Thêm phòng vào tòa đã tồn tại | Thêm phòng ở địa chỉ `86 Nguyễn Thượng Hiền` (đã có) | Tự **liên kết tòa cũ**, không tạo tòa mới; banner báo “Địa chỉ đã có → sẽ tự liên kết” |
| **5** | 2 người cùng thêm 1 căn 1 lúc | `python tests\run_checks.py` (test #5) | Chỉ **1 bản ghi hợp lệ**, bản kia bị chặn (BEGIN IMMEDIATE + unique index) |
| **6** | Sửa giá thuê trên phần mềm | Sửa giá 1 phòng trong bảng/form | DB đổi ngay, tìm theo giá mới ra đúng phòng, có **1 lệnh pending** đưa lên Google Sheets |
| **7** | Xuất Excel & giữ công thức | `Ctrl+E` → xuất → mở file bằng Excel | Đúng **3 sheet**, header dòng 5, **công thức COUNTIF/COUNTIFS còn nguyên**, thêm 2 cột **Số Căn / Tầng ở cuối**; nhập lại file xuất ra **không bị coi là dữ liệu mới** |
| **8** | Tìm kiếm siêu nhanh, không dấu | Gõ `nguyen thuong hien`, `NGUYEN  THUONG  HIEN`, `P-86`, `p86`, `Studio`, `7000000` | Kết quả **giống hệt** có/không dấu, thừa khoảng trắng; **< 20ms** (đo thực tế ~0,4ms) |
| **9** | Đổi trạng thái “Đã thuê → Trống” | Menu chuột phải trên bảng → Đổi trạng thái | **Không sinh ID mới**, version tăng, có **lịch sử** (trạng thái cũ → mới, thời gian, người thực hiện, ghi chú) |
| **10** | Mất mạng / khôi phục đồng bộ | Tắt mạng (hoặc để Google tắt) rồi sửa dữ liệu | Lệnh **nằm yên trong hàng đợi** (không rơi, không báo lỗi); có mạng + đã cấu hình là **đồng bộ tiếp**; dòng Sheets bị máy khác sửa → đánh dấu **xung đột, KHÔNG ghi đè ngầm** |

**Bonus:** kiểm tra khóa ghi nhiều người (`locks` + `_Lock` trên Sheets), xóa mềm/khôi phục phòng,
nhân bản phòng, panel chi tiết + lịch sử, popup tìm kiếm toàn cục.

---

## 6. Nguyên tắc quan trọng của phần mềm

1. **Offline-first:** SQLite luôn sẵn sàng; Google chỉ là lớp đồng bộ nền, thiếu credentials
   vẫn dùng bình thường.
2. **Khoá nhận diện căn hộ** = `(tòa nhà, số căn)`; thiếu số căn → dùng mã phòng hợp lệ
   (phải có chữ số), nếu thiếu cả hai → đánh dấu **⚠ cần xác minh** (không bao giờ tự suy đoán).
3. **Chống trùng 5 lớp** (địa chỉ → tòa → căn hộ → mã phòng → bản ghi tương tự) +
   **unique index SQLite** là chốt chặn cuối; kiểm tra trùng và ghi nằm **trong cùng khoá ghi**.
4. **Không ghi đè khi chưa xác nhận:** import mặc định chỉ thêm dòng *mới*; dòng *đã thay đổi*
   phải tự tick; dòng trùng/lỗi không bao giờ được chọn.
5. **Đồng bộ an toàn:** `idem_key` (một thay đổi = một lệnh), supersede lệnh pending,
   throttle + retry 429/5xx, khóa lease `_Lock`, content hash chống ghi đè,
   `App_ID_Map` ánh xạ đúng dòng.
6. **Giao diện không bao giờ bị đơ:** mọi ghi dữ liệu đều nhanh (< 10ms), sự kiện từ worker
   thread chỉ về qua **deque + QTimer** (không chạm widget từ thread nền).

---

## 7. Xử lý sự cố thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| `ModuleNotFoundError: PySide6` | `pip install -r requirements.txt` |
| Chữ Việt hiện thành `???` trong console | `$env:PYTHONIOENCODING='utf-8'` trước khi chạy |
| “Chưa cấu hình Google” | Vào **Cài đặt → tab ☁️ Google Sheets**, làm đủ 4 bước ở mục 2 |
| Lỗi `429 Quota exceeded` | Giảm `sync_interval_sec`, tăng `batch_size` — phần mềm đã tự retry |
| Muốn reset dữ liệu | Đóng chương trình, đổi tên `data\kho_phong.db` (hoặc xóa), chạy lại và nhập Excel |
| Xem log | `data\logs\app.log`, `data\logs\sync.log` |
