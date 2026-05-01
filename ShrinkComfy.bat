@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title ShrinkComfy
color 1E

:: ── First-run setup ───────────────────────────────────────────────────────────
if not exist "_app\.venv\Scripts\python.exe" (
    mode con cols=62 lines=34
    cls
    echo.
    echo  +========================================================+
    echo  ^|                 S H R I N K C O M F Y                  ^|
    echo  ^|                    First-time Setup                    ^|
    echo  +========================================================+
    echo.
    echo  This installer will prepare ShrinkComfy on your machine.
    echo.
    echo    - Nothing is installed outside this folder
    echo    - To uninstall: simply delete this folder
    echo    - One-time download of approximately 27 MB
    echo.
    echo  Packages that will be downloaded:
    echo.
    echo    Pillow        Image processing ^& compression
    echo    sv_ttk        Modern UI theme
    echo    darkdetect    Dark / light mode detection
    echo    pywinstyles   Native Windows visual effects
    echo.
    echo  +--------------------------------------------------------+
    echo.
    set /p "CONFIRM=    Proceed with download and setup?  [Y/N]  "
    if /i not "!CONFIRM!"=="Y" (
        echo.
        echo  Setup cancelled. Run this file again whenever ready.
        echo.
        pause >nul
        exit /b 0
    )

    cls
    echo.
    echo  +========================================================+
    echo  ^|          S H R I N K C O M F Y  ^|  Installing          ^|
    echo  +========================================================+
    echo.
    echo  [ 1 / 3 ]  Checking for Python...
    echo.
    where python >nul 2>nul
    if errorlevel 1 (
        echo  [ERROR] Python not found in PATH.
        echo.
        echo    Get it at : https://www.python.org/downloads/
        echo    During installation, check "Add Python to PATH".
        echo.
        pause >nul
        exit /b 1
    )
    echo             Python found.   [ OK ]
    echo.
    echo  ----------------------------------------------------------
    echo.
    echo  [ 2 / 3 ]  Creating isolated environment...
    echo.
    cd _app
    python -m venv .venv >nul 2>nul
    if errorlevel 1 (
        echo  [ERROR] Could not create virtual environment.
        cd ..
        pause >nul
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    echo             Environment ready.   [ OK ]
    echo.
    echo  ----------------------------------------------------------
    echo.
    echo  [ 3 / 3 ]  Downloading packages...
    echo.
    echo    [          ]   0%%   Pillow          image processing...
    ".venv\Scripts\python.exe" -m pip install Pillow --quiet
    echo    [##        ]  25%%   sv_ttk          modern UI theme...
    ".venv\Scripts\python.exe" -m pip install sv_ttk --quiet
    echo    [#####     ]  50%%   darkdetect      dark/light mode...
    ".venv\Scripts\python.exe" -m pip install darkdetect --quiet
    echo    [#######   ]  75%%   pywinstyles     Windows effects...
    ".venv\Scripts\python.exe" -m pip install pywinstyles --quiet
    echo    [##########] 100%%   All packages installed.
    echo.
    cd ..

    if exist ".gitignore"  del /f /q ".gitignore"
    if exist "README.md"   del /f /q "README.md"
    if exist "README.png"  del /f /q "README.png"
    if exist "_readme"     rd  /s /q "_readme"
    if exist ".git"        rd  /s /q ".git"

    echo  ----------------------------------------------------------
    echo.
    echo  +========================================================+
    echo  ^|                  ShrinkComfy is ready!                  ^|
    echo  +========================================================+
    echo.
    echo  Compressed images will be saved here by default:
    echo.
    echo    %~dp0output\
    echo.
    echo  You can pick a different folder at any time in the app.
    echo  Use ShrinkComfy.bat next time to start the application.
    echo.
    echo  Press any key to launch ShrinkComfy...
    pause >nul
)

:: ── Launch ────────────────────────────────────────────────────────────────────
if not exist "output" mkdir output
start "" "_app\.venv\Scripts\pythonw.exe" "_app\gui.py"
endlocal
