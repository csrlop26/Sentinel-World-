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

# Mercados que funcionan por sport_key (descubiertos en runtime para evitar 422)
_working_markets: dict[str, str] = {}

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

# Orden de fallback si los mercados configurados dan 422
_MARKET_FALLBACKS = ["h2h,totals,btts", "h2h,totals", "h2h"]


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
    """
    Devuelve todos los eventos de un deporte con cuotas.
    Si los mercados configurados dan 422 (no soportados), reintenta
    automáticamente con combinaciones más simples para no gastar cuota extra.
    El mercado que funciona se guarda en memoria para el resto de la sesión.
    """
    if not settings.THEODDS_API_KEY:
        return []

    ttl = settings.THEODDS_CACHE_MINUTES * 60
    url = f"{_BASE}/sports/{sport_key}/odds/"
    configured = settings.MARKETS

    # Si ya descubrimos qué mercados soporta este deporte, usarlos directamente
    if sport_key in _working_markets:
        markets_to_try = [_working_markets[sport_key]]
    else:
        # Probar los configurados; si dan 422, ir reduciendo
        markets_to_try = [configured]
        for fb in _MARKET_FALLBACKS:
            if fb != configured and fb not in markets_to_try:
                markets_to_try.append(fb)

    for markets in markets_to_try:
        params = {
            "apiKey": settings.THEODDS_API_KEY,
            "regions": settings.THEODDS_REGIONS,
            "markets": markets,
            "oddsFormat": "decimal",
        }
        try:
            data = _cached_get(url, params, ttl)
            if markets != configured:
                logger.info(
                    f"TheOddsAPI: '{sport_key}' no soporta '{configured}' — "
                    f"usando mercados '{markets}'"
                )
            _working_markets[sport_key] = markets
            return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:
                logger.warning(
                    f"TheOddsAPI 422 con markets='{markets}' para '{sport_key}'"
                    + (" — reintentando sin btts" if "btts" in markets else "")
                )
                continue
            raise

    logger.warning(f"TheOddsAPI: sin mercados disponibles para '{sport_key}'")
    return []


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


def get_active_soccer_sports() -> list[dict]:
    """Devuelve los deportes de fútbol activos según The Odds API."""
    sports = get_theodds_sports()
    return [
        s for s in sports
        if (s.get("group") or "").lower() == "soccer"
    ]


def find_world_cup_key() -> str:
    """
    Busca el sport key correcto del Mundial entre los deportes activos.
    Devuelve 'soccer_fifa_world_cup' como fallback si no lo encuentra.
    """
    try:
        sports = get_active_soccer_sports()
        for s in sports:
            key = s.get("key", "")
            title = (s.get("title") or "").lower()
            if "world cup" in title or "world_cup" in key or "fifa_world" in key:
                return key
    except Exception as e:
        logger.warning(f"Error buscando sport key del Mundial: {e}")
    return _WORLD_CUP_KEY


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
