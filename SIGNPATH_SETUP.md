# Cấu hình GitHub Secrets cho SignPath.io
# Vào: Settings → Secrets and variables → Actions → New repository secret

# 1. SIGNPATH_ORG
# Tên organization trên SignPath.io (ví dụ: tunguyen682688)
# Lấy tại: https://app.signpath.io/organizations

# 2. SIGNPATH_PROJECT
# Tên project trên SignPath.io (ví dụ: toolautomation)
# Lấy tại: https://app.signpath.io/organizations/<org>/projects

# 3. SIGNPATH_POLICY
# Tên signing policy (ví dụ: release)
# Lấy tại: https://app.signpath.io/organizations/<org>/projects/<project>/policies

# ---
# HƯỚNG DẪN SETUP SIGNPATH.IO:
# 1. Đăng ký https://signpath.io → Free for Open Source
# 2. Tạo Organization → Add repository: tunguyen682688/toolautomation
# 3. Tạo Project → Chọn "Windows Executable" → Policy: "Release"
# 4. Copy 3 giá trị trên → Add vào GitHub Secrets
# 5. Push tag v1.0.1 → Workflow tự chạy → Build → Sign → Release