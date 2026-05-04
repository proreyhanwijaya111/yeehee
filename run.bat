@echo off
REM yeehee launcher
REM Usage:
REM   run.bat          → start Streamlit dashboard
REM   run.bat bot      → start Telegram bot (push + interactive)
REM   run.bat test     → run smoke test
REM   run.bat signal   → print current signal bundle (CLI)
REM   run.bat tunnel   → start Cloudflare Tunnel for dashboard
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [yeehee] venv tidak ditemukan. Run setup.bat dulu.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

if "%1"=="test" (
    python smoke_test.py
    pause
    exit /b 0
)

if "%1"=="signal" (
    python signal_engine.py
    pause
    exit /b 0
)

if "%1"=="bot" (
    echo [yeehee] starting Telegram bot...
    python -m notify.telegram_bot
    pause
    exit /b 0
)

if "%1"=="api" (
    echo [yeehee] starting FastAPI backend at http://localhost:8000
    echo Docs: http://localhost:8000/docs
    pip install -q fastapi uvicorn[standard] 2>nul
    python -m uvicorn api.main:app --reload --port 8000
    pause
    exit /b 0
)

if "%1"=="tunnel" (
    where cloudflared >nul 2>nul
    if errorlevel 1 (
        echo [yeehee] cloudflared tidak ditemukan.
        echo Install: winget install --id Cloudflare.cloudflared
        pause
        exit /b 1
    )
    echo [yeehee] starting Cloudflare quick tunnel for localhost:8501
    echo URL akan keluar di bawah, buka di HP lo:
    cloudflared tunnel --url http://localhost:8501
    exit /b 0
)

echo [yeehee] starting dashboard at http://localhost:8501
echo Tip: run.bat bot ^(buka window kedua^) untuk Telegram bot
echo      run.bat tunnel ^(window ketiga^) untuk akses HP
streamlit run dashboard/app.py

endlocal
