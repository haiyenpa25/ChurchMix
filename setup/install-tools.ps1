<#
.SYNOPSIS
  HAINGUYENCODER — cài công cụ lập trình (Node.js, Git, PHP, Composer, Python, clasp, XAMPP, Docker)
  và đảm bảo biến môi trường PATH. Không cần Node.js để chạy script này.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File setup\install-tools.ps1 -Interactive
  powershell -NoProfile -ExecutionPolicy Bypass -File setup\install-tools.ps1 -Tools node,git,php,composer
  powershell -NoProfile -ExecutionPolicy Bypass -File setup\install-tools.ps1 -CheckOnly
#>
[CmdletBinding()]
param(
  [string[]]$Tools = @(),
  [switch]$Interactive,
  [switch]$CheckOnly,
  [string]$ReportPath,
  [switch]$PauseAtEnd
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ManifestPath = Join-Path $PSScriptRoot 'tools.json'
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$WingetAlreadyInstalled = -1978335189   # 0x8A15002B: no applicable upgrade / already installed
$ComposerPharUrl = 'https://getcomposer.org/download/latest-stable/composer.phar'
$ComposerBinDir = Join-Path $env:LOCALAPPDATA 'HAINGUYENCODER\bin'

# Allow both "-Tools a,b" and "-Tools 'a,b'" (string passed from another process).
$Tools = @($Tools | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })

function Write-Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "  [OK] $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "  [!]  $Message" -ForegroundColor Yellow }
function Write-Fail([string]$Message) { Write-Host "  [X]  $Message" -ForegroundColor Red }

function Expand-PathVariables([string]$Value) { [Environment]::ExpandEnvironmentVariables($Value) }

