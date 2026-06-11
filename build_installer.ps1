# Build the single Alpha POS installer (AlphaPOS-Setup.exe) end to end.
#
#   powershell -ExecutionPolicy Bypass -File build_installer.ps1
#
# Steps:
#   1. (re)generate the app icon
#   2. PyInstaller -> dist\AlphaPOS\  (the app, all Python compiled into the bundle)
#   3. Inno Setup  -> installer\Output\AlphaPOS-Setup.exe  (the one file you ship)
#
# Requires: the project's .venv, and Inno Setup 6 installed.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Prefer a dedicated build venv (.venv-build) when present. It carries the
# self-update stack (tufup/bsdiff4), whose wheels aren't available on the 3.14
# dev venv, so a build from it ships a self-updating app. Falls back to .venv.
$venv = if (Test-Path (Join-Path $root '.venv-build\Scripts\python.exe')) { '.venv-build' } else { '.venv' }
Write-Host "Using build venv: $venv" -ForegroundColor DarkCyan
$py = Join-Path $root "$venv\Scripts\python.exe"
$pyinstaller = Join-Path $root "$venv\Scripts\pyinstaller.exe"

# Locate the Inno Setup compiler (default + per-user winget install location).
$isccCandidates = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "ISCC.exe not found. Install Inno Setup 6 (winget install JRSoftware.InnoSetup)." }

Write-Host '== 1/3  Generating icon ==' -ForegroundColor Cyan
& $py 'desktop\make_icon.py'

Write-Host '== 2/3  Building app bundle (PyInstaller) ==' -ForegroundColor Cyan
& $pyinstaller --noconfirm --clean 'AlphaPOS.spec'
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }

Write-Host '== 3/3  Compiling installer (Inno Setup) ==' -ForegroundColor Cyan
& $iscc 'installer\AlphaPOS.iss'
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed ($LASTEXITCODE)" }

$out = Join-Path $root 'installer\Output\AlphaPOS-Setup.exe'
Write-Host ''
Write-Host "DONE -> $out" -ForegroundColor Green
