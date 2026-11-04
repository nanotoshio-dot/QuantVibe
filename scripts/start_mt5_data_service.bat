@echo off
setlocal
cd /d "%~dp0.."
".venv\Scripts\python.exe" -u scripts\mt5_market_service.py
echo Read-only MT5 market-data service stopped.
endlocal
