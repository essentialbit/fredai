#Requires -Version 5.1
<#
.SYNOPSIS
    FredAI — Windows 10/11 Installer
.DESCRIPTION
    Installs FredAI Financial Intelligence Dashboard on Windows.
    Handles: Python installation, virtual environment, Ollama, service setup,
    Start Menu and Desktop shortcuts.
    Works even if Python is not installed.
.NOTES
    Run as: powershell -ExecutionPolicy Bypass -File install.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Config ───────────────────────────────────────────────────────────────────
$RepoUrl    = "https://github.com/essentialbit/fredai"
$RepoZip    = "https://github.com/essentialbit/fredai/archive/refs/heads/main.zip"
$InstallDir = "$env:USERPROFILE\FredAI"
$VenvDir    = "$InstallDir\.venv"
$LogFile    = "$InstallDir\logs\install.log"
$Port       = 8080

# Ollama Windows installer URL
$OllamaUrl  = "https://ollama.com/download/OllamaSetup.exe"

# Python 3.12 installer (stable, widely tested)
$PythonUrl  = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
$PythonUrl32= "https://www.python.org/ftp/python/3.12.4/python-3.12.4.exe"

# ── Helpers ──────────────────────────────────────────────────────────────────
function Write-Step($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host "  [X]  $msg" -ForegroundColor Red; throw $msg }

function Get-RamMB {
    (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB
}

function Get-Arch {
    if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
}

function Test-Command($cmd) {
    $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue)
}

function Download-File($url, $dest) {
    Write-Host "    Downloading $(Split-Path $url -Leaf)..." -NoNewline
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "FredAI-Installer/1.0")
    $wc.DownloadFile($url, $dest)
    Write-Host " done" -ForegroundColor Green
}

# ── Header ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  FredAI Financial Intelligence" -ForegroundColor Cyan
Write-Host "  Windows Installer" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

$RamMB = Get-RamMB
$Arch  = Get-Arch
$Tier  = if ($RamMB -lt 1024) { "lite" } elseif ($RamMB -lt 4096) { "standard" } else { "full" }
$OllamaModel = if ($RamMB -lt 4096) { "phi3:mini" } else { "llama3.2" }

Write-Host "  RAM   : $([math]::Round($RamMB))MB  ->  tier: $Tier"
Write-Host "  Arch  : $Arch"
Write-Host "  Dir   : $InstallDir"
Write-Host ""

New-Item -ItemType Directory -Force -Path "$InstallDir\logs" | Out-Null
New-Item -ItemType Directory -Force -Path "$InstallDir\data" | Out-Null
New-Item -ItemType Directory -Force -Path "$env:TEMP\fredai-install" | Out-Null

# ── Step 1 — Python ───────────────────────────────────────────────────────────
Write-Step "1/8 Python 3"

$python = $null
foreach ($candidate in @("python", "python3", "py")) {
    if (Test-Command $candidate) {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 8) { $python = $candidate; break }
        }
    }
}

if (-not $python) {
    Write-Host "  Python 3.8+ not found. Attempting to install via winget..." -ForegroundColor Yellow

    # Try winget first (Windows 11 and updated Win10)
    if (Test-Command "winget") {
        try {
            winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Null
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            if (Test-Command "python") { $python = "python"; Write-Ok "Python installed via winget" }
        } catch { Write-Warn "winget failed, trying direct download" }
    }

    # Fallback: direct download from python.org
    if (-not $python) {
        $tmpExe = "$env:TEMP\fredai-install\python-installer.exe"
        $pyUrl  = if ($Arch -eq "x64") { $PythonUrl } else { $PythonUrl32 }
        Download-File $pyUrl $tmpExe
        Write-Host "  Running Python installer (silent)..."
        Start-Process -FilePath $tmpExe -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_pip=1", "Include_test=0" -Wait
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        if (Test-Command "python") { $python = "python"; Write-Ok "Python 3.12 installed" }
        else { Write-Err "Python installation failed. Download manually: https://python.org" }
    }
} else {
    Write-Ok "Found: $python ($(& $python --version 2>&1))"
}

# ── Step 2 — Git / Repo ───────────────────────────────────────────────────────
Write-Step "2/8 Repository"

if (Test-Path "$InstallDir\.git") {
    Write-Host "  Updating existing installation..."
    Push-Location $InstallDir
    git fetch origin
    git reset --hard origin/main
    Pop-Location
    Write-Ok "Updated to latest"
} elseif (Test-Command "git") {
    git clone $RepoUrl $InstallDir
    Write-Ok "Cloned to $InstallDir"
} else {
    # No git — download ZIP
    Write-Host "  Git not found — downloading ZIP archive..."
    $zipPath = "$env:TEMP\fredai-install\fredai.zip"
    Download-File $RepoZip $zipPath
    Expand-Archive -Path $zipPath -DestinationPath "$env:TEMP\fredai-install\" -Force
    $extracted = Get-ChildItem "$env:TEMP\fredai-install\" -Directory | Select-Object -First 1
    Copy-Item "$($extracted.FullName)\*" -Destination $InstallDir -Recurse -Force
    Write-Ok "Extracted to $InstallDir"
}

# ── Step 3 — Virtual environment ─────────────────────────────────────────────
Write-Step "3/8 Python environment"

& $python -m venv $VenvDir
$pip = "$VenvDir\Scripts\pip.exe"
$py  = "$VenvDir\Scripts\python.exe"

& $pip install --upgrade pip wheel setuptools -q

$reqFile = if ($Tier -eq "lite") { "$InstallDir\requirements-lite.txt" } else { "$InstallDir\requirements.txt" }
Write-Host "  Installing dependencies from $([System.IO.Path]::GetFileName($reqFile))..."
& $pip install -r $reqFile -q
Write-Ok "Python environment ready"

