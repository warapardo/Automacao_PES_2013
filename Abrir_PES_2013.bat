@echo off
cd /d "%~dp0"
python "%~dp0pes_sync.py"
if errorlevel 1 (
  echo.
  echo Falha na automacao. Consulte pes_sync.log.
  pause
)
