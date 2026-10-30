@echo off
chcp 65001 >nul
title BUILD - Kho Phong Can Ho
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo ==========================================================
echo  DONG GOI BAN BUILD WINDOWS (PyInstaller - onedir)
echo  Thu muc ket qua: dist\KhoPhongCanHo\
echo ==========================================================

where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Hay cai Python 3.10+ tu python.org
    pause
    exit /b 1
)

echo.
echo [1/4] Cai / nang cap PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [LOI] Khong cai duoc PyInstaller
    pause
    exit /b 1
)

echo.
echo [2/4] Dong goi (chay PyInstaller)...
python -m PyInstaller --clean --noconfirm KhoPhongCanHo.spec
if errorlevel 1 (
    echo [LOI] Loi khi dong goi - xem ban doan log o tren
    pause
    exit /b 1
)

echo.
echo [3/4] Bo sung tai lieu + file mau vao ban build...
if not exist "dist\KhoPhongCanHo\du_lieu_mau" mkdir "dist\KhoPhongCanHo\du_lieu_mau"
copy /Y "samples\*.xlsx" "dist\KhoPhongCanHo\du_lieu_mau\" >nul
copy /Y "README.md" "dist\KhoPhongCanHo\Huong_Dan.md" >nul
copy /Y "requirements.txt" "dist\KhoPhongCanHo\" >nul

rem cac file khoi dong theo moi truong (moi truong -> data + settings rieng biet)
(
echo @echo off
echo cd /d "%%~dp0"
echo start "" "KhoPhongCanHo.exe" --env prod
) > "dist\KhoPhongCanHo\ChayUngDung.bat"
(
echo @echo off
echo cd /d "%%~dp0"
echo start "" "KhoPhongCanHo.exe" --env staging
) > "dist\KhoPhongCanHo\ChayStaging.bat"
(
echo @echo off
echo cd /d "%%~dp0"
echo start "" "KhoPhongCanHo.exe" --env dev
) > "dist\KhoPhongCanHo\ChayDev.bat"

echo.
echo [4/4] Kiem tra ban build (selftest)...
set QT_QPA_PLATFORM=offscreen
"dist\KhoPhongCanHo\KhoPhongCanHo.exe" --selftest --env staging
set XT=%ERRORLEVEL%
set QT_QPA_PLATFORM=
if exist "dist\KhoPhongCanHo\data\staging\selftest_result.txt" (
    echo.
    type "dist\KhoPhongCanHo\data\staging\selftest_result.txt"
)
if not "%XT%"=="0" (
    echo [LOI] Selftest that bai - dung ban build nay!
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo  BUILD THANH CONG
echo  + San pham:     dist\KhoPhongCanHo\
echo  + Moi truong (moi cai database + cau hinh RIENG, khong anh huong nhau):
echo      ChayUngDung.bat  -> PROD   (du lieu that, mac dinh khi bam .exe)
echo      ChayStaging.bat  -> STAGING (kiem truoc khi dua vao su dung)
echo      ChayDev.bat      -> DEV     (phat trien)
echo    hoac tuong ung:  KhoPhongCanHo.exe --env prod|staging|dev
echo  + Copy thu muc dist\KhoPhongCanHo\ sang may khac la dung duoc
echo    (may do khong can cai Python)
echo ==========================================================
pause
