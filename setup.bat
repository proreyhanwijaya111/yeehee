@echo off
REM yeehee setup — buat venv & install deps
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [yeehee] Python tidak ditemukan di PATH.
    echo Install Python 3.11+ dari https://www.python.org/downloads/
    echo Pastikan centang "Add Python to PATH" saat install.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [yeehee] creating venv...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [yeehee] upgrading pip...
python -m pip install --upgrade pip

echo [yeehee] installing dependencies (akan memakan waktu 2-5 menit)...
pip install -r requirements.txt

if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo [yeehee] .env created from .env.example
    )
)

echo.
echo [yeehee] setup done!
echo - Run dashboard:  run.bat
echo - Run smoke test: run.bat test
echo - Run engine CLI: run.bat signal
echo.
pause
endlocal
