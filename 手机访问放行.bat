@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" _fw_allow.py 5000
echo.
echo If you saw a permission error above:
echo   Right-click this file, then choose "Run as administrator".
echo.
pause
