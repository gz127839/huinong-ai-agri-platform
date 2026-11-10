@echo off
chcp 65001 >nul
setlocal
set SRC=%~dp0
set OK=1

echo ==========================================
echo   Sync latest templates to copies
echo ==========================================

copy /Y "%SRC%templates\index.html"          "A:\smart-agri-web\templates\index.html"          >nul 2>&1
if errorlevel 1 (echo [FAIL] A-drive index.html          & set OK=0) else (echo [OK]   A-drive index.html)

copy /Y "%SRC%templates\product_detail.html" "A:\smart-agri-web\templates\product_detail.html" >nul 2>&1
if errorlevel 1 (echo [FAIL] A-drive product_detail.html & set OK=0) else (echo [OK]   A-drive product_detail.html)

if exist "D:\慧农AI智慧农业平台-交付包\05_项目源码\templates" (
  copy /Y "%SRC%templates\index.html"          "D:\慧农AI智慧农业平台-交付包\05_项目源码\templates\index.html"          >nul 2>&1
  if errorlevel 1 (echo [FAIL] package index.html          & set OK=0) else (echo [OK]   package index.html)
  copy /Y "%SRC%templates\product_detail.html" "D:\慧农AI智慧农业平台-交付包\05_项目源码\templates\product_detail.html" >nul 2>&1
  if errorlevel 1 (echo [FAIL] package product_detail.html & set OK=0) else (echo [OK]   package product_detail.html)
) else (
  echo [SKIP] delivery package folder not found
)

echo.
if "%OK%"=="1" (echo All synced.) else (echo Some files failed - close any program holding them and retry.)
echo.
pause
