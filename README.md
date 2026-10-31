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
| [5. Bộ kiểm thử](#5-bộ-kiểm-thử-chạy-được-ngay-không-cần-mạng) | 18 backend + 8 giao diện + selftest + 10 tình huống bắt buộc |
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
├── edit_form.py          ← form 8 nhóm + kiểm tra trùng debounce + Lưu / Lưu & thêm tiếp
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
└── tests/                ← bộ kiểm thử (18 + 8 tình huống giao diện)
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

### 5.3. Selftest — kiểm tra nhanh 12 đầu việc (có ở cả nguồn lẫn bản build)

```powershell
python main.py --selftest                  # chạy từ nguồn
# hoặc trên bản build:
dist\KhoPhongCanHo\KhoPhongCanHo.exe --selftest --env staging
```

Chạy nền (không hiện cửa sổ), dùng **DB tạm** nên không đụng dữ liệu thật. Tự làm:
nhập Excel mẫu → mở Dashboard/Tòa nhà/Bảng phòng → tìm kiếm không dấu → xuất Excel →
kiểm tra env được tách riêng. Exit code `0` = tốt, `1` = lỗi; chi tiết ghi vào
`data/<env>/selftest_result.txt`. Đây là bước cuối của `build.bat` (build fail nếu selftest fail).

### 5.4. 10 tình huống kiểm thử bắt buộc (đối chiếu với đặc tả)

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
(**12 kiểm tra**: nhập Excel, mở các trang, tìm kiếm, xuất Excel, xác minh env).
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
xác minh env tách riêng (**12 kiểm tra**). Exit code `0` = tốt, `1` = lỗi;
chi tiết ghi vào `data\<env>\selftest_result.txt`.
`build.bat` tự chạy selftest ở env **staging** và hủy build nếu fail.

---

## 9. Lịch sử thay đổi

| Ngày | Thay đổi |
|---|---|
| 2026-10-31 | **Tính năng "Tìm theo yêu cầu khách" (module `request_parser.py` + `request_dialog.py`).** Dán nguyên câu khách hỏi (Zalo/điện thoại) kiểu \"phòng 7tr full nội thất có thang máy, gửi xe, xung quanh P13 hay đường Bình Lợi\" → parser tiếng Việt không dấu tự tách: giá (±10% quanh mốc, khoảng `6-8tr`, `≤`, `≥`, bỏ số cọc), tiện ích nhóm AND-OR (thang máy/nội thất/gửi xe/máy lạnh/wifi...) + trường có cấu trúc (xe điện/pet/khách ngoại), loại phòng, phường `P13`, quận tên/số, **đường** (không strip tiền tố \"đường\"), dấu hiệu lân cân. Hiển thị chip tiêu chí parse live (debounce 250ms). Tìm **4 vòng mở rộng khu vực**: 🏆 Đúng khu vực (đường/phường/quận) → 📍 Lân cận cùng quận (quận suy ra từ phường/đường qua tòa nhà) → 🔀 Giáp ranh quận liền kề (bảng ước tính `NEIGHBORS`) → 🌐 Toàn kho; **tự nới lỏng tiện ích** khi không đủ phòng và báo rõ đã bỏ cái nào; mỗi vòng có nút \"Mở trên bảng phòng\" (nút 🎯 Yêu cầu khách ở thanh lọc trang Phòng). Kiểm thử tự động: test 19 `run_checks.py` (parse + 4 vòng + nới lỏng) và dialog trong `ui_smoke.py`. |
| 2026-10-31 | **Thiết kế lại trang Tòa nhà & Chủ nhà (phong cách Airtable/Linear).** Thẻ tòa mới: mã trong badge xanh, địa chỉ đậm, avatar tròn chữ cái đầu chủ nhà (màu pastel ổn định theo tên) + nút gọi/Zalo tròn, **thanh tỉ lệ OccupancyBar** (trống/cọc/thuê/sắp trống vẽ bo tròn), hàng 5 chỉ số (Tổng/Trống/Cọc-Giữ/Thuê/Sắp trống) + chip chính sách, nút "Xem phòng" bấm được cả thẻ. Tiêu đề khu vực/phường chuyển sang **section header sạch** (title + meta + kẻ mảnh) thay vì khối màu nặng. Toolbar gộp tóm tắt "tòa · phòng · trống". Panel phải: header avatar + 4 chỉ số nhanh + danh sách phòng bo góc + nút sửa tòa. Form thêm/sửa tòa cuộn được, nhóm có badge số. Thêm objectName `BuildingCard`/`IconButton`/`SmallPrimary`/`RoomList` vào design token. |
| 2026-10-31 | **Thiết kế lại giao diện theo phong cách app quản lý dự án lớn (Linear/Notion).** `theme.py` chuyển thành hệ thống **design token 2 chế độ Sáng/Tối** (mặc định Tối, navy đen + xanh dương) — QSS sinh động từ token, không còn màu hardcode. Sidebar kiểu Linear: nhóm "ĐIỀU HƯỚNG"/"DỮ LIỆU", huy hiệu môi trường, nút chuyển 🌙/☀️ lưu vào cài đặt `ui_theme` và áp dụng ngay lúc chạy (tự repaint biểu đồ/badge/card). TopBar phẳng tinh gọn, bảng dữ liệu, form, panel chi tiết, popup tìm kiếm đều theo token. |
| 2026-10-30 | **Tách 3 môi trường DEV / STAGING / PROD.** Mỗi env có `data/<env>/kho_phong.db`, `logs/`, `cache/` và `config/settings_<env>.json` riêng. Chọn qua `--env dev\|staging\|prod` (ưu tiên) hoặc biến `KHO_APP_ENV`; mặc định `dev` khi chạy nguồn, `prod` khi chạy `.exe`. Thêm huy hiệu env ở thanh trạng thái + tiêu đề; tab Cài đặt hiện env + đường dẫn. Tự migrate dữ liệu cũ (`data/kho_phong.db`, `config/settings.json`) vào env mặc định ở lần chạy đầu. |
| 2026-10-30 | **Build bản Windows (.exe).** Thêm `KhoPhongCanHo.spec` (PyInstaller, onedir) + `build.bat` (đóng gói → chép tài liệu/mẫu → selftest tự kiểm tra, fail thì hủy build). `config.py` aware `sys.frozen`: data/config ghi được cạnh file `.exe`. Thêm chế độ `--selftest` (12 kiểm tra, chạy nền, ghi `selftest_result.txt`). Bản build gồm `KhoPhongCanHo.exe` + `ChayUngDung.bat` / `ChayStaging.bat` / `ChayDev.bat`. |
| 2026-10-30 | **Bản đầu tiên.** Ứng dụng PySide6 + SQLite offline-first: Dashboard 9 KPI, lưới thẻ tòa nhà, bảng phòng ảo hoá, form 8 nhóm, tìm kiếm không dấu + debounce + chỉ mục (< 5ms), chống trùng 5 lớp, import Excel 5 loại có xem trước, xuất Excel giữ công thức COUNTIF/COUNTIFS, hàng đợi đồng bộ Google Sheets (khóa lease `_Lock`, content hash, `App_ID_Map`), khóa ghi `BEGIN IMMEDIATE`. Kèm 18 test backend + 8 test giao diện. |
