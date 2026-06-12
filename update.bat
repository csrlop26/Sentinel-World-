@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Sentinel World - Actualizar Bot

REM ── Ir siempre a la carpeta donde está este .bat ──────────────────────────
cd /d "%~dp0"

echo.
echo  ==========================================
echo    SENTINEL WORLD - Actualizar Bot
echo  ==========================================
echo.

REM ── Verificar que estamos en el repositorio Git ───────────────────────────
git status >nul 2>&1
if errorlevel 1 (
    echo  ERROR: No se detecta repositorio Git en:
    echo  %CD%
    echo.
    echo  Posibles causas:
    echo    1. Aun no has clonado el repositorio. Usa Git para clonar:
    echo       git clone https://github.com/csrlop26/Sentinel-World-.git
    echo    2. Git no esta instalado. Descargalo en https://git-scm.com
    echo.
    pause
    exit /b 1
)

REM ── 1. Activar hooks de seguridad (bloquean secretos antes del commit) ────
echo  [Seguridad] Activando hook pre-commit...
git config core.hooksPath .githooks
echo  OK: los commits quedan protegidos automaticamente.
echo.

REM ── 2. Descargar últimas actualizaciones ──────────────────────────────────
echo  [1/3] Descargando ultimas actualizaciones de GitHub...
git pull
if errorlevel 1 (
    echo.
    echo  ERROR: No se pudo descargar.
    echo  Comprueba que tienes conexion a internet y acceso al repositorio.
    pause
    exit /b 1
)
echo.

REM ── 3. Actualizar dependencias Python ─────────────────────────────────────
echo  [2/3] Actualizando dependencias Python...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo.
    echo  ERROR: No se pudieron instalar las dependencias.
    echo  Asegurate de tener Python 3.10+ y pip instalados.
    pause
    exit /b 1
)
echo.

REM ── 4. Gestionar .env (configuración privada — NUNCA en el repo) ──────────
echo  [3/3] Verificando configuracion privada (.env)...

if exist .env (
    echo  OK: .env encontrado en tu ordenador.
    goto :done
)

REM .env no existe — buscar .env.enc o crear desde plantilla
echo  AVISO: no se encontro .env
echo.

if exist .env.enc (
    echo  Se encontro .env.enc ^(archivo cifrado^).
    echo  Puedes descifrar tu configuracion privada con la contrasena que usaste al cifrar.
    echo.
    set /p DECRYPT="  Descifrar .env.enc ahora? (s/n): "
    if /i "!DECRYPT!"=="s" (
        python tools/decrypt_env.py
        if errorlevel 1 (
            echo  No se pudo descifrar. Revisa la contrasena.
        ) else (
            echo  Configuracion restaurada correctamente.
        )
    )
    goto :done
)

REM Primera vez — crear .env desde la plantilla
echo  Creando .env desde la plantilla (.env.example)...
copy .env.example .env >nul
echo.
echo  ============================================================
echo    ACCION REQUERIDA: rellena tus claves en el archivo .env
echo  ============================================================
echo.
echo  Abre .env con cualquier editor de texto y rellena:
echo    ODDS_API_KEY       = tu key de odds-api.net
echo    THEODDS_API_KEY    = tu key de the-odds-api.com
echo    TELEGRAM_BOT_TOKEN = token de tu bot de Telegram
echo    TELEGRAM_CHAT_ID   = tu chat ID de Telegram
echo.
echo  El archivo .env NUNCA se sube al repositorio publico.
echo  Esta protegido por .gitignore y por el hook pre-commit.
echo.

:done
echo.
echo  ==========================================
echo.
echo  Comandos disponibles:
echo.
echo    python main.py run        Arrancar el bot
echo    python main.py info       Ver eventos disponibles en la API
echo.
echo    python tools/check_security.py    Auditar el repo
echo    python tools/encrypt_env.py       Cifrar .env como backup
echo    python tools/decrypt_env.py       Restaurar .env desde .env.enc
echo.
pause
