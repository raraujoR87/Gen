@echo off
REM Sets up and starts the local paper-trading service on Windows.
REM See RUN_LOCAL.md for what this does and what it doesn't prove.
REM
REM Prerequisites (not handled by this script):
REM   - Python 3.11 or 3.12 installed (see the version check below — newer
REM     releases like 3.13/3.14 commonly lack prebuilt wheels for pinned
REM     deps such as torch/numpy/pydantic-core and fail to compile from
REM     source). Installing alongside a newer Python you already have is
REM     fine; this script picks 3.12/3.11 via the "py" launcher if present.
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

REM Prefer Python 3.12, then 3.11, via the "py" launcher (installed with any
REM python.org build); fall back to whatever "python" resolves to on PATH.
set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 -c "1" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3.12"
)
if not defined PY_CMD (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.11 -c "1" >nul 2>nul
        if not errorlevel 1 set "PY_CMD=py -3.11"
    )
)
if not defined PY_CMD set "PY_CMD=python"

for /f "tokens=1" %%v in ('%PY_CMD% -c "import sys; print(sys.version.split()[0])"') do set "PY_VERSION=%%v"
echo Using Python %PY_VERSION% ^(%PY_CMD%^)
echo %PY_VERSION% | findstr /r "^3\.1[34]\." >nul
if not errorlevel 1 (
    echo.
    echo WARNING: Python %PY_VERSION% is newer than this project's dependencies
    echo have prebuilt wheels for ^(torch/numpy/pydantic-core etc.^) — pip will
    echo likely try to compile them from source and fail, as you may have just
    echo seen. Install Python 3.12 from https://www.python.org/downloads/ ^(check
    echo "Add python.exe to PATH"^), delete the .venv folder if one exists, and
    echo re-run this script — it will pick up 3.12 automatically via the "py"
    echo launcher.
    echo.
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv ...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

echo Installing dependencies ...
pip install -q -r requirements-local.txt
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
