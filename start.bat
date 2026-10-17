@echo off
REM HAINGUYENCODER launcher - double-click to start; the browser opens once the server is up.
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo Khong tim thay Node.js tren may nay. Dang chay setup.bat de cai dat...
  call "%~dp0setup.bat"
  exit /b
)
title HAINGUYENCODER - http://127.0.0.1:4590
echo HAINGUYENCODER: http://127.0.0.1:4590   (dong cua so nay de tat)
start "" /min cmd /c "timeout /t 2 /nobreak >nul & start "" http://127.0.0.1:4590"
node server.js
pause
