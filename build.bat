@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  === BALLAB Build ===
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
if exist "dist\BALLAB.exe" del /f /q "dist\BALLAB.exe"
if exist "build\BALLAB" rd /s /q "build\BALLAB"

echo [2/2] Building...
!PYTHON! -m PyInstaller --clean BALLAB.spec

if exist "dist\BALLAB.exe" (
    echo.
    echo [DONE] dist\BALLAB.exe
) else (
    echo.
    echo [FAILED] See error above.
)
echo.
cmd /k
