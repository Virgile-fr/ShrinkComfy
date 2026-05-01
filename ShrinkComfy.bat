@echo off
setlocal
cd /d "%~dp0"
title ShrinkComfy

:: ── First-run setup ───────────────────────────────────────────────────────────
if not exist "_app\.venv\Scripts\python.exe" (
    echo.
    echo  +--------------------------------------+
    echo  ^|          ShrinkComfy  Setup          ^|
    echo  +--------------------------------------+
    echo.
    echo  ^> Checking for Python...
    where python >nul 2>nul
    if errorlevel 1 (
        echo.
        echo  [ERROR] Python is not installed or not found in PATH.
        echo.
        echo         Download it from: https://www.python.org/downloads/
        echo         Check "Add Python to PATH" during installation.
        echo.
        echo  Press any key to continue...
pause >nul
        exit /b 1
    )
    echo    Found.
    echo.
    echo  ^> Installing dependencies ^(~20 MB^)...
    cd _app
    python -m venv .venv
    if errorlevel 1 (
        echo  [ERROR] Could not create virtual environment.
        cd ..
        echo  Press any key to continue...
pause >nul
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    ".venv\Scripts\python.exe" -m pip install Pillow sv_ttk darkdetect pywinstyles --quiet
    if errorlevel 1 (
        echo  [ERROR] Dependency installation failed.
        cd ..
        echo  Press any key to continue...
pause >nul
        exit /b 1
    )
    cd ..
    echo    Done.
    echo.

    :: ── Clean up repo files ───────────────────────────────────────────────────
    if exist ".gitignore"  del /f /q ".gitignore"
    if exist "README.md"   del /f /q "README.md"
    if exist "README.png"  del /f /q "README.png"
    if exist "_readme"     rd  /s /q "_readme"
    if exist ".git"        rd  /s /q ".git"

    echo  +--------------------------------------+
    echo  ^|       ShrinkComfy is ready!          ^|
    echo  +--------------------------------------+
    echo.
    echo  Press any key to continue...
pause >nul
)

:: ── Launch ────────────────────────────────────────────────────────────────────
if not exist "output" mkdir output
start "" "_app\.venv\Scripts\pythonw.exe" "_app\gui.py"
endlocal
