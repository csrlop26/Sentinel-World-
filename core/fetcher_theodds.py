"""
Cliente para The Odds API (the-odds-api.com).

Free plan: 500 req/mes. Cada llamada a /odds usa:
  [número de markets] × [número de regiones] cuota.
Con markets=h2h y regions=eu,uk → 2 cuota por llamada.

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


def _cached_get(url: str, params: dict, ttl_seconds: int) -> list:
    cache_key = url + str(sorted(params.items()))
    now = time.time()
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if now - ts < ttl_seconds:
            age = int(now - ts)
            logger.debug(f"TheOddsAPI cache hit ({age}s old): {url}")
            return data

    with httpx.Client(timeout=15) as client:
        resp = client.get(url, params=params)
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        logger.info(f"TheOddsAPI → {resp.status_code} | cuota usada: {used} | restante: {remaining}")
        resp.raise_for_status()
        data = resp.json()

    _cache[cache_key] = (now, data)
    return data


def get_world_cup_events() -> list[dict]:
    """
    Devuelve todos los partidos del Mundial con cuotas de todos los bookmakers
    disponibles en las regiones configuradas. Resultado cacheado.
    """
    if not settings.THEODDS_API_KEY:
        return []

    params = {
        "apiKey": settings.THEODDS_API_KEY,
        "regions": settings.THEODDS_REGIONS,
        "markets": "h2h",
        "oddsFormat": "decimal",
    }
    ttl = settings.THEODDS_CACHE_MINUTES * 60
    return _cached_get(
        f"{_BASE}/sports/{_WORLD_CUP_KEY}/odds/",
        params,
        ttl,
    )


def get_theodds_sports() -> list[dict]:
    """Lista de deportes disponibles (no consume cuota)."""
    if not settings.THEODDS_API_KEY:
        return []
    params = {"apiKey": settings.THEODDS_API_KEY}
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{_BASE}/sports/", params=params)
        resp.raise_for_status()
        return resp.json()


def normalize_event(event: dict) -> tuple[dict, list[dict]]:
    """
    Convierte un evento de The Odds API al formato interno común:
    - event_meta: dict con home_team, away_team, league, sport, start_time
    - odds_items: list de dicts compatibles con core.calculator.find_best_odds()
    """
    commence_raw = event.get("commence_time", "")
    try:
        dt = datetime.fromisoformat(commence_raw.replace("Z", "+00:00"))
        commence_fmt = dt.strftime("%d/%m/%Y %H:%M UTC")
    except Exception:
        commence_fmt = commence_raw[:16] if commence_raw else ""

    event_meta = {
        "id": f"theodds_{event.get('id', '')}",
        "home_team": event.get("home_team", ""),
        "away_team": event.get("away_team", ""),
        "league": event.get("sport_title", "FIFA World Cup 2026"),
        "sport": event.get("sport_key", "soccer"),
        "commence_time": commence_fmt,
    }

    odds_items: list[dict] = []
    for bm in event.get("bookmakers", []):
        bm_name = bm.get("title") or bm.get("key", "")
        for market in bm.get("markets", []):
            if market.get("key") not in ("h2h", "1x2"):
                continue
            for outcome in market.get("outcomes", []):
                price = outcome.get("price", 0)
                name = outcome.get("name", "")
                if name and price and price > 1.0:
                    odds_items.append({
                        "bookmaker": bm_name,
                        "market_key": "h2h",
                        "selection_name": name,
                        "odds": float(price),
                        "is_available": True,
                        "source": "theodds",
                    })

    return event_meta, odds_items
