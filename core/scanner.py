import logging
from datetime import datetime, timezone

from config.settings import settings
from core.calculator import build_legs, calculate_arb, find_best_odds
from core.fetcher import get_arb_bets, get_event, get_events, get_odds_snapshot
from data.models import ArbOpportunity

logger = logging.getLogger(__name__)


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


def _check_event(event_id: str, event_data: dict | None) -> ArbOpportunity | None:
    try:
        odds_items = get_odds_snapshot(event_id)
    except Exception as e:
        logger.warning(f"Odds snapshot failed for {event_id}: {e}")
        return None

    if not odds_items:
        return None

    best_odds = find_best_odds(odds_items)
    if len(best_odds) < 2:
        return None

    margin_pct, stakes = calculate_arb(best_odds, settings.BANKROLL)

    if margin_pct < settings.MIN_ARB_MARGIN:
        return None

    if margin_pct > settings.MAX_ARB_MARGIN:
        logger.warning(f"Suspicious margin {margin_pct:.2f}% on {event_id} — skipping")
        return None

    if not event_data:
        try:
            event_data = get_event(event_id)
        except Exception:
            event_data = {"id": event_id}

    legs = build_legs(stakes)

    return ArbOpportunity(
        event_id=event_id,
        event_name=_event_name(event_data),
        sport=event_data.get("sport") or settings.SPORT_FILTER,
        league=event_data.get("league") or "",
        commence_time=_commence_time(event_data),
        legs=legs,
        margin_pct=round(margin_pct, 2),
        bankroll=settings.BANKROLL,
        min_profit=round(settings.BANKROLL * margin_pct / 100, 2),
    )


def scan() -> list[ArbOpportunity]:
    """
    Main scan: combines /bets/snapshot (fast arb flags) with direct event scanning.
    Returns list of confirmed arb opportunities above MIN_ARB_MARGIN.
    """
    event_ids: set[str] = set()
    event_cache: dict[str, dict] = {}

    # ── Strategy 1: grab pre-flagged arb bets from the API ──────────────────
    try:
        arb_bets = get_arb_bets()
        for bet in arb_bets:
            eid = bet.get("event_id")
            if eid:
                event_ids.add(eid)
        logger.info(f"/bets/snapshot returned {len(arb_bets)} legs on {len(event_ids)} events")
    except Exception as e:
        logger.warning(f"/bets/snapshot unavailable: {e}")

    # ── Strategy 2: scan configured sport/league directly ───────────────────
    try:
        events = get_events(
            sport=settings.SPORT_FILTER,
            league=settings.LEAGUE_FILTER,
        )
        for ev in events:
            eid = ev.get("id")
            if eid and _matches_league_filter(ev):
                event_ids.add(eid)
                event_cache[eid] = ev
        logger.info(f"Direct event scan found {len(events)} events matching filter")
    except Exception as e:
        logger.warning(f"Event list unavailable: {e}")

    if not event_ids:
        logger.info("No events to check")
        return []

    opportunities: list[ArbOpportunity] = []
    for eid in event_ids:
        opp = _check_event(eid, event_cache.get(eid))
        if opp:
            opportunities.append(opp)

    return opportunities
