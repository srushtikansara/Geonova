# Starts the dashboard on http://localhost:5173 (the backend must be running)
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\frontend"
npm run dev
