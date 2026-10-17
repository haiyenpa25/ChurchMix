@echo off
REM Dong goi HAINGUYENCODER thanh file .zip (dat canh thu muc HAINGUYENCODER).
REM Them tham so -Lite de bo antigravity-awesome-skills (~380 MB):  pack.bat -Lite
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pack.ps1" %*
pause
