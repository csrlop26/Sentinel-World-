@echo off
chcp 65001 >nul
title Sentinel World - Actualizacion

echo.
echo  ==========================================
echo    SENTINEL WORLD - Actualizar Bot
echo  ==========================================
echo.

REM ── 1. Descargar últimas actualizaciones ───────────────────────────────────
echo  [1/3] Descargando ultimas actualizaciones de GitHub...
git pull
if errorlevel 1 (
    echo.
    echo  ERROR: No se pudo descargar.
    echo  Comprueba que tienes conexion a internet y acceso al repo.
    pause
    exit /b 1
)

echo.

REM ── 2. Actualizar dependencias Python ─────────────────────────────────────
echo  [2/3] Actualizando dependencias Python...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo.
    echo  ERROR: No se pudieron instalar las dependencias.
    echo  Asegurate de tener Python y pip instalados.
    pause
    exit /b 1
)

echo.

REM ── 3. Listo ───────────────────────────────────────────────────────────────
echo  [3/3] Actualizacion completada.
echo.
echo  ==========================================
echo.
echo  Para arrancar el bot:
echo    python main.py run
echo.
echo  Para ver que eventos detecta la API:
echo    python main.py info
echo.
pause
