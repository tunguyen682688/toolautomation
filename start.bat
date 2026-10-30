@echo off
chcp 65001 >nul
title Kho Phong Can Ho
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Hay cai Python 3.10+ tu python.org
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Dang tao moi truong ao...
    python -m venv .venv
    if errorlevel 1 (
        echo [LOI] Khong tao duoc venv. Thu chay: pip install -r requirements.txt
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [LOI] Loi khi cai thu vien. Kiem tra lai mang / requirements.txt
        pause
        exit /b 1
    )
)

echo Dang khoi dong ung dung...
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
    echo.
    echo [LOI] Ung dung dung loi. Xem log: data\logs\app.log
    pause
)
