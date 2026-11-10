@echo off
cd /d "%~dp0"
"%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" launcher.py > "%~dp0startup.log" 2>&1
