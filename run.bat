@echo off
chcp 65001 >nul
title HuiNong AI - Smart Agriculture Platform

cd /d "%~dp0"

set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" launcher.py

echo.
echo  Server has stopped. You can close this window.
pause
