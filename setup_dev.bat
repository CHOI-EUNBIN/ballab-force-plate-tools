@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul 2>&1
cd /d "%~dp0"

echo.
echo  === BALLAB Development Setup ===
echo.

set PYTHON=
for %%C in (python py python3) do (
    if not defined PYTHON (
        %%C --version > nul 2>&1
        if not errorlevel 1 ( set PYTHON=%%C )
    )
)

if not defined PYTHON (
    echo [ERROR] Python was not found.
    echo Install Python 3.10 or newer and check "Add python.exe to PATH".
    echo https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating .venv...
    !PYTHON! -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv.
        pause
        exit /b 1
    )
) else (
    echo [1/3] .venv already exists.
)

echo [2/3] Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    pause
    exit /b 1
)

echo [3/3] Installing required packages...
".venv\Scripts\python.exe" -m pip install "PyQt6>=6.5.0" "pyqtgraph>=0.13.0" "numpy>=1.24.0" "scipy>=1.10.0" "pyinstaller>=6.0.0" "openpyxl>=3.1.0"
if errorlevel 1 (
    echo [ERROR] Failed to install required packages.
    pause
    exit /b 1
)

echo.
echo Installing optional QTM package...
".venv\Scripts\python.exe" -m pip install "qtm-rt>=3.0.0,<4.0.0"
if errorlevel 1 (
    echo [WARN] qtm-rt install failed. The app can still run, but QTM live connection will be unavailable.
) else (
    echo [OK] qtm-rt
)

echo.
echo [DONE] Development environment is ready.
echo Run the app with:
echo   run_dev.bat
echo.
pause
