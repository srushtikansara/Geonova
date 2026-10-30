# Applies database migrations and starts the API on http://localhost:8000
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.db.seed   # adds the three city regions; safe to repeat
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
