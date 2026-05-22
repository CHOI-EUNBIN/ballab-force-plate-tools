@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul 2>&1

echo.
echo  ====================================================
echo    BALLAB - Environment Setup
echo  ====================================================
echo.

echo  [1/3] Checking Python...

set PYTHON=
for %%C in (python py python3) do (
    if not defined PYTHON (
        %%C --version > nul 2>&1
        if not errorlevel 1 ( set PYTHON=%%C )
    )
)

if not defined PYTHON (
    echo.
    echo  [ERROR] Python was not found.
    echo.
    echo  Install Python 3.10 or newer:
    echo    https://www.python.org/downloads/windows/
    echo.
    echo  During installation, check "Add python.exe to PATH".
    echo.
    choice /m "Open the Python download page now?" /c YN /n
    if !errorlevel! equ 1 start https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

for /f "tokens=2" %%V in ('!PYTHON! --version 2^>^&1') do set PY_VER=%%V
for /f "tokens=1,2 delims=." %%A in ("!PY_VER!") do (
    set PY_MAJOR=%%A
    set PY_MINOR=%%B
)

if !PY_MAJOR! lss 3 (
    echo  [ERROR] Python 3.10 or newer is required. Current: !PY_VER!
    pause
    exit /b 1
)
if !PY_MAJOR! equ 3 if !PY_MINOR! lss 10 (
    echo  [ERROR] Python 3.10 or newer is required. Current: !PY_VER!
    pause
    exit /b 1
)

echo  [OK] Python !PY_VER! (!PYTHON!)
echo.

echo  [2/3] Upgrading pip...
!PYTHON! -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo  [WARN] pip upgrade failed. Continuing...
) else (
    echo  [OK] pip
)
echo.

echo  [3/3] Installing packages...
echo        This may take a few minutes depending on the network.
echo.

set INSTALL_OK=1

echo  - Installing PyQt6...
!PYTHON! -m pip install "PyQt6>=6.5.0" --quiet
if errorlevel 1 ( echo  [ERROR] PyQt6 install failed & set INSTALL_OK=0 ) else ( echo  [OK] PyQt6 )

echo  - Installing pyqtgraph...
!PYTHON! -m pip install "pyqtgraph>=0.13.0" --quiet
if errorlevel 1 ( echo  [ERROR] pyqtgraph install failed & set INSTALL_OK=0 ) else ( echo  [OK] pyqtgraph )

echo  - Installing numpy...
!PYTHON! -m pip install "numpy>=1.24.0" --quiet
if errorlevel 1 ( echo  [ERROR] numpy install failed & set INSTALL_OK=0 ) else ( echo  [OK] numpy )

echo  - Installing scipy...
!PYTHON! -m pip install "scipy>=1.10.0" --quiet
if errorlevel 1 ( echo  [ERROR] scipy install failed & set INSTALL_OK=0 ) else ( echo  [OK] scipy )

echo  - Installing openpyxl...
!PYTHON! -m pip install "openpyxl>=3.1.0" --quiet
if errorlevel 1 ( echo  [ERROR] openpyxl install failed & set INSTALL_OK=0 ) else ( echo  [OK] openpyxl )

echo  - Installing qtm_rt...
!PYTHON! -m pip install "qtm-rt>=3.0.0,<4.0.0" --quiet
if errorlevel 1 (
    echo  [WARN] qtm_rt install failed. QTM live connection will be unavailable.
) else (
    echo  [OK] qtm_rt
)
echo.

if !INSTALL_OK! equ 0 (
    echo  ====================================================
    echo    Setup completed with errors.
    echo  ====================================================
    echo.
    echo  Try:
    echo    !PYTHON! -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo  ====================================================
echo    Setup complete.
echo  ====================================================
echo.
echo  Run:
echo    run.bat
echo.
echo  Build exe:
echo    build.bat
echo.
pause
