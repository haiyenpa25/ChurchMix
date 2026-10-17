@echo off
REM ============================================================
REM  HAINGUYENCODER - first-time setup on a new machine.
REM  Does NOT need Node.js. Installs Node.js + Git (required),
REM  asks about PHP, Composer, Python, clasp, XAMPP, Docker,
REM  fixes PATH, then starts the app.
REM ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\install-tools.ps1" -Interactive -ReportPath "%~dp0data\tools-report.json"
if errorlevel 1 (
  echo.
  echo Setup gap loi. Xem thong bao phia tren.
  pause
  exit /b 1
)

REM Reload PATH from the registry so the freshly installed node.exe is found in this window.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%P"

where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo Chua tim thay Node.js. Hay dong cua so nay, mo lai va chay start.bat.
  pause
  exit /b 1
)

echo.
echo Cai dat xong. Dang mo HAINGUYENCODER...
call "%~dp0start.bat"
