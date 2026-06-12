"""
Detección de 'middles' en el mercado de totales.

Un middle existe cuando se apuesta Over X.5 en una casa y Under (X+1).5 en
otra: si el partido acaba con exactamente X+1 goles, AMBAS ganan.

  Over 2.5 (casa A) + Under 3.5 (casa B):
    < 3 goles → Under 3.5 gana, Over 2.5 pierde  (resultado parcial)
    = 3 goles → AMBAS GANAN                       (middle golpea)
    > 3 goles → Over 2.5 gana, Under 3.5 pierde  (resultado parcial)

El riesgo real es bajo: en el peor caso se pierde solo el lado perdedor.
"""

import logging
from typing import Callable

from config.settings import settings
from data.models import MiddleOpportunity

logger = logging.getLogger(__name__)

_VALID_HALF_LINES = {0.5, 1.5, 2.5, 3.5, 4.5, 5.5}

# Fracción del bankroll apostada POR LADO (es apuesta de valor, no garantizada)
_STAKE_FRACTION = 0.05


def _collect_best_totals(
    event: dict,
    bookmaker_filter: Callable[[str], bool] | None,
) -> tuple[dict[float, tuple[str, float]], dict[float, tuple[str, float]]]:
    """
    Devuelve (overs, unders) con la mejor cuota por línea, respetando el filtro
    de bookmakers.

        overs  = {2.5: ("Bet365", 2.20), 3.5: ("Bwin", 1.95), ...}
        unders = {2.5: ("Unibet", 1.70), 3.5: ("Betway", 1.55), ...}
    """
    overs: dict[float, tuple[str, float]] = {}
    unders: dict[float, tuple[str, float]] = {}

    for bm in event.get("bookmakers", []):
        bm_name = bm.get("title") or bm.get("key", "")
        if bookmaker_filter and not bookmaker_filter(bm_name):
            continue

        for market in bm.get("markets", []):
            if market.get("key") != "totals":
                continue
            for outcome in market.get("outcomes", []):
                name = (outcome.get("name") or "").lower()
                price = outcome.get("price")
                point = outcome.get("point")
                if not name or price is None or point is None:
                    continue
                try:
                    price = float(price)
                    line = float(point)
                except (TypeError, ValueError):
                    continue
                if price <= 1.0 or line not in _VALID_HALF_LINES:
                    continue

                if "over" in name:
                    if line not in overs or price > overs[line][1]:
                        overs[line] = (bm_name, price)
                elif "under" in name:
                    if line not in unders or price > unders[line][1]:
                        unders[line] = (bm_name, price)

    return overs, unders


def find_middles(
    events: list[dict],
    bookmaker_filter: Callable[[str], bool] | None = None,
) -> list[MiddleOpportunity]:
    """
    Detecta middles en todos los eventos proporcionados.

    Solo requiere que Over X.5 y Under (X+1).5 sean de casas distintas.
    Si ambas son de la misma casa no es un middle real (la misma casa ya
    tiene ese margen incorporado).
    """
    from core.fetcher_theodds import extract_event_meta

    stake_each = round(settings.BANKROLL * _STAKE_FRACTION, 2)
    results: list[MiddleOpportunity] = []

    for event in events:
        meta = extract_event_meta(event)
        overs, unders = _collect_best_totals(event, bookmaker_filter)

        for over_line, (over_bm, over_odds) in overs.items():
            under_line = over_line + 1.0          # Over 2.5 → Under 3.5
            if under_line not in unders:
                continue

            under_bm, under_odds = unders[under_line]

            # El middle debe cruzar casas distintas para tener sentido
            if over_bm.lower() == under_bm.lower():
                continue

            middle_goal = int(over_line + 0.5)    # Over 2.5 → middle = 3 goles

            # Probabilidad implícita del middle según precios de mercado
            # (solapamiento entre ambas distribuciones implícitas)
            implied_prob = max(0.0, 1 / over_odds + 1 / under_odds - 1)
            if implied_prob < 0.04:               # descarta casos insignificantes
                continue

            # Resultados netos (stake_each apostado en cada lado)
            both_win   = round(stake_each * (over_odds - 1) + stake_each * (under_odds - 1), 2)
            over_wins  = round(stake_each * (over_odds - 1) - stake_each, 2)   # goles > under_line
            under_wins = round(stake_each * (under_odds - 1) - stake_each, 2)  # goles < over_line

            results.append(MiddleOpportunity(
                event_id=f"{meta['id']}_mid_{over_line}_{under_line}",
                event_name=f"{meta['home_team']} vs {meta['away_team']}",
                league=meta.get("league", ""),
                commence_time=meta.get("commence_time", ""),
                over_line=over_line,
                under_line=under_line,
                middle_goal=middle_goal,
                over_bookmaker=over_bm,
                under_bookmaker=under_bm,
                over_odds=over_odds,
                under_odds=under_odds,
                stake_each=stake_each,
                both_win_profit=both_win,
                over_wins_result=over_wins,
                under_wins_result=under_wins,
                implied_middle_prob=round(implied_prob * 100, 1),
            ))

    logger.info(f"Middles → {len(results)} oportunidades detectadas en {len(events)} eventos")
    return results
