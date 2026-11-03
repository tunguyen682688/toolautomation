# 🏠 KHO PHÒNG CĂN HỘ — Quản lý kho căn hộ cho thuê

Phần mềm máy tính (desktop, PySide6) quản lý kho phòng căn hộ cho thuê, dùng **Google Sheets làm nguồn dữ liệu
trung tâm** nhưng **hoạt động được hoàn toàn ngoại tuyến (offline-first)** với SQLite.

Ưu tiên thiết kế theo đặc tả: **tìm kiếm cực nhanh → cập nhật tức thì → chống trùng dữ liệu →
import/export Excel → đồng bộ Google Sheets**, giao diện đẹp xếp sau.

Ngoài ra phần mềm còn tách **3 môi trường độc lập** (`dev` / `staging` / `prod`),
mỗi env có database, log và cấu hình **riêng hoàn toàn** — thử nghiệm thoải mái
mà không bao giờ ảnh hưởng dữ liệu thật (xem mục 1.3).

---

## MỤC LỤC

| Mục | Nội dung |
|---|---|
| [1. Cài đặt trên Windows](#1-cài-đặt-trên-windows) | Cài từ nguồn, **1.3 môi trường DEV/STAGING/PROD**, cấu trúc thư mục |
| [2. Cấu hình Google API](#2-cấu-hình-google-api-chi-tiết-có-thể-làm-sau) | 4 bước, các sheet quản lý, giới hạn quota |
| [3. Phím tắt](#3-phím-tắt) | Bàn phím tắt |
| [4. Dữ liệu mẫu kiểm thử](#4-dữ-liệu-mẫu-kiểm-thử) | 2 file Excel mẫu |
| [5. Bộ kiểm thử](#5-bộ-kiểm-thử-chạy-được-ngay-không-cần-mạng) | 21 backend + 5 phân biệt 3 trạng thái + 10 giao diện + selftest + 10 tình huống bắt buộc |
| [6. Nguyên tắc quan trọng](#6-nguyên-tắc-quan-trọng-của-phần-mềm) | Offline-first, chống trùng, đồng bộ an toàn |
| [7. Xử lý sự cố](#7-xử-lý-sự-cố-thường-gặp) | Bảng lỗi thường gặp |
| [8. Build bản Windows (.exe)](#8-build-bản-windows-exe-cho-người-dùng-cuối) | Đóng gói, chạy trên máy khác, selftest |
| [9. Lịch sử thay đổi](#9-lịch-sử-thay-đổi) | Các lần cập nhật |

---

## 1. Cài đặt trên Windows

### 1.1. Yêu cầu
- Windows 10/11, Python **3.10 – 3.12** (đã test trên Python 3.12 64-bit).
- Không cần cài thêm phần mềm nào khác (SQLite có sẵn trong Python).

### 1.2. Các bước

```powershell
# 1) Vào thư mục dự án
cd D:\Workspace\SoftwareDevelopment\toolautomation

# 2) (Khuyến nghị) tạo môi trường ảo
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3) cài thư viện
pip install -r requirements.txt

# 4) chạy chương trình (mặc định: môi trường DEV)
python main.py

# hoặc chọn môi trường:  dev | staging | prod
python main.py --env staging

# hoặc dùng start.bat (tự tạo venv + cài thư viện nếu thiếu, rồi chạy):
start.bat                    # dev
start.bat --env staging      # staging
```

> **Lưu ý quan trọng:** Dự án **không dùng pandas/numpy** vì môi trường Windows có chính sách
> AppControl chặn DLL của numpy. Excel được đọc/ghi trực tiếp bằng `openpyxl` → nhẹ và nhanh hơn.

### 1.3. Môi trường DEV / STAGING / PROD

Phần mềm tách **3 môi trường hoàn toàn độc lập** — mỗi môi trường có database,
log và file cấu hình **riêng**, không ảnh hưởng lẫn nhau:

| Môi trường | Dữ liệu | Cấu hình | Dùng để |
|---|---|---|---|
| `dev` | `data/dev/kho_phong.db` | `config/settings_dev.json` | Phát triển, thử code (**mặc định khi chạy `python main.py`**) |
| `staging` | `data/staging/kho_phong.db` | `config/settings_staging.json` | Kiểm thử trước khi đưa vào dùng thật |
| `prod` | `data/prod/kho_phong.db` | `config/settings_prod.json` | Sản xuất — dữ liệu thật (**mặc định khi chạy `.exe`**) |

**Cách chọn môi trường** (ưu tiên từ trên xuống):

1. Cờ `--env` trên dòng lệnh: `python main.py --env staging`
2. Biến môi trường Windows: `set KHO_APP_ENV=staging` rồi chạy `python main.py`
3. Mặc định: `dev` khi chạy từ nguồn, `prod` khi chạy bản build `.exe`

**Nhận biết đang ở môi trường nào:** huy hiệu **`[DEV]` / `[STAGING]` / `[PROD]`** hiện ở
góc trái thanh trạng thái và ở tiêu đề cửa sổ (DEV xám, STAGING cam, PROD xanh lá).

Ví dụ thực tế — **dùng staging để thử đồng bộ Google Sheets với bảng nháp, không đụng bảng thật:**

```powershell
# env prod đang trỏ spreadsheet_id = BẢNG THẬT
# env staging trỏ spreadsheet_id = BẢNG NHÁP (copy để test)  -> tha hồ thử mà không lo mất dữ liệu
python main.py --env staging
```

> **Chuyển dữ liệu cũ:** nếu bạn từng chạy bản trước khi tách môi trường
> (có `data/kho_phong.db` và `config/settings.json` ở thư mục gốc), phần mềm **tự động
> chuyển chúng vào env mặc định** ở lần chạy đầu tiên (kèm file `-wal` của SQLite).
> Muốn env khác dùng dữ liệu đó thì tự copy `data/<env>/kho_phong.db`.

### 1.4. File cấu trúc

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
├── config.py             ← SettingsStore + đường dẫn + XÁC ĐỊNH MÔI TRƯỜNG (--env)
├── text_utils.py         ← chuẩn hoá tiếng Việt (bỏ dấu, khoá nhận diện, giá tiền...)
├── logger.py / theme.py  ← nhật ký & chủ đề giao diện (QSS)
├── dashboard.py          ← Dashboard 9 chỉ số, biểu đồ, lịch sử thay đổi
├── building_view.py      ← lưới thẻ tòa nhà (FlowLayout) + form tòa
├── room_view.py          ← bảng phòng ảo hoá + bộ lọc + panel chi tiết + menu chuột phải
├── customer_manager.py   ← CRM: khách tiềm pipeline + dắt căn + điểm sai tư vấn/xử lý (phân tích sale)
├── customer_view.py      ← trang Khách hàng: bảng pipeline + chi tiết (dắt căn/điểm sai) + tab Phân tích
├── edit_form.py          ← form 8 nhóm + kiểm tra trùng debounce + Lưu / Lưu & thêm tiếp
├── quick_add.py          ← ⚡ Tạo nhanh từ Zalo: dán ảnh clipboard -> Enter là có phòng
├── import_dialog.py      ← nhập Excel: ánh xạ cột, xem trước 5 loại, không tự ghi đè
├── export_dialog.py      ← xuất Excel (giữ công thức) + file mẫu trống
├── settings.py           ← hộp thoại Cài đặt (Chung / Google / Đồng bộ / Hướng dẫn Google API)
├── data/                 ← MỖI MÔI TRƯỜNG MỘT THƯ MỤC (tự tạo):
│   ├── dev/    kho_phong.db · logs/ · cache/
│   ├── staging/kho_phong.db · logs/ · cache/
│   └── prod/   kho_phong.db · logs/ · cache/
├── config/               ← settings_<env>.json + service_account.json (KHÔNG commit)
├── samples/              ← dữ liệu mẫu kiểm thử
├── start.bat             ← tạo venv + cài thư viện + chạy (hỗ trợ --env)
├── build.bat             ← build bản Windows (.exe) + selftest
├── KhoPhongCanHo.spec    ← cấu hình PyInstaller
└── tests/                ← bộ kiểm thử (21 + 5 + 10 tình huống)
```

---

## 2. Cấu hình Google API (chi tiết, có thể làm sau)

> **Chưa có credentials?** Không sao — phần mềm chạy **hoàn chỉnh ngoại tuyến**: dữ liệu nằm trong
> `data/<env>/kho_phong.db` (ví dụ `data/dev/kho_phong.db`). Khi nào có Google API thì bật sau,
> mọi thay đổi không bị mất.

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
| `Ctrl+1/2/3/4` | Tổng quan / Tòa nhà / Phòng / Khách hàng |
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

### 5.1. Kiểm thử backend — 25 tình huống

```powershell
$env:PYTHONIOENCODING='utf-8'     # console Windows cp1252 -> tránh lỗi hiển thị UTF-8
python tests\run_checks.py
# kỳ vọng: KẾT QUẢ: 25/25 PASS
```

### 5.2. Kiểm thử phân biệt 3 trạng thái (Chưa biết / Có / Không) — 5 tình huống

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:QT_QPA_PLATFORM='offscreen'
python tests\tri_state_check.py
# kỳ vọng: TRI-STATE: 5/5 PASS
```

Phủ: round-trip None qua DB (NULL thật), update Có↔Không↔Chưa biết, xuất→nhập Excel
giữ nguyên 3 trạng thái, search_norm/fingerprint/hiển thị phân biệt rõ, migration DB cũ
cột NOT NULL → build lại bảng (chuỗi rỗng & giá 0 cũ → NULL, dữ liệu 0/1 đã rõ giữ nguyên).

### 5.3. Kiểm thử giao diện — 12 tình huống (chạy nền được)

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:QT_QPA_PLATFORM='offscreen'          # bỏ dòng này để thấy cửa sổ
python tests\ui_smoke.py
# kỳ vọng: UI: 12/12 PASS
```

### 5.4. Selftest — kiểm tra nhanh 14 đầu việc (có ở cả nguồn lẫn bản build)

```powershell
python main.py --selftest                  # chạy từ nguồn
# hoặc trên bản build:
dist\KhoPhongCanHo\KhoPhongCanHo.exe --selftest --env staging
```

Chạy nền (không hiện cửa sổ), dùng **DB tạm** nên không đụng dữ liệu thật. Tự làm:
nhập Excel mẫu → mở Dashboard/Tòa nhà/Bảng phòng → tìm kiếm không dấu → xuất Excel →
kiểm tra env được tách riêng. Exit code `0` = tốt, `1` = lỗi; chi tiết ghi vào
`data/<env>/selftest_result.txt`. Đây là bước cuối của `build.bat` (build fail nếu selftest fail).

### 5.5. 10 tình huống kiểm thử bắt buộc (đối chiếu với đặc tả)

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
nhân bản phòng, panel chi tiết + lịch sử, popup tìm kiếm toàn cục,
**⚡ tạo nhanh từ Zalo** (copy ảnh → dán → Enter: check tòa nhà/loại phòng/trùng mã, ảnh vào thư mục quy ước).

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
| **Dữ liệu “biến mất” / không thấy phòng đã nhập** | **Kiểm tra huy hiệu `[DEV]`/`[STAGING]`/`[PROD]`** — rất có thể bạn đang ở env khác; mỗi env có `data/<env>/kho_phong.db` riêng |
| **Muốn dồn dữ liệu 2 env vào 1 env** | Đóng app, copy `data/<env_tu>/kho_phong.db` đè lên `data/<env_dich>/kho_phong.db`, mở lại |
| Muốn reset dữ liệu của 1 env | Đóng chương trình, đổi tên (hoặc xóa) `data\<env>\kho_phong.db`, chạy lại và nhập Excel |
| Xem log | `data\<env>\logs\app.log`, `data\<env>\logs\sync.log` (vd `data\prod\logs\app.log`) |
| Bản build `.exe` chạy rồi tắt ngay | Chạy thử `KhoPhongCanHo.exe --selftest` rồi xem `data\<env>\selftest_result.txt`; hoặc `ChayUngDung.bat` để hiện thông báo lỗi |
| App báo “không ghi được dữ liệu” | Kiểm tra quyền ghi thư mục chứa `.exe` (nên để ở `C:\` hoặc Desktop, **không** để trong `Program Files`) |

---

## 8. BUILD BẢN WINDOWS (.EXE) CHO NGƯỜI DÙNG CUỐI

Máy người dùng cuối **không cần cài Python** — chỉ cần copy thư mục build.

### 8.1. Tạo bản build (trên máy có Python)

```
build.bat
```

Script tự làm đủ 4 bước: cài PyInstaller → đóng gói (`KhoPhongCanHo.spec`) →
chép tài liệu + dữ liệu mẫu vào bản build → chạy `--selftest` tự kiểm tra
(**14 kiểm tra**: nhập Excel, mở các trang, tìm kiếm, xuất Excel, tạo nhanh từ Zalo, xác minh env).
Selftest fail ⇒ hủy build.

> **Ghi chú:** PyInstaller **không nằm trong `requirements.txt`** (chỉ cần khi build).
> `build.bat` tự cài/nâng cấp nó. Bản build là **onedir** (một thư mục) thay vì onedir
> (`--onefile`) vì PySide6 giải nén ~200 MB mỗi lần mở → mở chậm 8–15s; onedir mở ~1–2s.

Kết quả: `dist\KhoPhongCanHo\` (~235 MB), cấu trúc:

```
dist\KhoPhongCanHo\
├── KhoPhongCanHo.exe      ← file chạy chính (double-click = môi trường PROD)
├── ChayUngDung.bat        ← chạy môi trường PROD (dữ liệu thật)
├── ChayStaging.bat        ← chạy môi trường STAGING (thử nghiệm)
├── ChayDev.bat            ← chạy môi trường DEV (phát triển)
├── Huong_Dan.md           ← tài liệu (README)
├── requirements.txt
├── du_lieu_mau\           ← 2 file Excel mẫu để kiểm thử import
├── _internal\             ← thư viện (KHÔNG xóa, KHÔNG sửa)
├── config\                ← TẠO TỰ ĐỘNG: settings_dev/staging/prod.json, Google API
└── data\                  ← TẠO TỰ ĐỘNG, MỖI MÔI TRƯỜNG MỘT THƯ MỤC:
    ├── dev\     kho_phong.db · logs\ · selftest_result.txt
    ├── staging\ kho_phong.db · logs\ · selftest_result.txt
    └── prod\    kho_phong.db · logs\
```

Mỗi môi trường có database và cấu hình **riêng hoàn toàn** — thử trên staging
không ảnh hưởng dữ liệu prod. Xem mục **1.3. Môi trường DEV / STAGING / PROD**.

### 8.2. Chạy trên máy khác

1. Copy **cả thư mục** `dist\KhoPhongCanHo\` sang máy đích (USB, zip…).
   Không copy riêng `.exe` — thư mục `_internal` chứa thư viện Qt/Python đi kèm.
2. Chọn cách chạy (mỗi cách là một env, **data + config riêng biệt**):
   - `ChayUngDung.bat` → **PROD** (dữ liệu thật; cũng là mặc định khi bấm đúp `.exe`)
   - `ChayStaging.bat` → **STAGING** (thử nghiệm)
   - `ChayDev.bat` → **DEV** (phát triển)
   - hoặc tự chạy: `KhoPhongCanHo.exe --env prod|staging|dev`
3. Lần đầu chạy, app tự tạo `data\<env>\` + `config\` cạnh file `.exe` và mời nhập dữ liệu Excel.

> **Lưu ý quyền ghi:** để thư mục ở vị trí được phép ghi (Desktop, `C:\Apps`…).
> **Không** để trong `Program Files` — Windows chặn ghi và app sẽ không tạo được database.

### 8.3. Gỡ / dọn bản build

Xóa cả thư mục `dist\KhoPhongCanHo\` là đủ — không ghi gì vào registry hay AppData.
Muốn giữ dữ liệu thì backup thư mục `data\` (chứa `dev\`, `staging\`, `prod\`) trước khi xóa.

### 8.4. Chế độ --selftest

```
dist\KhoPhongCanHo\KhoPhongCanHo.exe --selftest --env staging
```

Chạy nền (không hiện cửa sổ), tự nhập dữ liệu mẫu → mở 3 trang → tìm kiếm → xuất Excel →
xác minh env tách riêng (**14 kiểm tra**). Exit code `0` = tốt, `1` = lỗi;
chi tiết ghi vào `data\<env>\selftest_result.txt`.
`build.bat` tự chạy selftest ở env **staging** và hủy build nếu fail.

---

## 9. Lịch sử thay đổi

| Ngày | Thay đổi |
|---|---|
| 2026-11-03 | **📂 ĐỔI THƯ MỤC LƯU TRỮ (DB + logs + backup + cache) — tab Cài đặt → Chung.** Ô \"Thư mục dữ liệu\" có nút **Chọn...** chọn thư mục mới; bấm Lưu sẽ **copy toàn bộ DB (kèm WAL/SHM), logs/, backup/, cache/ sang chỗ mới**, thư mục cũ **giữ nguyên làm backup**. App chạy ngay ở chỗ mới (không cần khởi động lại) nhờ `Database.reconnect()`; `LOG_DIR`, `CACHE_DIR` tự tính theo `db_path` setting lúc runtime (`config.get_log_dir()`, `config.get_cache_dir()`). Test t24: backend **24/24**, UI **12/12**, selftest **14/14**. |
| 2026-11-02 | **⚡ TẠO NHANH TỪ ZALO: copy ảnh phòng -> dán -> Enter là có phòng (không cần bấm "Thêm phòng" rồi mò file Downloads).** Module mới `quick_add.py` + nút **"⚡ Tạo nhanh từ Zalo"** trên thanh lọc trang Phòng (kèm nút 🎯 Yêu cầu khách). Dialog **tự đọc clipboard ngay khi mở** và **tự đọc lại khi quay lại app (Alt-Tab)**: ảnh copy từ Zalo (đường dẫn file CF_HDROP **hoặc** ảnh bitmap → lưu PNG tạm) hiện xem trước + đếm số ảnh; **chữ trong tin nhắn** (nếu có) tự tách địa chỉ / giá / dạng phòng / tầng / diện tích / SĐT để điền sẵn **chỉ vào ô còn trống** (không ghi đè; chữ không giống tin đăng → không tự điền gì; bỏ `notes` vì parser gán notes = nguyên văn). **Check LIVE 3 lớp (debounce 250ms)**: 🏢 **TÒA NHÀ đã có chưa** (tự liên kết / tạo mới, kèm % tương đồng nếu nghi trùng) · 🧱 **LOẠI PHÒNG đó đã có trong tòa chưa** (liệt kê mã phòng đang có: "Tòa này đã có 1 phòng Studio: S-77" hoặc "Tòa đã có nhưng CHƯA có phòng loại Penthouse") · ⛔ **trùng số căn/mã** → chặn Lưu + nút "📂 Mở bản ghi trùng". **1 Enter = Lưu & mở phòng** (nút Lưu tự tắt khi thiếu địa chỉ/khóa nhận diện — không popup), lưu xong ảnh tự `import_files` vào **thư mục quy ước** của phòng rồi mở panel chi tiết + hiện "✅ Đã tạo … — N ảnh đã vào thư mục quy ước" ở thanh trạng thái; Alt-Tab về app sau khi copy ảnh tiếp cũng tự nạp. Tách 3 hàm thuần để test không cần Qt: `norm_price()` (rỗng → **NULL = Chưa biết**, không ép 0), `autofill_from_text()`, `type_in_building()`. Test: backend **23/23** (t23 mới) + UI **12/12** (check "dán ảnh → lưu phòng + ảnh vào thư mục + check tòa/loại phòng") + selftest **14/14** (3 check mới: có nút, tách tin nhắn, check loại phòng — xác nhận module có trong bản build). |
| 2026-11-02 | **QUẢN LÝ "ĐÃ DẮT CĂN NÀO" + "ĐIỂM SAI TRONG TƯ VẤN & XỬ LÝ" (VD: chăm khách rồi mới dắt khách).** Bảng SQLite mới `customer_showings` (căn + `room_label` CHỤP LẠI lúc dắt + ngày + phản hồi khách4 mức + ghi chú + điểm sai kèm lúc dắt), 3 index theo khách/căn/ngày. **Panel chi tiết khách** (bọc `QScrollArea` vì nội dung dài): nút **🏠 Ghi dắt căn** (dialog chọn căn từ kho — có combo editable để gõ căn đã bán/đã xóa — + ngày + phản hồi + điểm sai kèm + ghi chú), nút **⚠️ Điểm sai xử lý** (danh mục 10 lỗi PROCESS_ERRORS, đầu danh mục là «Chăm khách rồi mới dắt khách (để khách nguội)»), nhãn đếm điểm sai, khối **CĂN ĐÃ DẮT KHÁCH XEM** (chuột phải → xóa lượt dắt, có ghi vào dòng thời gian). `CustomerManager` mới: `showings()/log_showing()/remove_showing()/log_mistake()/mistake_count()` — mỗi lượt dắt **tự ghi event `view`**, kèm điểm sai thì ghi thêm event `mistake`; cột **"Đã dắt"** trong bảng pipeline (subquery đếm); `stats()` trả thêm `showings_*` + `mistakes_*` + `top_rooms` + `top_mistakes`. **Tab Phân tích** tách 3 khối riêng: ❌ ĐIỂM SAI KHI SALE (bar đỏ) · ⚠️ ĐIỂM SAI TRONG TƯ VẤN & XỬ LÝ (bar cam) · 🏠 CĂN ĐÃ DẮT KHÁCH XEM (bar xanh); KPI tăng 5→**7** (thêm *Lượt dắt khách*, *Điểm sai xử lý*), 2 hint riêng + 2 insight mới; nhãn thanh dài quá 34 ký tự tự cắt + "…". Bug sửa kèm: `CustomerPage.refresh()` trước chỉ gọi `set_customer` khi đổi khách → panel không nạp lại lượt dắt/điểm sau khi ghi (giờ luôn nạp lại). Test: backend **22/22** (check 22 mới) + UI **11/11** (check "dắt căn + điểm sai" mới) + tri-state 5/5. |
| 2026-11-02 | **TRANG KHÁCH HÀNG (CRM) + phân tích "mình sai điểm nào khi sale".** Module mới `customer_manager.py` (bảng `customers` + `customer_events` trong SQLite) và `customer_view.py` (nav 👥 Khách hàng, Ctrl+4). **Bảng pipeline** phân cụm theo 8 trạng thái (Mới → Liên hệ → Tư vấn → Hẹn xem → Cọc → Chốt / Tạm hoãn / Mất khách) + tìm không dấu (tên/SĐT/Zalo/yêu cầu, token AND) + lọc trạng thái/nguồn + KPI. **Panel chi tiết**: đổi trạng thái trực tiếp (về **Mất khách bắt buộc chọn lý do** = "điểm sai khi sale", hồi sinh tự xóa lý do), nút Gọi/Zalo (tel: & zalo.me), ghi tương tác nhanh (📞đã gọi / 💬đã nhắn / 👁đã xem / 📝ghi chú) + lịch sử đầy đủ. **Tab "Phân tích điểm sai khi sale"**: FUNNEL thật (số khách đã TỪNG tới từng khâu, tính từ lịch sử trạng thái — chỉ ra "rơi nhiều nhất sau khâu X: N khách"), **TOP LÝ DO MẤT KHÁCH** (bar đỏ + "Điểm sai #1: «Giá cao» — x/N khách mất"), nguồn khách, hoạt động selling, tỷ lệ chốt % + số ngày trung bình chốt + nhận định tự động. Nút **"➕ Lưu thành khách hàng"** trong hộp thoại Tìm theo yêu cầu khách (prefill yêu cầu/ngân sách/đã parse). Test: backend **21/21** (check 21: pipeline + lý do + funnel + conversion 50% + tìm không dấu) + UI **10/10** (trang khách: form → bảng → panel → đổi trạng thái → phân tích render → lọc). Dashboard 9 thẻ không đổi. |
| 2026-11-02 | **Copy ảnh dán vào Zalo: NHIỀU ảnh trong 1 tin nhắn + lưu ảnh bền vào thư mục quy ước.** Helper mới `media_manager.copy_files_to_clipboard()` — đưa file vào clipboard dạng CF_HDROP (đường dẫn tuyệt đối), **không đặt bitmap khi >1 ảnh** (clipboard có ảnh bitmap thì Zalo bóp thành 1 ảnh dán) → dán Ctrl+V 1 lần = N file trong MỘT tin nhắn; đúng 1 ảnh thì kèm bitmap cho mượt. Sửa lỗ hổng lớn: `QListWidget` mặc định `SingleSelection` → **không chọn được nhiều file** để copy — cả panel Ảnh/Video và ô ảnh trong form đều chuyển sang `ExtendedSelection` (Ctrl/Shift/Ctrl+A). Panel: nút 📋 copy selection hoặc **tất cả** khi chưa chọn gì, phản hồi "✅ Đã copy N file" tự hoàn nguyên, menu chuột phải thêm "Copy TẤT CẢ". Form: nút 📋 copy ảnh đang chọn/tất cả (đổi nhãn "Đã copy N ảnh ✓"3s), menu chuột phải copy; **mở form sửa tự nạp ảnh từ thư mục quy ước** (trước là `pass`), và **bấm Lưu tự copy ảnh vào thư mục quy ước** (ảnh dán từ Zalo nằm trong TEMP sẽ mất khi dọn tạm; trùng trùng dung lượng tự bỏ qua; banner báo "N ảnh đã vào thư mục"). Sửa bug tiềm ẩn: `ImageUpload._refresh` dùng `QIcon` mà không import (thêm ảnh vào form là lỗi NameError). Test mới trong `ui_smoke` (9/9): chọn nhiều + copy2 ảnh = file-only + copy1 ảnh = file+bitmap + lưu vào thư mục quy ước; ghi chú Qt offscreen PySide6 6.12 crash 0xC0000005 nếu thoát khi clipboard còn dữ liệu (platform windows thật không bị → test clear clipboard trước khi thoát). |
| 2026-11-02 | **Phân biệt 3 trạng thái Chưa biết/Có/Không thật sự trong dữ liệu (NULL, không ép về 0).** Nguyên tắc: `1` = Có, `0` = Không, `NULL` = **Chưa biết** (đang hỏi chủ nhà). **Database**: schema `rooms` bỏ `NOT NULL` ở 10 cột (`floor/area/capacity/rating/pet_policy/price/deposit/surveyed/ev_support/foreign_guest`) + `_migrate_nullable_rooms()` tự build lại bảng cho DB cũ (copy → rename trong 1 transaction, có phục hồi `rooms_old_mig`; chuỗi rỗng & price/deposit=0 cũ → NULL, 0/1 đã rõ giữ nguyên; sửa bug `"rooms" not in info` — `info` là cột PRAGMA nên migration luôn bị bỏ qua). **Import** (`tri_parse_survey`/`tri_parse_yes_no`): ô trống → None, fill-only (payload None không ghi đè dữ liệu cũ). **Export**: tri-state → "Chưa biết", price/deposit NULL → ô trống (không ghi 0 giả). **Chống trùng**: fingerprint dùng `?` phân biệt None vs 0; `_same_significant`/`_diff_fields` so tri-state (bỏ 2 dòng so tay bool gây nhãn trùng). **Form**: checkbox "Chưa biết" cho số (tầng/diện tích/giá/cọc/sức chứa — seed giá/cọc 0 cũ → tick), `surveyed` chuyển sang combo 3 trạng thái; sửa **bug GC** `_line_with_unknown` (QWidget container không parent bị GC → "Internal C++ object already deleted", gây 3 FAIL UI). **Bảng/panel**: "Chưa biết"/"✕ Không"/"❔ Chưa biết", sửa ô trống → None. Hiển thị giá ở bảng/popup/tòa/chi tiết đều nói rõ "Chưa biết" thay vì "0 ₫". Test mới `tests/tri_state_check.py` (5/5). Kết quả: **backend 20/20 + tri-state 5/5 + UI 8/8 PASS**. |
| 2026-11-01 | **Bảng Tòa nhà kiểu bảng + phân cụm PHƯỜNG cho cả 2 danh sách.** Module mới `grouped_table.py` — `GroupedTableModel` (QAbstractTableModel có hàng tiêu đề nhóm xen giữa dòng dữ liệu: `rows` vẫn là dữ liệu thuần, `_disp` ánh xạ dòng hiển thị → hàng nhóm chỉ chọn được Enabled, delegate `paint_group_row` vẽ nền full-width + viền trái accent + meta căn phải, giữ nguyên thứ tự relevance bên trong nhóm). Trang **Tòa nhà bỏ lưới thẻ → bảng QTableView** giống trang Phòng (11 cột: mã/**số nhà**/**tên đường**/phường/quận/chủ nhà/SĐT/Tổng·Trống·Cọc·Thuê·Sắp trống, cột tên đường co giãn, click chọn → panel phòng bên phải, double-click mở bảng đầy đủ). **Cả 2 bảng phân cụm theo phường** (checkbox "🏘 Phân cụm phường", bật mặc định): mỗi phường một hàng `📍 P.xx · quận · N phòng · X trống`; tòa nhà gộp khoá `(quận, phường)` để tránh trùng tên phường giữa 2 quận. Test: backend 20/20 + UI 8/8 + selftest 12/12 PASS, render 1920×1080 cả 2 theme. |
| 2026-11-01 | **Panel chi tiết phòng: nút hành động hàng ngang chỉ icon + tooltip + khảo sát nhanh mở rộng.** Các nút action (Sửa chi tiết, Xem tòa nhà, Gọi điện, Zalo, Drive, Lịch sử, Xóa) chuyển thành `QToolButton` 44×44px chỉ hiển thị icon, toàn bộ mô tả đưa vào tooltip; sắp xếp trên 1 hàng ngang với stretch cuối. Thêm 5 combo khảo sát nhanh (Có/Không/Chưa biết): Khảo sát, Xe điện, Khách NNGO, Pet và **Đánh giá (★1…★5 sao)** — chọn xong gọi `update_room` ngay, hỗ trợ giá trị `None`/`""` = "chưa biết" (chưa hỏi khi chưa khảo sát tòa nhà). Chip hiển thị tự đồng bộ theo dữ liệu. Test: backend 20/20 + UI 8/8 PASS. |
| 2026-11-01 | **Sơ lược ảnh đại diện trong panel chi tiết phòng.** Widget `CoverPreview` (trong `media_panel.py`) hiển thị ảnh đầu tiên của phòng (co giữ tỉ lệ, bo góc) với badge đếm `📷 N ảnh · ▶ M video` ở góc dưới bên phải; bấm để mở ảnh đầu tiên bằng trình xem mặc định, chuột phải mở thư mục ảnh. Không có ảnh → placeholder hướng dẫn bấm ＋ Thêm. Nằm ngay đầu panel chi tiết (trước ô Giá/Cọc/Diện tích), giúp nhân viên biết ngay căn trông như nào. |
| 2026-10-31 | **Tính năng "Tìm theo yêu cầu khách" (module `request_parser.py` + `request_dialog.py`).** Dán nguyên câu khách hỏi (Zalo/điện thoại) kiểu \"phòng 7tr full nội thất có thang máy, gửi xe, xung quanh P13 hay đường Bình Lợi\" → parser tiếng Việt không dấu tự tách: giá (±10% quanh mốc, khoảng `6-8tr`, `≤`, `≥`, bỏ số cọc), tiện ích nhóm AND-OR (thang máy/nội thất/gửi xe/máy lạnh/wifi...) + trường có cấu trúc (xe điện/pet/khách ngoại), loại phòng, phường `P13`, quận tên/số, **đường** (không strip tiền tố \"đường\"), dấu hiệu lân cân. Hiển thị chip tiêu chí parse live (debounce 250ms). Tìm **4 vòng mở rộng khu vực**: 🏆 Đúng khu vực (đường/phường/quận) → 📍 Lân cận cùng quận (quận suy ra từ phường/đường qua tòa nhà) → 🔀 Giáp ranh quận liền kề (bảng ước tính `NEIGHBORS`) → 🌐 Toàn kho; **tự nới lỏng tiện ích** khi không đủ phòng và báo rõ đã bỏ cái nào; mỗi vòng có nút \"Mở trên bảng phòng\" (nút 🎯 Yêu cầu khách ở thanh lọc trang Phòng). Kiểm thử tự động: test 19 `run_checks.py` (parse + 4 vòng + nới lỏng) và dialog trong `ui_smoke.py`. |
| 2026-10-31 | **Thiết kế lại trang Tòa nhà & Chủ nhà (phong cách Airtable/Linear).** Thẻ tòa mới: mã trong badge xanh, địa chỉ đậm, avatar tròn chữ cái đầu chủ nhà (màu pastel ổn định theo tên) + nút gọi/Zalo tròn, **thanh tỉ lệ OccupancyBar** (trống/cọc/thuê/sắp trống vẽ bo tròn), hàng 5 chỉ số (Tổng/Trống/Cọc-Giữ/Thuê/Sắp trống) + chip chính sách, nút "Xem phòng" bấm được cả thẻ. Tiêu đề khu vực/phường chuyển sang **section header sạch** (title + meta + kẻ mảnh) thay vì khối màu nặng. Toolbar gộp tóm tắt "tòa · phòng · trống". Panel phải: header avatar + 4 chỉ số nhanh + danh sách phòng bo góc + nút sửa tòa. Form thêm/sửa tòa cuộn được, nhóm có badge số. Thêm objectName `BuildingCard`/`IconButton`/`SmallPrimary`/`RoomList` vào design token. |
| 2026-11-01 | **Sửa padding + mở full màn hình.** Trang Phòng/Tòa nhà có khung lề chuẩn 22px hai bên + trên/dưới (nội dung không còn dính mép cửa sổ); bỏ tiêu đề và phụ đề trùng lặp trong trang Phòng (tiêu đề trang đã có sẵn trên thanh trên cùng TopBar, hàng nút thao tác chuyển sang căn phải); app tự **mở full màn hình (showMaximized)** ngay khi khởi động thay vì cửa sổ nhỏ 1440×900 — UI tự scale theo kích thước màn hình thật. Render kiểm chứng 1920×1080 cả 3 trang. |
| 2026-11-01 | **Quản lý ảnh/video phòng lưu cục bộ theo thư mục quy ước** (module `media_manager.py` + panel `media_panel.py`). Quy ước: `<gốc>/<Quận>/<Đường>/<số nhà>-<mã phòng>/<loại phòng> <giá>tr` — VD `Data Image/Bình Thạnh/Nơ Trang Long/5-102-4/studio 8tr` (gốc đổi được trong Cài đặt → "Thư mục ảnh/video"; đường dẫn tương đối = cạnh app). Panel **Ảnh/Video** ngay trong chi tiết phòng: thumbnail nhanh (giải mã thu nhỏ, nạp theo lô 6 file), đếm file/ảnh/video, thêm file (＋ hoặc KÉO THẢ, kể cả thả cả thư mục), **📋 Copy file vào clipboard để dán thẳng vào Zalo/Telegram**, bấm đúp mở trình xem mặc định, 📂 mở thư mục quy ước (tự tạo cây thư mục), 🗑 chuyển vào `_ThungRac` (không mất ngay), 🔄 quét lại. Trùng tên + trùng dung lượng tự bỏ qua; trùng tên khác dung lượng tự đổi tên " (2)". FileSystem là nguồn sự thật — ảnh chép từ điện thoại vào đúng thư mục là app thấy ngay. Test: t20 `run_checks.py` + MediaPanel trong `ui_smoke.py` (20/20 + 8/8 PASS). |
| 2026-11-01 | **Bản build `.exe` mới** (chứa toàn bộ thay đổi từ 2026-10-31: giao diện 2 chế độ Tối/Sáng, trang Tòa nhà redesign, tính năng Tìm theo yêu cầu khách, quản lý ảnh/video phòng theo thư mục quy ước, sửa padding + mở full màn hình). Selftest 12/12 PASS trên môi trường staging; `request_parser`/`request_dialog`/`media_manager`/`media_panel` đã được bundle vào gói. |
| 2026-10-31 | **Thiết kế lại giao diện theo phong cách app quản lý dự án lớn (Linear/Notion).** `theme.py` chuyển thành hệ thống **design token 2 chế độ Sáng/Tối** (mặc định Tối, navy đen + xanh dương) — QSS sinh động từ token, không còn màu hardcode. Sidebar kiểu Linear: nhóm "ĐIỀU HƯỚNG"/"DỮ LIỆU", huy hiệu môi trường, nút chuyển 🌙/☀️ lưu vào cài đặt `ui_theme` và áp dụng ngay lúc chạy (tự repaint biểu đồ/badge/card). TopBar phẳng tinh gọn, bảng dữ liệu, form, panel chi tiết, popup tìm kiếm đều theo token. |
| 2026-10-30 | **Tách 3 môi trường DEV / STAGING / PROD.** Mỗi env có `data/<env>/kho_phong.db`, `logs/`, `cache/` và `config/settings_<env>.json` riêng. Chọn qua `--env dev\|staging\|prod` (ưu tiên) hoặc biến `KHO_APP_ENV`; mặc định `dev` khi chạy nguồn, `prod` khi chạy `.exe`. Thêm huy hiệu env ở thanh trạng thái + tiêu đề; tab Cài đặt hiện env + đường dẫn. Tự migrate dữ liệu cũ (`data/kho_phong.db`, `config/settings.json`) vào env mặc định ở lần chạy đầu. |
| 2026-10-30 | **Build bản Windows (.exe).** Thêm `KhoPhongCanHo.spec` (PyInstaller, onedir) + `build.bat` (đóng gói → chép tài liệu/mẫu → selftest tự kiểm tra, fail thì hủy build). `config.py` aware `sys.frozen`: data/config ghi được cạnh file `.exe`. Thêm chế độ `--selftest` (12 kiểm tra, chạy nền, ghi `selftest_result.txt`). Bản build gồm `KhoPhongCanHo.exe` + `ChayUngDung.bat` / `ChayStaging.bat` / `ChayDev.bat`. |
| 2026-10-30 | **Bản đầu tiên.** Ứng dụng PySide6 + SQLite offline-first: Dashboard 9 KPI, lưới thẻ tòa nhà, bảng phòng ảo hoá, form 8 nhóm, tìm kiếm không dấu + debounce + chỉ mục (< 5ms), chống trùng 5 lớp, import Excel 5 loại có xem trước, xuất Excel giữ công thức COUNTIF/COUNTIFS, hàng đợi đồng bộ Google Sheets (khóa lease `_Lock`, content hash, `App_ID_Map`), khóa ghi `BEGIN IMMEDIATE`. Kèm 18 test backend + 8 test giao diện. |
