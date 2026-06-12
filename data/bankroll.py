"""
Gestión del bankroll con persistencia e interés compuesto.

El bankroll real (tras ganancias/pérdidas registradas) se usa para calcular
los stakes Kelly — así el crecimiento compone en vez de quedarse plano.

Comandos Telegram asociados:
  /bank          → balance, P&L y ROI
  /win 5.50      → registrar ganancia
  /loss 2        → registrar pérdida
  /setbank 120   → fijar balance manualmente
"""

import json
import logging
import os
from datetime import datetime

from config.settings import settings

logger = logging.getLogger(__name__)

_BANKROLL_FILE = "data/bankroll.json"


def _load() -> dict:
    if os.path.exists(_BANKROLL_FILE):
        try:
            with open(_BANKROLL_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "initial": settings.BANKROLL,
        "balance": settings.BANKROLL,
        "history": [],
    }


def _save(data: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(_BANKROLL_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_bankroll() -> float:
    """Balance actual — base para los cálculos de stake Kelly."""
    return float(_load().get("balance", settings.BANKROLL))


def record_result(amount: float, note: str = "") -> float:
    """
    Registra un resultado: positivo = ganancia, negativo = pérdida.
    Devuelve el nuevo balance.
    """
    data = _load()
    data["balance"] = round(float(data["balance"]) + amount, 2)
    data["history"].append({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "amount": round(amount, 2),
        "note": note,
    })
    _save(data)
    logger.info(f"Bankroll: {'+' if amount >= 0 else ''}{amount:.2f}€ → balance €{data['balance']:.2f}")
    return data["balance"]


def set_balance(amount: float) -> float:
    """Fija el balance manualmente (p.ej. tras reconciliar con las casas)."""
    data = _load()
    old = data["balance"]
    data["balance"] = round(amount, 2)
    data["history"].append({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "amount": round(amount - old, 2),
        "note": f"ajuste manual {old:.2f}→{amount:.2f}",
    })
    _save(data)
    return data["balance"]


def get_stats() -> dict:
    """Estadísticas para el comando /bank."""
    data = _load()
    initial = float(data.get("initial", settings.BANKROLL))
    balance = float(data.get("balance", settings.BANKROLL))
    history = data.get("history", [])

    wins = [h for h in history if h["amount"] > 0]
    losses = [h for h in history if h["amount"] < 0]

    profit = balance - initial
    roi = (profit / initial * 100) if initial else 0.0

    return {
        "initial": initial,
        "balance": balance,
        "profit": round(profit, 2),
        "roi_pct": round(roi, 1),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "total_won": round(sum(h["amount"] for h in wins), 2),
        "total_lost": round(abs(sum(h["amount"] for h in losses)), 2),
        "n_records": len(history),
    }
