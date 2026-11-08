@echo off
cd /d "%~dp0"
python pes_sync.py
if errorlevel 1 (
    echo.
    echo Ocorreu um erro. Consulte pes_sync.log nesta pasta.
    pause
)
