import logging
from typing import Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_HEADERS = {"X-API-Key": settings.ODDS_API_KEY}
_TIMEOUT = 15.0


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{settings.ODDS_API_BASE_URL}{path}"
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(url, headers=_HEADERS, params=params or {})
        resp.raise_for_status()
        return resp.json()


def get_sports() -> list[str]:
    return _get("/sports").get("items", [])


def get_leagues(sport: str = "") -> list[str]:
    params = {"sport": sport} if sport else {}
    return _get("/leagues", params).get("items", [])


def get_events(
    sport: str = "",
    league: str = "",
    limit: int = 200,
) -> list[dict]:
    params: dict = {"limit": limit}
    if sport:
        params["sport"] = sport
    if league:
        params["league"] = league
    return _get("/events", params).get("items", [])


def get_event(event_id: str) -> dict:
    return _get(f"/events/{event_id}")


def get_odds_snapshot(event_id: str) -> list[dict]:
    params = {"limit": 1000, "price_fields": "odds"}
    return _get(f"/events/{event_id}/odds/snapshot", params).get("items", [])


def get_arb_bets(event_id: Optional[str] = None) -> list[dict]:
    params: dict = {"strategies": "arbitrage", "limit": 500}
    if event_id:
        params["event_id"] = event_id
    return _get("/bets/snapshot", params).get("items", [])
