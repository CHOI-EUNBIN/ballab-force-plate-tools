@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  === Balancelab Build ===
echo.

set PYTHON=
if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    for %%C in (python py python3) do (
        if not defined PYTHON (
            %%C --version > nul 2>&1
            if not errorlevel 1 ( set PYTHON=%%C )
        )
    )
)

if not defined PYTHON (
    echo [ERROR] Python was not found. Run setup_dev.bat first.
    cmd /k
    exit /b 1
)

!PYTHON! -m pyinstaller --version > nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    !PYTHON! -m pip install "pyinstaller>=6.0.0"
    if errorlevel 1 (
        echo [ERROR] PyInstaller install failed
        cmd /k
        exit /b 1
    )
)

echo [1/2] Cleaning old build...
if exist "dist\Balancelab.exe" del /f /q "dist\Balancelab.exe"
if exist "build\Balancelab" rd /s /q "build\Balancelab"

echo [2/2] Building...
!PYTHON! -m PyInstaller --clean Balancelab.spec

if exist "dist\Balancelab.exe" (
    echo.
    echo [DONE] dist\Balancelab.exe
) else (
    echo.
    echo [FAILED] See error above.
)
echo.
cmd /k
