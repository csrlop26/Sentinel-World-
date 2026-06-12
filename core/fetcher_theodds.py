"""
Cliente para The Odds API (the-odds-api.com).

Free plan: 500 req/mes. Cada llamada a /odds usa:
  [número de markets] × [número de regiones] cuota.
Con markets=h2h,totals,btts y regions=eu,uk → 6 cuota por llamada.

Se usa caché en memoria para no agotar el cupo.
"""

import logging
import time
from datetime import datetime, timezone

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.the-odds-api.com/v4"
_WORLD_CUP_KEY = "soccer_fifa_world_cup"

# Caché en memoria: {cache_key: (timestamp_float, data)}
_cache: dict[str, tuple[float, list]] = {}

# Etiquetas legibles por mercado
_MARKET_LABELS: dict[str, str] = {
    "h2h":   "1×2",
    "btts":  "Ambos marcan",
}

# Emojis por mercado para las alertas
MARKET_EMOJIS: dict[str, str] = {
    "h2h":    "🏆",
    "totals": "⚽",
    "btts":   "🥅",
}


def _cached_get(url: str, params: dict, ttl_seconds: int) -> list:
    cache_key = url + str(sorted(params.items()))
    now = time.time()
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if now - ts < ttl_seconds:
            logger.debug(f"TheOddsAPI cache hit ({int(now - ts)}s): {url}")
            return data

    with httpx.Client(timeout=15) as client:
        resp = client.get(url, params=params)
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        logger.info(f"TheOddsAPI → {resp.status_code} | cuota: {used} usada / {remaining} restante")
        resp.raise_for_status()
        data = resp.json()

    _cache[cache_key] = (now, data)
    return data


def get_events_for_sport(sport_key: str) -> list[dict]:
    """Devuelve todos los eventos de un deporte con cuotas de todos los mercados configurados."""
    if not settings.THEODDS_API_KEY:
        return []

    params = {
        "apiKey": settings.THEODDS_API_KEY,
        "regions": settings.THEODDS_REGIONS,
        "markets": settings.MARKETS,
        "oddsFormat": "decimal",
    }
    ttl = settings.THEODDS_CACHE_MINUTES * 60
    return _cached_get(f"{_BASE}/sports/{sport_key}/odds/", params, ttl)


def get_world_cup_events() -> list[dict]:
    return get_events_for_sport(_WORLD_CUP_KEY)


def get_theodds_sports() -> list[dict]:
    if not settings.THEODDS_API_KEY:
        return []
    params = {"apiKey": settings.THEODDS_API_KEY}
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{_BASE}/sports/", params=params)
        resp.raise_for_status()
        return resp.json()


# ── Normalización ─────────────────────────────────────────────────────────────

def _market_label(group_id: str) -> str:
    """Convierte el id interno del grupo en etiqueta legible."""
    if group_id in _MARKET_LABELS:
        return _MARKET_LABELS[group_id]
    if group_id.startswith("totals_"):
        point = group_id.replace("totals_", "")
        return f"Más/Menos {point} goles"
    return group_id


def _market_emoji(group_id: str) -> str:
    for key, emoji in MARKET_EMOJIS.items():
        if group_id.startswith(key):
            return emoji
    return "📊"


def extract_event_meta(event: dict) -> dict:
    """Extrae metadatos del evento (sin cuotas)."""
    commence_raw = event.get("commence_time", "")
    try:
        dt = datetime.fromisoformat(commence_raw.replace("Z", "+00:00"))
        commence_fmt = dt.strftime("%d/%m/%Y %H:%M UTC")
    except Exception:
        commence_fmt = commence_raw[:16] if commence_raw else ""

    return {
        "id": f"theodds_{event.get('id', '')}",
        "home_team": event.get("home_team", ""),
        "away_team": event.get("away_team", ""),
        "league": event.get("sport_title", ""),
        "sport": event.get("sport_key", ""),
        "commence_time": commence_fmt,
    }


def extract_market_groups(event: dict) -> list[tuple[str, str, str, list[dict]]]:
    """
    Agrupa las cuotas del evento por mercado.

    Devuelve lista de:
        (group_id, market_label, market_emoji, odds_items)

    Cada grupo es un mercado independiente que se analiza por separado.
    Ejemplo de grupos para un partido de fútbol:
        - ("h2h",        "1×2",              "🏆", [...])
        - ("totals_2.5", "Más/Menos 2.5 goles", "⚽", [...])
        - ("totals_3.5", "Más/Menos 3.5 goles", "⚽", [...])
        - ("btts",       "Ambos marcan",      "🥅", [...])
    """
    groups: dict[str, list[dict]] = {}

    for bm in event.get("bookmakers", []):
        bm_name = bm.get("title") or bm.get("key", "")
        for market in bm.get("markets", []):
            market_key = market.get("key", "")

            for outcome in market.get("outcomes", []):
                price = outcome.get("price", 0)
                name = outcome.get("name", "")
                point = outcome.get("point")  # presente en totals (2.5, 3.5...)

                if not name or not price or float(price) <= 1.0:
                    continue

                # Para totals, agrupar por línea: "totals_2.5", "totals_3.5"...
                if point is not None:
                    group_id = f"{market_key}_{point}"
                    full_name = f"{name} {point}"
                else:
                    group_id = market_key
                    full_name = name

                groups.setdefault(group_id, []).append({
                    "bookmaker": bm_name,
                    "market_key": market_key,
                    "selection_name": full_name,
                    "odds": float(price),
                    "is_available": True,
                    "source": "theodds",
                })

    return [
        (gid, _market_label(gid), _market_emoji(gid), items)
        for gid, items in groups.items()
    ]


# Alias de compatibilidad con código existente
def normalize_event(event: dict) -> tuple[dict, list[dict]]:
    """Compatibilidad: devuelve (meta, odds_items) solo del mercado h2h."""
    meta = extract_event_meta(event)
    for gid, _label, _emoji, items in extract_market_groups(event):
        if gid == "h2h":
            return meta, items
    return meta, []
