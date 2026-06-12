"""
Auditoría de seguridad del repositorio.
Detecta secretos o archivos privados que podrían estar expuestos en el repo público.

Uso:
    python tools/check_security.py
"""
import re
import subprocess
import sys
from pathlib import Path

RED = "\033[0;31m"
YELLOW = "\033[1;33m"
GREEN = "\033[0;32m"
BOLD = "\033[1m"
NC = "\033[0m"

# Patrones que indican secretos reales (no placeholders)
_PATTERNS = [
    (r"[0-9]{8,12}:[A-Za-z0-9_-]{35,}", "Telegram Bot Token"),
    (r"(?:ODDS_API_KEY|THEODDS_API_KEY|BOT_TOKEN|ACCESS_TOKEN)\s*=\s*[a-zA-Z0-9_-]{15,}", "API Key"),
    (r"TELEGRAM_CHAT_ID\s*=\s*-?[0-9]{5,}", "Telegram Chat ID"),
    (r"(?:password|passwd|secret)\s*=\s*[^\s]{8,}", "Contraseña"),
]

_PLACEHOLDER_WORDS = {"your_", "example", "placeholder", "here", "test", "fake", "dummy", "xxx", "change_me"}

_SKIP_EXTENSIONS = {".pyc", ".png", ".jpg", ".gif", ".pdf", ".zip", ".enc", ".ico"}
_SKIP_FILES = {".env.example", ".env.enc"}


def _is_placeholder(line: str) -> bool:
    low = line.lower()
    return any(w in low for w in _PLACEHOLDER_WORDS)


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    if path.suffix in _SKIP_EXTENSIONS or path.name in _SKIP_FILES:
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    issues = []
    for i, line in enumerate(content.splitlines(), 1):
        for pattern, label in _PATTERNS:
            if re.search(pattern, line, re.IGNORECASE) and not _is_placeholder(line):
                masked = re.sub(r"=\s*\S+", "= [*** OCULTADO ***]", line.strip())
                issues.append((i, label, masked))
    return issues


def _git(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        return ""


def main():
    print(f"\n{BOLD}=== Sentinel World — Auditoría de Seguridad ==={NC}\n")
    exit_code = 0

    # ── Check 1: .env rastreado por git ─────────────────────────────────────
    tracked_env = _git(["git", "ls-files", ".env"])
    if tracked_env:
        print(f"{RED}✗ CRÍTICO: .env está siendo rastreado por git!{NC}")
        print(f"  Ejecuta: git rm --cached .env && git commit -m 'remove .env from tracking'")
        exit_code = 1
    else:
        print(f"{GREEN}✓ .env no está en el repo{NC}")

    # ── Check 2: .env ignorado correctamente ─────────────────────────────────
    result = subprocess.run(["git", "check-ignore", "-v", ".env"],
                            capture_output=True, text=True)
    if result.returncode == 0:
        print(f"{GREEN}✓ .env está en .gitignore{NC}")
    else:
        print(f"{YELLOW}⚠ .env NO está en .gitignore — añádelo{NC}")

    # ── Check 3: hooks de seguridad activos ──────────────────────────────────
    hooks_path = _git(["git", "config", "core.hooksPath"])
    if hooks_path == ".githooks":
        print(f"{GREEN}✓ Hook pre-commit activo (.githooks){NC}")
    else:
        print(f"{YELLOW}⚠ Hook pre-commit NO configurado — ejecuta update.bat{NC}")

    # ── Check 4: escaneo de archivos rastreados por git ──────────────────────
    print(f"\n  Escaneando archivos del repo...")
    tracked = _git(["git", "ls-files"]).splitlines()
    found_any = False
    for filename in tracked:
        p = Path(filename)
        if not p.exists():
            continue
        issues = _scan_file(p)
        if issues:
            found_any = True
            for line_num, label, masked in issues:
                print(f"{RED}  ✗ {filename}:{line_num} — {label}{NC}")
                print(f"     {masked}")
                exit_code = 1

    # ── Check 5: verificar commits recientes ─────────────────────────────────
    recent = _git(["git", "log", "--oneline", "-5"])
    print(f"\n  Últimos 5 commits:")
    for line in recent.splitlines():
        print(f"    {line}")

    # ── Resumen ───────────────────────────────────────────────────────────────
    print()
    if exit_code == 0 and not found_any:
        print(f"{GREEN}✓ Repo limpio — no se detectaron secretos expuestos{NC}\n")
    else:
        print(f"{RED}✗ Se encontraron problemas — revisa antes de hacer push{NC}\n")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