# Reload PATH from the registry so tools installed a moment ago are visible in this session.
function Update-SessionPath {
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

# Append a directory to the *User* PATH (persistent, no admin needed). Never truncates like setx.
function Add-UserPath([string]$Directory) {
  if (-not (Test-Path -LiteralPath $Directory)) { return $false }
  $user = [Environment]::GetEnvironmentVariable('Path', 'User')
  $entries = @($user -split ';' | Where-Object { $_ })
  $machineEntries = @([Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';' | Where-Object { $_ })
  if (($entries + $machineEntries) | Where-Object { $_.TrimEnd('\') -ieq $Directory.TrimEnd('\') }) { return $false }
  [Environment]::SetEnvironmentVariable('Path', (($entries + $Directory) -join ';'), 'User')
  Write-Ok "Đã thêm vào PATH (User): $Directory"
  Update-SessionPath
  return $true
}

function Get-Tool([string]$Id) {
  $tool = $Manifest.tools | Where-Object { $_.id -eq $Id }
  if (-not $tool) { throw "Không có công cụ '$Id' trong tools.json" }
  return $tool
}

# Returns @{ Installed = bool; Version = string; Source = string }
function Test-Tool($Tool) {
  if ($Tool.detectPaths) {
    foreach ($candidate in $Tool.detectPaths) {
      $path = Expand-PathVariables $candidate
      if (Test-Path -LiteralPath $path) { return @{ Installed = $true; Version = 'đã cài'; Source = $path } }
    }
    return @{ Installed = $false }
  }
  $command = Get-Command $Tool.command -ErrorAction SilentlyContinue | Select-Object -First 1
  # The Windows Store "python" alias lives in WindowsApps and is not a real interpreter.
  if (-not $command -or $command.Source -like '*\WindowsApps\*') { return @{ Installed = $false } }
  try {
    $output = & $command.Source @($Tool.versionArgs) 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or -not $output.Trim()) { return @{ Installed = $false } }
    return @{ Installed = $true; Version = ($output.Trim() -split "`r?`n")[0]; Source = $command.Source }
  } catch {
    return @{ Installed = $false }
  }
}

# Before downloading anything, look for an existing install that is just missing from PATH.
function Repair-PathFromCandidates($Tool) {
  foreach ($candidate in @($Tool.pathCandidates)) {
    if (-not $candidate) { continue }
    $directory = Expand-PathVariables $candidate
    if (-not $Tool.command) { continue }
    $hasExecutable = @("$($Tool.command).exe", "$($Tool.command).cmd", "$($Tool.command).bat") |
      Where-Object { Test-Path -LiteralPath (Join-Path $directory $_) }
    if ($hasExecutable) { [void](Add-UserPath $directory) }
  }
}

function Assert-Winget {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "Không tìm thấy winget. Cài 'App Installer' từ Microsoft Store (Windows 10/11) rồi chạy lại."
  }
}

function Install-WithWinget($Tool) {
  Assert-Winget
  $arguments = @('install', '--id', $Tool.install.id, '--exact', '--silent',
    '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity')
  if ($Tool.install.override) { $arguments += @('--override', $Tool.install.override) }
  Write-Host "  winget $($arguments -join ' ')" -ForegroundColor DarkGray
  & winget @arguments
  if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $WingetAlreadyInstalled) {
    throw "winget trả về mã lỗi $LASTEXITCODE"
  }
}

function Install-Composer {
  $php = Get-Command php -ErrorAction SilentlyContinue
  if (-not $php) { throw 'Composer cần PHP trong PATH. Cài PHP trước.' }
  New-Item -ItemType Directory -Force -Path $ComposerBinDir | Out-Null
  $pharPath = Join-Path $ComposerBinDir 'composer.phar'
  $tempPath = "$pharPath.download"

  Write-Host "  Tải $ComposerPharUrl" -ForegroundColor DarkGray
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $ComposerPharUrl -OutFile $tempPath -UseBasicParsing
  $expected = (Invoke-WebRequest -Uri "$ComposerPharUrl.sha256" -UseBasicParsing).Content.Trim().Split(' ')[0]
  $actual = (Get-FileHash -LiteralPath $tempPath -Algorithm SHA256).Hash
  if ($actual -ine $expected) {
    Remove-Item -LiteralPath $tempPath -Force
    throw "Checksum composer.phar không khớp (mong đợi $expected, nhận $actual). Đã hủy."
  }
  Move-Item -LiteralPath $tempPath -Destination $pharPath -Force
  Set-Content -LiteralPath (Join-Path $ComposerBinDir 'composer.bat') -Value "@php `"%~dp0composer.phar`" %*" -Encoding ASCII
  Write-Ok 'Đã xác minh SHA-256 của composer.phar'
}

function Install-WithNpm($Tool) {
  $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if (-not $npm) { throw 'Cần Node.js (npm) trước.' }
  & $npm.Source install -g $Tool.install.package
  if ($LASTEXITCODE -ne 0) { throw "npm trả về mã lỗi $LASTEXITCODE" }
}

function Install-Tool($Tool) {
  switch ($Tool.install.type) {
    'winget' { Install-WithWinget $Tool }
    'composer' { Install-Composer }
    'npm' { Install-WithNpm $Tool }
    default { throw "Kiểu cài đặt không hỗ trợ: $($Tool.install.type)" }
  }
}

# Expand dependencies so that e.g. composer pulls in php, clasp pulls in node; keep manifest order.
function Resolve-InstallOrder([string[]]$Ids) {
  $wanted = New-Object System.Collections.Generic.HashSet[string]
  $queue = New-Object System.Collections.Generic.Queue[string]
  $Ids | ForEach-Object { $queue.Enqueue($_) }
  while ($queue.Count -gt 0) {
    $id = $queue.Dequeue()
    if ($wanted.Add($id)) { @((Get-Tool $id).dependsOn) | Where-Object { $_ } | ForEach-Object { $queue.Enqueue($_) } }
  }
  return @($Manifest.tools | Where-Object { $wanted.Contains($_.id) } | ForEach-Object { $_.id })
}

function Get-StatusTable([bool]$RepairPath = $true) {
  Update-SessionPath
  foreach ($tool in $Manifest.tools) {
    $status = Test-Tool $tool
    if (-not $status.Installed -and $RepairPath) { Repair-PathFromCandidates $tool; $status = Test-Tool $tool }
    [pscustomobject]@{ Id = $tool.id; Label = $tool.label; Installed = $status.Installed; Version = $status.Version; Required = [bool]$tool.required; Heavy = [bool]$tool.heavy }
  }
}

function Show-Status($Rows) {
  Write-Step 'Trạng thái công cụ trên máy này'
  foreach ($row in $Rows) {
    $tag = if ($row.Required) { ' (bắt buộc)' } elseif ($row.Heavy) { ' (nặng, cần Admin)' } else { '' }
    if ($row.Installed) { Write-Ok "$($row.Label): $($row.Version)" } else { Write-Warn "$($row.Label): CHƯA CÀI$tag" }
  }
}

function Confirm-Choice([string]$Question, [bool]$Default = $false) {
  $suffix = if ($Default) { '[Y/n]' } else { '[y/N]' }
  $answer = Read-Host "$Question $suffix"
  if (-not $answer) { return $Default }
  return $answer -match '^(y|yes|c|co)$'
}

# npm.ps1 / scripts are blocked when the effective policy is Restricted or Undefined (default on Windows client).
function Repair-ExecutionPolicy {
  $policy = Get-ExecutionPolicy
  if ($policy -in @('Restricted', 'Undefined', 'AllSigned')) {
    Write-Warn "ExecutionPolicy hiện tại: $policy — lệnh 'npm' trong PowerShell sẽ bị chặn."
    if (Confirm-Choice 'Đặt ExecutionPolicy = RemoteSigned cho user hiện tại (chỉ cho phép script local)?' $true) {
      Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
      Write-Ok 'Đã đặt RemoteSigned (CurrentUser)'
    }
  }
}

$AntigravityConfigDir = Join-Path $env:USERPROFILE '.gemini\config'
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Find-FirstPath([string[]]$Candidates) {
  foreach ($candidate in $Candidates) { if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate } }
  return $null
}

# Prefer a globally installed MCP binary (fast start, works offline); otherwise run the latest via npx.
function Get-McpLaunch([string]$BinaryName, [string]$NpmPackage, [string[]]$ExtraArgs) {
  if (Get-Command "$BinaryName.cmd" -ErrorAction SilentlyContinue) { return @('/c', $BinaryName) + $ExtraArgs }
  return @('/c', 'npx', '-y', "$NpmPackage@latest") + $ExtraArgs
}

# Chrome DevTools MCP + Playwright MCP for Antigravity. Keeps every other server already configured.
function Configure-AntigravityMcp {
  Write-Step 'Cấu hình MCP cho Antigravity IDE (Chrome DevTools + Playwright)'
  New-Item -ItemType Directory -Force -Path $AntigravityConfigDir | Out-Null
  $configFile = Join-Path $AntigravityConfigDir 'mcp_config.json'

  $chrome = Find-FirstPath @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
  $edge = Find-FirstPath @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe")

  if ($chrome) {
    $devtoolsArgs = @('--channel', 'stable')
    $playwrightArgs = @('--browser', 'chrome')
    Write-Ok "Trình duyệt: Google Chrome ($chrome)"
  } elseif ($edge) {
    $devtoolsArgs = @('--executablePath', $edge)
    $playwrightArgs = @('--browser', 'msedge')
    Write-Warn "Không có Google Chrome — dùng Microsoft Edge ($edge). Nên cài Chrome để dùng đầy đủ DevTools MCP."
  } else {
    Write-Warn 'Không tìm thấy Chrome hay Edge — MCP trình duyệt sẽ không chạy được cho tới khi cài Chrome.'
    $devtoolsArgs = @('--channel', 'stable')
    $playwrightArgs = @('--browser', 'chrome')
  }

  $mcpServers = [ordered]@{
    'chrome-devtools' = [ordered]@{ command = 'cmd.exe'; args = @(Get-McpLaunch 'chrome-devtools-mcp' 'chrome-devtools-mcp' $devtoolsArgs) }
    'playwright'      = [ordered]@{ command = 'cmd.exe'; args = @(Get-McpLaunch 'playwright-mcp' '@playwright/mcp' $playwrightArgs) }
  }

  if (Test-Path -LiteralPath $configFile) {
    $raw = Get-Content -LiteralPath $configFile -Raw -Encoding UTF8
    if ($raw -and $raw.Trim()) {
      try {
        $existing = $raw | ConvertFrom-Json
        if ($existing.mcpServers) {
          foreach ($prop in $existing.mcpServers.PSObject.Properties) {
            if (-not $mcpServers.Contains($prop.Name)) { $mcpServers[$prop.Name] = $prop.Value }
          }
        }
      } catch {
        $backup = "$configFile.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Copy-Item -LiteralPath $configFile -Destination $backup
        Write-Warn "mcp_config.json cũ không phải JSON hợp lệ — đã sao lưu sang $backup"
      }
    }
  }

  $json = [ordered]@{ mcpServers = $mcpServers } | ConvertTo-Json -Depth 6
  [IO.File]::WriteAllText($configFile, $json, $Utf8NoBom)
  Write-Ok "Đã ghi $configFile — khởi động lại Antigravity IDE để nạp MCP."
}

# Copy the curated community skills (setup/global-skills.json) into the global Antigravity skills folder.
function Install-CommunitySkills {
  Write-Step 'Cài skill cộng đồng vào Antigravity (dùng chung cho mọi dự án)'
  $listFile = Join-Path $PSScriptRoot 'global-skills.json'
  if (-not (Test-Path -LiteralPath $listFile)) { Write-Warn 'Không có setup/global-skills.json — bỏ qua.'; return }
  $appRoot = Split-Path -Parent $PSScriptRoot
  $skillsDir = Join-Path $AntigravityConfigDir 'skills'
  New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null

  foreach ($entry in (Get-Content -LiteralPath $listFile -Raw -Encoding UTF8 | ConvertFrom-Json).skills) {
    $source = Join-Path $appRoot ($entry.source -replace '/', '\')
    $skillFile = Join-Path $source 'SKILL.md'
    if (-not (Test-Path -LiteralPath $skillFile)) { Write-Warn "Thiếu $($entry.source) (chưa tải community-skills?)"; continue }
    $nameLine = Select-String -LiteralPath $skillFile -Pattern '^name:\s*(.+?)\s*$' | Select-Object -First 1
    $name = if ($nameLine) { $nameLine.Matches[0].Groups[1].Value.Trim('"', "'") } else { Split-Path -Leaf $source }
    $target = Join-Path $skillsDir $name
    if (Test-Path -LiteralPath $target) { Write-Ok "$name (đã có, giữ nguyên)"; continue }
    Copy-Item -LiteralPath $source -Destination $target -Recurse
    Write-Ok "$name — $($entry.why)"
  }
}


# ---------------- main ----------------
$results = @()
try {
  $rows = @(Get-StatusTable (-not $CheckOnly))
  Show-Status $rows

  if ($CheckOnly) {
    $results = $rows
  } else {
    if ($Interactive) {
      $selected = @($rows | Where-Object { -not $_.Installed -and $_.Required } | ForEach-Object { $_.Id })
      foreach ($row in $rows | Where-Object { -not $_.Installed -and -not $_.Required }) {
        $tool = Get-Tool $row.Id
        if (Confirm-Choice "Cài $($row.Label)? — $($tool.purpose)") { $selected += $row.Id }
      }
      $Tools = $selected
      Repair-ExecutionPolicy
    }

    $order = if ($Tools.Count) { Resolve-InstallOrder $Tools } else { @() }
    foreach ($id in $order) {
      $tool = Get-Tool $id
      Write-Step "$($tool.label)"
      $status = Test-Tool $tool
      if ($status.Installed) { Write-Ok "Đã có: $($status.Version)"; continue }
      try {
        Install-Tool $tool
        Update-SessionPath
        foreach ($candidate in @($tool.pathCandidates)) { if ($candidate) { [void](Add-UserPath (Expand-PathVariables $candidate)) } }
        $status = Test-Tool $tool
        if ($status.Installed) { Write-Ok "Đã cài: $($status.Version)" }
        else { Write-Warn 'Đã chạy trình cài nhưng chưa nhận diện được — mở cửa sổ terminal mới hoặc khởi động lại máy rồi kiểm tra lại.' }
      } catch {
        Write-Fail "$($tool.label): $($_.Exception.Message)"
      }
    }
    Configure-AntigravityMcp
    if ($Interactive) { Install-CommunitySkills }
    $results = @(Get-StatusTable)
    if ($order.Count) { Show-Status $results }
  }
} catch {
  Write-Fail $_.Exception.Message
  $exitCode = 1
}

if ($ReportPath) {
  $reportDir = Split-Path -Parent $ReportPath
  if ($reportDir) { New-Item -ItemType Directory -Force -Path $reportDir | Out-Null }
  $report = [pscustomobject]@{ checkedAt = (Get-Date).ToString('o'); tools = $results }
  $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
}

Write-Host "`nLưu ý: các cửa sổ terminal/IDE đang mở cần mở lại để nhận PATH mới." -ForegroundColor DarkGray
if ($PauseAtEnd) { Read-Host 'Nhấn Enter để đóng' | Out-Null }
exit ($(if ($exitCode) { $exitCode } else { 0 }))
