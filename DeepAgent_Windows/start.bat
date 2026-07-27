@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title DeepAgent - Bridge Server
cd /d "%~dp0"

echo ============================================
echo   DeepAgent - installer and launcher (Windows)
echo ============================================
echo.

set "PYTHON_CMD="

REM 1) Look for already installed Python (launcher py, then python)
where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        python --version >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD=python"
    )
)

if defined PYTHON_CMD goto :found_python

REM 2) No hay Python: intentar instalarlo solo
echo [DeepAgent] No installed Python found.
echo [DeepAgent] Trying to install it automatically...
echo.

where winget >nul 2>nul
if not errorlevel 1 (
    winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
) else (
    echo [DeepAgent] winget not available on this Windows.
)

REM Look for newly installed python.exe without relying on PATH
REM being updated in this window.
set "PYEXE="
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
)
if defined PYEXE (
    set "PYTHON_CMD=!PYEXE!"
    goto :found_python
)

REM 3) winget no funciono: bajar el instalador oficial
echo.
echo [DeepAgent] Downloading the official installer from python.org...
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '$env:TEMP\python-installer.exe'" 2>nul

if not exist "%TEMP%\python-installer.exe" (
    echo.
    echo [DeepAgent] Could not download or install Python automatically.
    echo [DeepAgent] Install it manually from https://www.python.org/downloads/
    echo [DeepAgent] ^(check "Add python.exe to PATH" in the installer^)
    echo [DeepAgent] and then run start.bat again
    echo.
    pause
    exit /b 1
)

echo [DeepAgent] Instalando Python ^(silencioso, puede tardar un minuto^)...
"%TEMP%\python-installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1
del "%TEMP%\python-installer.exe" >nul 2>nul

for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
)
if defined PYEXE (
    set "PYTHON_CMD=!PYEXE!"
    goto :found_python
)

echo.
echo [DeepAgent] Python was installed but could not locate it automatically.
echo [DeepAgent] Close this window and run start.bat again
pause
exit /b 1

:found_python
echo [DeepAgent] Python OK:
!PYTHON_CMD! --version
echo.
echo [DeepAgent] bridge_server.py no necesita paquetes extra ^(solo libreria estandar de Python^).
echo.
echo [DeepAgent] Iniciando servidor en http://localhost:8765
echo [DeepAgent] Keep this window open while using the DeepAgent extension.
echo [DeepAgent] If a command needs admin permissions: close this
echo             and open it again with right click -^> "Run as administrator"
echo.

!PYTHON_CMD! "%~dp0bridge_server.py"

echo.
echo [DeepAgent] The server was closed.
pause
