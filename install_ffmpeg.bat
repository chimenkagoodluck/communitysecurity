@echo off
setlocal EnableExtensions
REM ===========================================================================
REM  FFmpeg installer for CSSA  (per-user, NO admin rights required)
REM  - Skips if ffmpeg is already on PATH
REM  - Download:  curl  -> PowerShell  (whichever works)
REM  - Extract:   tar   -> PowerShell  (whichever works)
REM  - Installs to %LOCALAPPDATA%\ffmpeg and adds it to the USER PATH safely
REM  - Verifies and fails loudly with a clear message at every step
REM ===========================================================================

echo ============================================================
echo  FFmpeg installer for CSSA  (no admin rights required)
echo ============================================================
echo.

REM --- 0. Already available on PATH? -----------------------------------------
where ffmpeg >nul 2>nul
if not errorlevel 1 (
    echo [OK] ffmpeg is already installed and on PATH:
    where ffmpeg
    echo Nothing to do.
    goto :success
)

set "DEST=%LOCALAPPDATA%\ffmpeg"
set "BIN=%DEST%\bin"
set "ZIP=%TEMP%\ffmpeg-cssa.zip"
set "UNZIP=%TEMP%\ffmpeg-cssa-unzip"
set "URL=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

REM --- 1. Installed by a previous run of this script? -------------------------
if exist "%BIN%\ffmpeg.exe" (
    echo [OK] Found existing install at "%BIN%".
    goto :addpath
)

REM --- 2. Download -----------------------------------------------------------
echo [1/4] Downloading FFmpeg ...
echo       %URL%
if exist "%ZIP%" del /f /q "%ZIP%" >nul 2>nul

set "DL_OK="
where curl >nul 2>nul
if not errorlevel 1 (
    curl -L --fail --retry 3 --retry-delay 2 -o "%ZIP%" "%URL%"
    if not errorlevel 1 set "DL_OK=1"
)
if not defined DL_OK (
    echo       curl unavailable or failed - trying PowerShell ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try{Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing -ErrorAction Stop}catch{Write-Host $_.Exception.Message; exit 1}"
    if not errorlevel 1 set "DL_OK=1"
)
if not defined DL_OK (
    echo [ERROR] Download failed. Check the internet connection / firewall and retry.
    goto :fail
)

REM verify the zip is a real, non-trivial file (catches HTML error pages)
set "ZSIZE="
for %%A in ("%ZIP%") do set "ZSIZE=%%~zA"
if not defined ZSIZE (
    echo [ERROR] Download produced no file.
    goto :fail
)
if %ZSIZE% LSS 1000000 (
    echo [ERROR] Downloaded file is only %ZSIZE% bytes - looks incomplete/corrupt. Retry.
    goto :fail
)

REM --- 3. Extract ------------------------------------------------------------
echo [2/4] Extracting ...
if exist "%UNZIP%" rmdir /s /q "%UNZIP%" >nul 2>nul
mkdir "%UNZIP%" >nul 2>nul

set "EX_OK="
where tar >nul 2>nul
if not errorlevel 1 (
    tar -xf "%ZIP%" -C "%UNZIP%"
    if not errorlevel 1 set "EX_OK=1"
)
if not defined EX_OK (
    echo       tar unavailable or failed - trying PowerShell ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try{Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%UNZIP%' -Force -ErrorAction Stop}catch{Write-Host $_.Exception.Message; exit 1}"
    if not errorlevel 1 set "EX_OK=1"
)
if not defined EX_OK (
    echo [ERROR] Extraction failed.
    goto :fail
)

REM locate the bin folder inside the extracted build (folder name has a version)
set "SRCBIN="
for /d %%D in ("%UNZIP%\ffmpeg-*") do (
    if exist "%%D\bin\ffmpeg.exe" set "SRCBIN=%%D\bin"
)
if not defined SRCBIN if exist "%UNZIP%\bin\ffmpeg.exe" set "SRCBIN=%UNZIP%\bin"
if not defined SRCBIN (
    echo [ERROR] Could not find ffmpeg.exe inside the archive.
    goto :fail
)

REM --- 4. Install to a stable folder ----------------------------------------
echo [3/4] Installing to "%BIN%" ...
if not exist "%DEST%" mkdir "%DEST%" >nul 2>nul
if not exist "%BIN%"  mkdir "%BIN%"  >nul 2>nul
xcopy /y /q "%SRCBIN%\*" "%BIN%\" >nul
if not exist "%BIN%\ffmpeg.exe" (
    echo [ERROR] Copy failed - "%BIN%\ffmpeg.exe" is not present.
    goto :fail
)

:addpath
echo [4/4] Adding "%BIN%" to your user PATH ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$b='%BIN%'; $p=[Environment]::GetEnvironmentVariable('Path','User'); if([string]::IsNullOrEmpty($p)){$new=$b}else{ if(($p -split ';') -contains $b){Write-Host 'Already on PATH.'; exit 0}; $new=$p.TrimEnd(';')+';'+$b }; [Environment]::SetEnvironmentVariable('Path',$new,'User'); Write-Host 'PATH updated.'"
if errorlevel 1 (
    echo [WARN] Could not update PATH automatically. Add this folder manually:
    echo        %BIN%
)

REM make ffmpeg usable in THIS window too (current session PATH)
set "PATH=%PATH%;%BIN%"

REM --- cleanup ---------------------------------------------------------------
if exist "%ZIP%"   del /f /q "%ZIP%"     >nul 2>nul
if exist "%UNZIP%" rmdir /s /q "%UNZIP%" >nul 2>nul

REM --- verify ----------------------------------------------------------------
echo.
echo Verifying ...
"%BIN%\ffmpeg.exe" -version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] ffmpeg.exe did not run. Installation incomplete.
    goto :fail
)
echo [OK] Installed version:
"%BIN%\ffmpeg.exe" -version 2>&1 | findstr /b /c:"ffmpeg version"

:success
echo.
echo ============================================================
echo  DONE. ffmpeg is installed.
echo  IMPORTANT: close this window and open a NEW terminal
echo  (or restart the CSSA server) so the PATH change takes effect.
echo ============================================================
endlocal
exit /b 0

:fail
echo.
echo ============================================================
echo  INSTALL FAILED - see the message above.
echo  Manual fallback: download "ffmpeg-release-essentials.zip"
echo  from https://www.gyan.dev/ffmpeg/builds/ , unzip it, and add
echo  its \bin folder to PATH.
echo ============================================================
endlocal
exit /b 1
