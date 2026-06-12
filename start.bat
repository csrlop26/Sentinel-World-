@echo off
chcp 65001 >nul
title Sentinel World - Bot Activo

echo.
echo  ==========================================
echo    SENTINEL WORLD - Iniciando Bot
echo  ==========================================
echo.

REM ── Verificar .env ────────────────────────────────────────────────────────
if not exist .env (
    echo  ERROR: No se encuentra .env con tus claves.
    echo  Ejecuta primero update.bat para configurarlo.
    echo.
    pause
    exit /b 1
)

REM ── Verificar Python ──────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python no encontrado.
    echo  Instala Python 3.10+ desde https://python.org
    echo.
    pause
    exit /b 1
)

REM ── Menú de inicio ────────────────────────────────────────────────────────
echo  Opciones:
echo.
echo    [1] Arrancar bot  (loop continuo, alertas por Telegram)
echo    [2] Modo info     (ver partidos y ligas disponibles en la API)
echo    [3] Auditoria     (verificar que el repo esta limpio de secretos)
echo.
set /p OPCION="  Elige una opcion (1/2/3): "

if "%OPCION%"=="1" goto :run
if "%OPCION%"=="2" goto :info
if "%OPCION%"=="3" goto :audit

echo  Opcion no valida. Arrancando bot por defecto...
goto :run

:run
echo.
echo  Arrancando bot... (Ctrl+C para detener)
echo  Los logs se guardan en sentinel.log
echo.
python main.py run
goto :end

:info
echo.
python main.py info
goto :end

:audit
echo.
python tools/check_security.py
goto :end

:end
echo.
pause
