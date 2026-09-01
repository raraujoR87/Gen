@echo off
REM Sets up and starts the local paper-trading service on Windows.
REM See RUN_LOCAL.md for what this does and what it doesn't prove.
REM
REM Prerequisites (not handled by this script):
REM   - Python 3.11+ on PATH
REM   - Redis reachable at REDIS_URL (default redis://localhost:6379/0) —
REM     e.g. Memurai (https://www.memurai.com/get-memurai) running as a
REM     Windows service, or Redis under WSL2. No Docker required.
REM   - A .env file in this directory (copy .env.example and edit
REM     MONITORED_PAIRS at minimum; DATABASE_URL defaults to a local
REM     SQLite file, sqlite+aiosqlite:///./local.db, if left unset below).

setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".env" (
    echo No .env found — copying .env.example to .env.
    echo Edit .env ^(at least MONITORED_PAIRS^) before running this again if this is your first run.
    copy .env.example .env >nul
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create the virtual environment. Is Python 3.11+ installed and on PATH?
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

echo Installing dependencies ...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo pip install failed — see the output above.
    exit /b 1
)

echo Initializing the database (SQLite-compatible; safe to re-run) ...
python scripts\init_db.py
if errorlevel 1 (
    echo Database initialization failed — see the output above.
    exit /b 1
)

echo.
echo Starting the API + local paper-trading runner.
echo Dashboard: http://localhost:8000/dashboard
echo Press Ctrl+C to stop.
echo.
uvicorn backend.api.main:app --host 127.0.0.1 --port 8000

endlocal
