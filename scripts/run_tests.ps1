# Runs backend tests (set TEST_DATABASE_URL first for the PostgreSQL tests) and the frontend build.
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
.\.venv\Scripts\python.exe -m pytest app/tests -q -rs
Set-Location "$root\frontend"
npm run build
