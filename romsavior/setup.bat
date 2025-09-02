@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM =========================
REM Myrient ROM Manager - Windows One-Click Setup
REM - Creates venv
REM - Installs deps
REM - Generates run script
REM - Places Desktop shortcut
REM =========================

REM --- Resolve project directory (this script's folder) ---
set "PROJECT_DIR=%~dp0"
REM Trim trailing backslash if present
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "VENV_DIR=%PROJECT_DIR%\venv"

echo:
echo === Myrient ROM Manager - Windows Setup ===
echo Project directory: "%PROJECT_DIR%"
echo Venv directory:    "%VENV_DIR%"
echo:

REM --- Check Python launcher ---
where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python launcher "py" not found on PATH.
  echo Install Python from https://www.python.org/downloads/ and re-run this script.
  pause
  exit /b 1
)

REM --- Create venv if missing ---
if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [*] Creating virtual environment...
  py -3 -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
  )
) else (
  echo [*] Using existing virtual environment.
)

REM --- Upgrade pip & install packages ---
echo [*] Installing Python packages (this may take a minute)...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip >nul
if errorlevel 1 echo [WARN] Could not upgrade pip (continuing)...
"%VENV_DIR%\Scripts\pip.exe" install PySide6 requests beautifulsoup4 pyinstaller
if errorlevel 1 (
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

REM --- Write run script that launches via venv ---
set "RUN_BAT=%PROJECT_DIR%\run_rom_manager.bat"
echo [*] Writing run launcher: "%RUN_BAT%"
> "%RUN_BAT%" (
  echo @echo off
  echo setlocal
  echo set "PROJECT_DIR=%%~dp0"
  echo if "%%PROJECT_DIR:~-1%%"=="\" set "PROJECT_DIR=%%PROJECT_DIR:~0,-1%%"
  echo call "%%PROJECT_DIR%%\venv\Scripts\activate.bat"
  echo if exist "%%PROJECT_DIR%%\main.py" (
  echo   python "%%PROJECT_DIR%%\main.py"
  echo ) else (
  echo   echo [ERROR] main.py not found next to this script.
  echo   pause
  echo )
  echo endlocal
)

REM --- Create Desktop shortcut to the run script (via PowerShell) ---
echo [*] Creating Desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$proj = (Get-Item -LiteralPath '%PROJECT_DIR%').FullName; " ^
  "$desk = [Environment]::GetFolderPath('Desktop'); " ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$lnk = $ws.CreateShortcut((Join-Path $desk 'Myrient ROM Manager.lnk')); " ^
  "$lnk.TargetPath = (Join-Path $proj 'run_rom_manager.bat'); " ^
  "$lnk.WorkingDirectory = $proj; " ^
  "$lnk.IconLocation = $env:SystemRoot + '\System32\shell32.dll, 2'; " ^
  "$lnk.Save();"

if errorlevel 1 (
  echo [WARN] Could not create Desktop shortcut automatically.
  echo        You can run the app with: "%RUN_BAT%"
) else (
  echo [OK] Desktop shortcut created: Myrient ROM Manager.lnk
)

REM --- Check external tools and warn if missing ---
echo:
echo === Checking external tools on PATH ===
where aria2c >nul 2>&1
if errorlevel 1 (
  echo [WARN] aria2c not found. Install aria2 (recommended) or switch to wget in Profiles.
) else (
  echo [OK]   aria2c found.
)

where 7z >nul 2>&1
if errorlevel 1 (
  where unzip >nul 2>&1
  if errorlevel 1 (
    echo [WARN] 7z / unzip not found. Install 7-Zip or Info-ZIP for archive extraction.
  ) else (
    echo [OK]   unzip found.
  )
) else (
  echo [OK]   7z found.
)

where chdman >nul 2>&1
if errorlevel 1 (
  echo [WARN] chdman not found. Install MAME tools and ensure chdman.exe is on PATH.
) else (
  echo [OK]   chdman found.
)

echo:
echo === Done! ===
echo - Double-click the Desktop shortcut "Myrient ROM Manager".
echo - Or run: "%RUN_BAT%"
echo:
pause
endlocal
