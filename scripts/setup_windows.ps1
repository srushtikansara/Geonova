# GEONOVA one-time setup for Windows 11 (PowerShell). Run from the project root:  .\scripts\setup_windows.ps1
# Creates the Python venv, installs backend and frontend dependencies, and copies the .env templates.
# It does NOT create the database or write any password: see docs/DATABASE.md.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== Checking prerequisites"
python --version
node --version
java -version 2>&1 | Select-Object -First 1   # needed only for the PySpark benchmark (Java 17 or 21)

Write-Host "== Backend"
Set-Location "$root\backend"
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created backend\.env. Edit it and replace CHANGE_ME with your own database password." }

Write-Host "== Frontend"
Set-Location "$root\frontend"
npm install
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

Write-Host "Done. Next: create the database (docs/DATABASE.md), then .\scripts\run_backend.ps1 and .\scripts\run_frontend.ps1"
