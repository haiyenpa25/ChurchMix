# PowerShell script to register ChurchMix as a Windows Background Task / Service
param(
    [string]$PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    [string]$AppDir = "C:\xampp\htdocs\ChurchMix"
)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " ChurchMix Windows Service Installer     " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

if (-not (Test-Path $PythonExe)) {
    Write-Error "Python executable not found at: $PythonExe"
    exit 1
}

# Create Scheduled Task configured to run at startup without login prompt
$TaskName = "ChurchMix_X32_Engineer"
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "-m uvicorn apps.api.main:app --host 127.0.0.1 --port 8080" -WorkingDirectory $AppDir
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "ChurchMix Behringer X32 AI Sound Engineer Server" -Force

Write-Host "Successfully registered ChurchMix service as task: $TaskName" -ForegroundColor Green
Write-Host "Starting ChurchMix now..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName $TaskName
Write-Host "ChurchMix is active on http://127.0.0.1:8080" -ForegroundColor Green
