@echo off
setlocal
cd /d "%~dp0"
title ChurchMix - Signal Monitor

echo ====================================================================
echo                    CHURCHMIX SIGNAL MONITOR
echo ====================================================================
echo  [INFO] Default: isolated X32 simulator and READ-ONLY mode.
echo  [INFO] Dashboard: http://127.0.0.1:8080
echo  [INFO] Demo signals are not measurements from real hardware.
echo ====================================================================
echo.

set "PY_CMD="
set "PY_ARGS="

rem Prefer installed Python over the Windows Store alias on PATH.
for %%V in (314 313 312 311) do (
    if not defined PY_CMD if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
    if not defined PY_CMD if exist "C:\Python%%V\python.exe" set "PY_CMD=C:\Python%%V\python.exe"
)

if not defined PY_CMD (
    python -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    py -3 -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul
    if not errorlevel 1 (
        set "PY_CMD=py"
        set "PY_ARGS=-3"
    )
)

if not defined PY_CMD (
    echo [ERROR] Python 3.11 or newer was not found. Install Python from python.org.
    pause
    exit /b 1
)

"%PY_CMD%" %PY_ARGS% -c "import uvicorn, fastapi, numpy, scipy, sounddevice" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Missing dependencies. Run this command first:
    echo "%PY_CMD%" %PY_ARGS% -m pip install -r requirements.txt
    pause
    exit /b 1
)

start "" http://127.0.0.1:8080
"%PY_CMD%" %PY_ARGS% -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8080 --log-level info

pause
