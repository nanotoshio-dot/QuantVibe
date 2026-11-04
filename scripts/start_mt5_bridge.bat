@echo off
title QuantVibe MT5 Bridge Launcher
color 0A
cls
echo ====================================================================
echo        QUANTVIBE INSTITUTIONAL ENGINE - MT5 1-CLICK DESKTOP BRIDGE
echo                    https://quantvibeapp.com/
echo ====================================================================
echo.
echo [1/3] Verificando entorno Python...
set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [ERROR] No se encontro la .venv del proyecto:
    echo %PYTHON%
    echo Ejecuta la configuracion del entorno desde la raiz de QuantVibe.
    pause
    exit /b 1
)

echo [2/3] Verificando paquete MetaTrader5...
"%PYTHON%" -c "import MetaTrader5" >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] MetaTrader5 no esta instalado en la .venv del proyecto.
    echo Reinstala las dependencias del proyecto; no se instalara nada globalmente.
    pause
    exit /b 1
)

echo [3/3] Iniciando puente de conexion con MetaTrader 5...
echo Asegurate de que tu terminal MetaTrader 5 este ABIERTO en tu PC.
echo.
"%PYTHON%" "%~dp0quantvibe_mt5_bridge.py" --server https://quantvibeapp.com

pause
