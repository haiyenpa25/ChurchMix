<#
.SYNOPSIS
  Đóng gói HAINGUYENCODER thành 1 file .zip sạch để chép sang máy khác.

.DESCRIPTION
  Bỏ qua: .git (của các repo community-skills), data\ (danh sách dự án + cài đặt
  riêng của máy này), node_modules, file tạm. Mặc định giữ đủ community-skills.
  -Lite bỏ thêm community-skills\antigravity-awesome-skills (~380 MB, ~26.000 file).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File pack.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File pack.ps1 -Lite
#>
[CmdletBinding()]
param(
  [switch]$Lite,
  [string]$OutDir
)

$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
if (-not $OutDir) { $OutDir = Split-Path -Parent $appRoot }
$stamp = Get-Date -Format 'yyyyMMdd-HHmm'
$suffix = if ($Lite) { '-lite' } else { '' }
$zipPath = Join-Path $OutDir "HAINGUYENCODER-$stamp$suffix.zip"
$staging = Join-Path $env:TEMP "hnc-pack-$stamp"
$stageApp = Join-Path $staging 'HAINGUYENCODER'

$excludeDirs = @('.git', 'node_modules', (Join-Path $appRoot 'data'))
if ($Lite) { $excludeDirs += (Join-Path $appRoot 'community-skills\antigravity-awesome-skills') }

Write-Host "==> Sao chép vào thư mục tạm $stageApp" -ForegroundColor Cyan
if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
& robocopy $appRoot $stageApp /E /NFL /NDL /NJH /NJS /NP /XD @excludeDirs /XF '*.tmp' '*.log' | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy lỗi (mã $LASTEXITCODE)" }

Write-Host "==> Nén thành $zipPath" -ForegroundColor Cyan
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
if (Get-Command tar.exe -ErrorAction SilentlyContinue) {
  & tar.exe -a -c -f $zipPath -C $staging 'HAINGUYENCODER'
  if ($LASTEXITCODE -ne 0) { throw "tar lỗi (mã $LASTEXITCODE)" }
} else {
  Compress-Archive -Path $stageApp -DestinationPath $zipPath
}
Remove-Item -LiteralPath $staging -Recurse -Force

$sizeMb = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 1)
Write-Host "`n[OK] Đã tạo $zipPath ($sizeMb MB)" -ForegroundColor Green
Write-Host 'Trên máy mới: giải nén -> chạy setup.bat (lần đầu) -> sau đó dùng start.bat.' -ForegroundColor DarkGray
