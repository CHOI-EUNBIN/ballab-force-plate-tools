@echo off
chcp 65001 > nul 2>&1
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py %*
    if errorlevel 1 (
        echo.
        echo An error occurred while running the app.
        pause
    )
    exit /b %errorlevel%
)

:: Find Python
set PYTHON=
for %%C in (python py python3) do (
    if not defined PYTHON (
        %%C --version > nul 2>&1
        if not errorlevel 1 ( set PYTHON=%%C )
    )
)

if not defined PYTHON (
    echo Python was not found.
    echo Run install.bat first, or install Python and add it to PATH.
    pause
    exit /b 1
)

%PYTHON% main.py %*
if errorlevel 1 (
    echo.
    echo An error occurred while running the app.
    echo Run install.bat first to install the required packages.
    pause
)
