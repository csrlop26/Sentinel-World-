import logging
from datetime import datetime, timezone
from typing import Callable

import httpx

from config.bookmakers import is_spain_licensed
from config.settings import settings
from core.calculator import build_legs, calculate_arb, find_best_odds
from core.fetcher import get_arb_bets, get_event, get_events, get_odds_snapshot
from data.models import ArbOpportunity

logger = logging.getLogger(__name__)

# Circuit breaker: si odds-api.net devuelve 401/403, se desactiva en toda la sesión
_oddsnet_disabled = False


# ── Helpers compartidos ───────────────────────────────────────────────────────

def _matches_league_filter(event: dict) -> bool:
    if not settings.LEAGUE_FILTER:
        return True
    league = (event.get("league") or "").lower()
    sport = (event.get("sport") or "").lower()
    needle = settings.LEAGUE_FILTER.lower()
    return needle in league or needle in sport


def _event_name(event: dict) -> str:
    home = event.get("home_team") or event.get("home") or event.get("team1") or ""
    away = event.get("away_team") or event.get("away") or event.get("team2") or ""
    if home and away:
        return f"{home} vs {away}"
    return event.get("name") or event.get("title") or event.get("id", "Unknown")


def _commence_time(event: dict) -> str:
    ts = event.get("start_time") or event.get("commence_time") or event.get("date") or ""
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%d/%m/%Y %H:%M UTC")
    return str(ts)[:19] if ts else ""


def _event_sig(opp: ArbOpportunity) -> str:
    """Firma normalizada para deduplicar el mismo partido entre fuentes distintas."""
    return opp.event_name.lower().replace(" ", "").replace("_", "")


def _bookmaker_filter() -> Callable[[str], bool] | None:
    """Devuelve el filtro de bookmakers activo según configuración."""
    if settings.SPAIN_ONLY:
        return is_spain_licensed
    return None


def _build_opp(
    event_id: str,
    event_data: dict,
    odds_items: list[dict],
) -> ArbOpportunity | None:
    best_odds = find_best_odds(odds_items, bookmaker_filter=_bookmaker_filter())
    if len(best_odds) < 2:
        return None

    margin_pct, stakes = calculate_arb(best_odds, settings.BANKROLL)

    if margin_pct < settings.MIN_ARB_MARGIN:
        return None
    if margin_pct > settings.MAX_ARB_MARGIN:
        logger.warning(f"Margen sospechoso {margin_pct:.2f}% en {event_id} — ignorado")
        return None

    return ArbOpportunity(
        event_id=event_id,
        event_name=_event_name(event_data),
        sport=event_data.get("sport") or settings.SPORT_FILTER,
        league=event_data.get("league") or "",
        commence_time=(
            event_data.get("commence_time")
            or _commence_time(event_data)
        ),
        legs=build_legs(stakes),
        margin_pct=round(margin_pct, 2),
        bankroll=settings.BANKROLL,
        min_profit=round(settings.BANKROLL * margin_pct / 100, 2),
    )


# ── Source A: The Odds API ────────────────────────────────────────────────────

def _scan_theodds() -> list[ArbOpportunity]:
    """
    Escanea todos los partidos del Mundial desde The Odds API.
    Una sola llamada HTTP devuelve todos los eventos con TODOS los bookmakers.
    """
    from core.fetcher_theodds import get_world_cup_events, normalize_event

    try:
        events = get_world_cup_events()
    except Exception as e:
        logger.warning(f"TheOddsAPI no disponible: {e}")
        return []

    opportunities: list[ArbOpportunity] = []
    for event in events:
        meta, odds_items = normalize_event(event)
        opp = _build_opp(meta["id"], meta, odds_items)
        if opp:
            opportunities.append(opp)

    logger.info(f"TheOddsAPI → {len(events)} partidos revisados, {len(opportunities)} oportunidades")
    return opportunities


# ── Source B: odds-api.net ────────────────────────────────────────────────────

def _is_auth_error(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403)


def _scan_oddsnet() -> list[ArbOpportunity]:
    """
    Escanea via odds-api.net. Si devuelve 401/403 se desactiva para toda
    la sesión (circuit breaker) y no vuelve a intentarlo.
    """
    global _oddsnet_disabled

    if _oddsnet_disabled:
        return []

    event_ids: set[str] = set()
    event_cache: dict[str, dict] = {}

    try:
        arb_bets = get_arb_bets()
        for bet in arb_bets:
            eid = bet.get("event_id")
            if eid:
                event_ids.add(eid)
        logger.info(f"odds-api.net /bets/snapshot → {len(arb_bets)} señales en {len(event_ids)} eventos")
    except Exception as e:
        if _is_auth_error(e):
            _oddsnet_disabled = True
            logger.warning("odds-api.net: key inválida (401) — desactivado para esta sesión. "
                           "Revisa ODDS_API_KEY en .env o déjala vacía si no la usas.")
            return []
        logger.warning(f"odds-api.net /bets/snapshot no disponible: {e}")

    try:
        events = get_events(sport=settings.SPORT_FILTER, league=settings.LEAGUE_FILTER)
        for ev in events:
            eid = ev.get("id")
            if eid and _matches_league_filter(ev):
                event_ids.add(eid)
                event_cache[eid] = ev
        logger.info(f"odds-api.net eventos directos → {len(events)} encontrados")
    except Exception as e:
        if _is_auth_error(e):
            _oddsnet_disabled = True
            logger.warning("odds-api.net: key inválida (401) — desactivado para esta sesión.")
            return []
        logger.warning(f"odds-api.net /events no disponible: {e}")

    if not event_ids:
        return []

    opportunities: list[ArbOpportunity] = []
    for eid in event_ids:
        try:
            odds_items = get_odds_snapshot(eid)
        except Exception as e:
            if _is_auth_error(e):
                _oddsnet_disabled = True
                logger.warning("odds-api.net: key inválida (401) — desactivado para esta sesión.")
                return opportunities
            logger.warning(f"Odds snapshot fallido para {eid}: {e}")
            continue

        if not odds_items:
            continue

        ev_data = event_cache.get(eid)
        if not ev_data:
            try:
                ev_data = get_event(eid)
            except Exception:
                ev_data = {"id": eid}

        opp = _build_opp(eid, ev_data, odds_items)
        if opp:
            opportunities.append(opp)

    logger.info(f"odds-api.net → {len(event_ids)} eventos revisados, {len(opportunities)} oportunidades")
    return opportunities


# ── Scan principal ────────────────────────────────────────────────────────────

def scan() -> list[ArbOpportunity]:
    """
    Escaneo combinado de ambas fuentes.
    The Odds API va primero (más bookmakers). Las oportunidades de odds-api.net
    se añaden solo si no se detectó ya el mismo partido desde The Odds API.
    """
    opportunities: list[ArbOpportunity] = []
    seen_sigs: set[str] = set()

    # ── The Odds API (fuente principal si está configurada) ──────────────────
    if settings.THEODDS_API_KEY:
        for opp in _scan_theodds():
            sig = _event_sig(opp)
            opportunities.append(opp)
            seen_sigs.add(sig)
    else:
        logger.info("TheOddsAPI no configurada — usando solo odds-api.net")

    # ── odds-api.net (complemento / fallback) ────────────────────────────────
    for opp in _scan_oddsnet():
        sig = _event_sig(opp)
        if sig not in seen_sigs:          # evita doble alerta del mismo partido
            opportunities.append(opp)
            seen_sigs.add(sig)

    return opportunities
