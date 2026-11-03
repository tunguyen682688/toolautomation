# KhoPhongCanHo ${{VERSION}} - Release Notes

## ✨ Tính năng mới
- **⚡ Tạo nhanh từ Zalo**: Copy ảnh phòng → dán → Enter (check tòa nhà + loại phòng + chống trùng)
- **📂 Đổi thư mục lưu trữ**: Cài đặt → Chung → Chọn thư mục mới (copy DB+logs+backup+cache, cũ giữ backup)

## 🐛 Sửa lỗi & Cải tiến
- Tri-state 3 trạng thái (Có/Không/Chưa biết) ổn định
- Tìm kiếm không dấu, chống trùng phòng, import/export Excel
- CRM khách hàng: pipeline, funnel, lý do mất, tỷ lệ chốt
- Dắt căn + điểm sai tư vấn/xử lý (phân tích 7 KPI)

## 📦 Cài đặt
1. Tải `KhoPhongCanHo_${{VERSION}}.exe` từ release này
2. Chạy file → Next → Next → Install
3. Mở từ **Start Menu** → `KhoPhongCanHo`

## ✅ Kiểm thử
- Backend: 24/24 PASS
- UI: 12/12 PASS
- Tri-state: 5/5 PASS
- Selftest: 14/14 PASS

## 🔐 Chữ ký số
File này đã được ký số bằng **SignPath.io** (EV-equivalent certificate) - Windows Smart App Control sẽ chấp nhận tự động.

---
**Yêu cầu**: Windows 10/11 (x64) - Không cần cài Python