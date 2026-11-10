@echo off
chcp 65001 >nul
title HuiNong AI - Smart Agriculture Platform

cd /d "%~dp0"

rem ---- 1) locate a Python interpreter ----
rem Prefer a bundled runtime when present, otherwise fall back to PATH.
set "PY="
if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not defined PY if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not defined PY (
    where python >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  [ERROR] Python 3.10 - 3.13 was not found.
        echo.
        echo  1. Install Python from https://www.python.org/downloads/
        echo  2. During setup, tick "Add python.exe to PATH"
        echo  3. Double-click run.bat again
        echo.
        pause
        exit /b 1
    )
    set "PY=python"
)

rem ---- 2) verify required packages ----
"%PY%" -c "import flask, PIL, numpy" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Required Python packages are missing.
    echo.
    echo  Open a terminal in this folder and run:
    echo      pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

rem ---- 3) start the platform ----
echo  Starting HuiNong AI ... a browser window will open shortly.
echo  Close this window to stop the server.
echo.
"%PY%" launcher.py

echo.
echo  Server has stopped. You can close this window.
pause