# ── Step 4 — .env configuration ──────────────────────────────────────────────
Write-Step "4/8 Configuration"

if (-not (Test-Path "$InstallDir\.env")) {
    Copy-Item "$InstallDir\.env.example" "$InstallDir\.env"
    Write-Warn ".env created from template. Edit $InstallDir\.env to add your API keys."
} else {
    Write-Ok ".env already configured"
}

# Generate random SECRET_KEY
$content = Get-Content "$InstallDir\.env" -Raw
if ($content -match "change_this_to_a_random_string") {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 32
    $rng.GetBytes($bytes)
    $newKey = [System.BitConverter]::ToString($bytes).Replace("-","").ToLower()
    $content = $content -replace "change_this_to_a_random_string", $newKey
    Set-Content "$InstallDir\.env" $content
    Write-Ok "Generated random SECRET_KEY"
}

# Patch OLLAMA_MODEL
$content = Get-Content "$InstallDir\.env" -Raw
$content = $content -replace "(?m)^OLLAMA_MODEL=.*", "OLLAMA_MODEL=$OllamaModel"
Set-Content "$InstallDir\.env" $content

# ── Step 5 — Ollama ───────────────────────────────────────────────────────────
Write-Step "5/8 Ollama (local AI — free, no API cost)"

if ($Tier -eq "lite") {
    Write-Warn "Low RAM — skipping Ollama. Use ANTHROPIC_API_KEY in .env for AI features."
} elseif (Test-Command "ollama") {
    Write-Ok "Ollama already installed"
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep 3
    & ollama pull $OllamaModel
    Write-Ok "Model $OllamaModel ready"
} else {
    $ollamaExe = "$env:TEMP\fredai-install\OllamaSetup.exe"
    Download-File $OllamaUrl $ollamaExe
    Write-Host "  Installing Ollama (silent)..."
    Start-Process -FilePath $ollamaExe -ArgumentList "/S" -Wait
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

    if (Test-Command "ollama") {
        Write-Ok "Ollama installed"
        Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep 5
        Write-Host "  Pulling AI model $OllamaModel (may take several minutes)..."
        & ollama pull $OllamaModel
        Write-Ok "Model $OllamaModel ready"
    } else {
        Write-Warn "Ollama install failed. AI features will use Anthropic API if key is set."
    }
}

# ── Step 6 — Windows service ──────────────────────────────────────────────────
Write-Step "6/8 Windows startup"

$startupScript = "$InstallDir\FredAI-Start.bat"
@"
@echo off
cd /d "$InstallDir"
netstat -ano | findstr LISTENING | findstr :$Port >nul
if %errorlevel% neq 0 (
    start "" "$VenvDir\Scripts\python.exe" main.py
    timeout /t 3 >nul
)
start "" http://localhost:$Port
"@ | Set-Content $startupScript

# Register as Windows Scheduler task (auto-start at login)
$action  = New-ScheduledTaskAction -Execute "$VenvDir\Scripts\python.exe" -Argument "main.py" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings= New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
try {
    Register-ScheduledTask -TaskName "FredAI" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
    Write-Ok "Windows Task Scheduler entry created (auto-starts at login)"
} catch {
    Write-Warn "Could not create scheduled task: $_ — use FredAI-Start.bat instead"
}

# ── Step 7 — Shortcuts ────────────────────────────────────────────────────────
Write-Step "7/8 Shortcuts"

$wshShell = New-Object -ComObject WScript.Shell

# Desktop shortcut
$desktopLink = "$([Environment]::GetFolderPath('Desktop'))\FredAI.lnk"
$shortcut = $wshShell.CreateShortcut($desktopLink)
$shortcut.TargetPath  = $startupScript
$shortcut.Description = "FredAI Financial Intelligence Dashboard"
$iconPath = "$InstallDir\assets\icons\windows-256.ico"
if (Test-Path $iconPath) { $shortcut.IconLocation = $iconPath }
$shortcut.Save()
Write-Ok "Desktop shortcut created"

# Start Menu shortcut
$startMenu = "$([Environment]::GetFolderPath('StartMenu'))\Programs\FredAI.lnk"
$shortcut2 = $wshShell.CreateShortcut($startMenu)
$shortcut2.TargetPath  = $startupScript
$shortcut2.Description = "FredAI Financial Intelligence Dashboard"
if (Test-Path $iconPath) { $shortcut2.IconLocation = $iconPath }
$shortcut2.Save()
Write-Ok "Start Menu shortcut created"

# ── Step 8 — Launch ───────────────────────────────────────────────────────────
Write-Step "8/8 Launch"

Start-Process -FilePath $startupScript
Start-Sleep 4

# Get local IP
$localIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback" } | Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  FredAI is running!" -ForegroundColor Green
Write-Host ""
Write-Host "  Local:   http://localhost:$Port" -ForegroundColor Cyan
Write-Host "  Network: http://${localIP}:$Port" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Login:   admin / sentinel2024" -ForegroundColor White
Write-Host "  Config:  $InstallDir\.env" -ForegroundColor Yellow
Write-Host "  Logs:    $InstallDir\logs\fredai.log" -ForegroundColor Yellow
Write-Host ""
Write-Host "  For iOS/Android: open http://${localIP}:$Port"
Write-Host "  in your browser and tap 'Add to Home Screen'"
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "NEXT STEP: Edit .env to add your API keys" -ForegroundColor Yellow
Write-Host "  notepad $InstallDir\.env" -ForegroundColor Yellow
Write-Host ""
