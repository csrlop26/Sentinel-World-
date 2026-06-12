"""
Value Betting (+EV) mediante consenso de casas sharp.

Método:
  1. Identificar casas "sharp" en los datos (Pinnacle, Betfair Exchange, etc.)
     — sus cuotas reflejan la probabilidad real con márgenes muy bajos.
  2. Eliminamos su margen ("devigify") → probabilidad real P_real.
  3. Si una casa DGOJ ofrece odds tales que odds × P_real > 1 → valor.
  4. Stake: Quarter-Kelly (25% del Kelly completo, cap 10% bankroll).
  5. (Opcional) Segunda capa: modelo Poisson con datos de FootApi.
     Si Poisson confirma el edge → confidence="high".
"""

import logging
from typing import Callable

from config.settings import settings
from data.models import ValueBet

logger = logging.getLogger(__name__)

# Casas sharp en orden de prioridad (forman la referencia de mercado)
_SHARP_BOOKS = [
    "pinnacle",
    "betfair_ex_eu", "betfair exchange", "betfair_ex",
    "matchbook", "smarkets", "betcris",
]

_MIN_REF_OUTCOMES = 2   # mínimo de resultados para analizar un mercado


# ── Matemáticas ───────────────────────────────────────────────────────────────

def _overround(odds_map: dict[str, float]) -> float:
    return sum(1 / o for o in odds_map.values() if o > 1)


def _devigify(odds_map: dict[str, float]) -> dict[str, float]:
    """Elimina el margen del bookmaker y devuelve probabilidades reales."""
    imp = {k: 1 / v for k, v in odds_map.items() if v > 1}
    total = sum(imp.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in imp.items()}


def _quarter_kelly(true_prob: float, odds: float, bankroll: float) -> tuple[float, float]:
    """Devuelve (kelly_pct, stake_euros). Capeado al 10% del bankroll."""
    b = odds - 1
    if b <= 0:
        return 0.0, 0.0
    full_kelly = (b * true_prob - (1 - true_prob)) / b
    if full_kelly <= 0:
        return 0.0, 0.0
    kelly_f = min(full_kelly * 0.25, 0.10)
    return round(kelly_f * 100, 1), round(bankroll * kelly_f, 2)


# ── Extracción de cuotas ──────────────────────────────────────────────────────

def _collect_lines(event: dict, market_key: str) -> dict[frozenset, list[tuple]]:
    """
    Recopila cuotas agrupadas por "línea" (frozenset de nombres de outcome).

    Para h2h:    una sola línea {Home, Draw, Away}
    Para totals: una línea por punto, {Over 2.5, Under 2.5}, {Over 3.5, Under 3.5}, ...

    Devuelve {frozenset(outcomes): [(is_sharp, overround, bm_name, odds_map), ...]}
    """
    lines: dict[frozenset, list] = {}

    for bm in event.get("bookmakers", []):
        bm_name = bm.get("title") or bm.get("key", "")
        bm_low = bm_name.lower()
        is_sharp = any(sh in bm_low for sh in _SHARP_BOOKS)

        for market in bm.get("markets", []):
            if market.get("key") != market_key:
                continue

            # Agrupar por punto (totals) o todo junto (h2h)
            by_point: dict[float | None, dict[str, float]] = {}
            for outcome in market.get("outcomes", []):
                name = (outcome.get("name") or "").strip()
                price = outcome.get("price")
                point = outcome.get("point")
                if not name or not price or float(price) <= 1:
                    continue
                full_name = f"{name} {point}" if point is not None else name
                pt_key = float(point) if point is not None else None
                by_point.setdefault(pt_key, {})[full_name] = float(price)

            for odds_map in by_point.values():
                if len(odds_map) < _MIN_REF_OUTCOMES:
                    continue
                line_key = frozenset(odds_map.keys())
                entry = (is_sharp, _overround(odds_map), bm_name, odds_map)
                lines.setdefault(line_key, []).append(entry)

    return lines


def _consensus_probs(candidates: list[tuple]) -> tuple[dict[str, float], str]:
    """
    Probabilidades reales usando los 1-2 bookmakers más sharp disponibles.
    Si no hay sharps conocidos, usa los de menor overround.
    """
    if not candidates:
        return {}, ""

    sorted_c = sorted(candidates, key=lambda x: (not x[0], x[1]))
    ref = sorted_c[:2]  # máximo 2 casas de referencia

    combined: dict[str, float] = {}
    ref_names: list[str] = []

    for _, _, name, odds_map in ref:
        probs = _devigify(odds_map)
        ref_names.append(name.split()[0])
        for outcome, p in probs.items():
            combined[outcome] = combined.get(outcome, 0) + p

    n = len(ref)
    return {k: v / n for k, v in combined.items()}, " + ".join(ref_names)


# ── Punto de entrada ──────────────────────────────────────────────────────────

def find_value_bets(
    events: list[dict],
    bookmaker_filter: Callable[[str], bool] | None = None,
    min_edge: float | None = None,
) -> list[ValueBet]:
    """
    Detecta value bets comparando cuotas de casas blandas contra el consenso
    de las casas más sharp disponibles.

    bookmaker_filter aplica solo al lado de "apuesta recomendada" (dónde apostar).
    Para calcular la probabilidad de referencia se usan TODAS las casas.
    """
    from datetime import datetime, timedelta, timezone

    from core.fetcher_theodds import extract_event_meta
    from data.bankroll import get_bankroll

    if min_edge is None:
        min_edge = settings.MIN_VALUE_EDGE

    bankroll = get_bankroll()   # balance real con resultados registrados → Kelly compone
    results: list[ValueBet] = []
    skipped_far = 0

    # Solo partidos dentro de la ventana — las líneas lejanas son blandas
    # y el "edge" detectado a días vista suele ser ruido, no valor.
    cutoff = datetime.now(timezone.utc) + timedelta(hours=settings.VALUE_MAX_HOURS)

    market_labels = {
        "h2h":    "1×2",
        "totals": "Totales",
    }

    for event in events:
        commence_raw = event.get("commence_time", "")
        try:
            commence_dt = datetime.fromisoformat(commence_raw.replace("Z", "+00:00"))
            if commence_dt > cutoff:
                skipped_far += 1
                continue
        except Exception:
            pass  # sin fecha parseable → no filtrar

        meta = extract_event_meta(event)
        event_name = f"{meta['home_team']} vs {meta['away_team']}"

        for market_key, market_base_label in market_labels.items():
            lines = _collect_lines(event, market_key)

            for outcome_set, candidates in lines.items():
                true_probs, sharp_ref = _consensus_probs(candidates)
                if not true_probs:
                    continue

                has_sharp = any(c[0] for c in candidates)
                if settings.VALUE_REQUIRE_SHARP:
                    # Sin casa sharp la "probabilidad real" es solo consenso
                    # de casas blandas — demasiadas falsas señales.
                    if not has_sharp:
                        continue
                elif not has_sharp and len(candidates) < 3:
                    continue

                for is_sharp_bm, _, bm_name, odds_map in candidates:
                    if bookmaker_filter and not bookmaker_filter(bm_name):
                        continue

                    for outcome, odds in odds_map.items():
                        true_prob = true_probs.get(outcome)
                        if true_prob is None or true_prob <= 0:
                            continue

                        edge_pct = round((odds * true_prob - 1) * 100, 1)
                        if edge_pct < min_edge:
                            continue

                        kelly_pct, stake = _quarter_kelly(true_prob, odds, bankroll)
                        if stake <= 0:
                            continue

                        # Etiqueta de mercado legible
                        parts = outcome.split()
                        if len(parts) >= 2 and parts[0].lower() in ("over", "under"):
                            market_label = f"Más/Menos {parts[-1]} goles"
                        else:
                            market_label = market_base_label

                        results.append(ValueBet(
                            event_id=f"{meta['id']}_{market_key}_{outcome.replace(' ', '_')}",
                            event_name=event_name,
                            league=meta.get("league", ""),
                            commence_time=meta.get("commence_time", ""),
                            market=market_label,
                            outcome=outcome,
                            bookmaker=bm_name,
                            odds=odds,
                            true_prob=round(true_prob, 4),
                            edge_pct=edge_pct,
                            kelly_pct=kelly_pct,
                            stake=stake,
                            sharp_ref=sharp_ref,
                        ))

    raw_count = len(results)

    # Filtrar por stake mínimo (evita longshots con apuestas de céntimos)
    min_stake = settings.MIN_VALUE_STAKE
    results = [v for v in results if v.stake >= min_stake]
    stake_filtered = raw_count - len(results)

    # Dedup: mismo partido+mercado+outcome en varias casas → solo la de mejor cuota
    best: dict[str, ValueBet] = {}
    for vb in results:
        key = vb.event_id   # ya incluye event, market_key y outcome
        existing = best.get(key)
        if existing is None or vb.odds > existing.odds:
            best[key] = vb
    dedup_filtered = len(results) - len(best)
    results = list(best.values())

    results.sort(key=lambda v: -v.edge_pct)
    logger.info(
        f"Value bets → {raw_count} brutas · "
        f"-{stake_filtered} stake<€{min_stake:.2f} · "
        f"-{dedup_filtered} duplicadas · "
        f"= {len(results)} únicas  "
        f"(edge ≥ {min_edge}%, bankroll €{bankroll:.2f}, "
        f"{skipped_far} partidos >{settings.VALUE_MAX_HOURS}h descartados)"
    )

    if settings.RAPIDAPI_KEY and results:
        _enrich_with_poisson(results)

    return results


# ── Confirmación Poisson ──────────────────────────────────────────────────────

# Caché de sesión: (home_name_lower, away_name_lower) → PoissonProbs | None
_poisson_match_cache: dict[tuple[str, str], object] = {}


def _get_poisson_probs(home_name: str, away_name: str):
    """Devuelve PoissonProbs para el partido, o None si no hay datos."""
    key = (home_name.lower(), away_name.lower())
    if key in _poisson_match_cache:
        return _poisson_match_cache[key]

    try:
        from core.fetcher_footapi import get_team_id_by_name, get_team_recent_matches
        from core.poisson import calc_probs, estimate_lambdas, stats_from_recent_matches

        home_id = get_team_id_by_name(home_name)
        away_id = get_team_id_by_name(away_name)
        if not home_id or not away_id:
            _poisson_match_cache[key] = None
            return None

        home_matches = get_team_recent_matches(home_id)
        away_matches = get_team_recent_matches(away_id)

        home_stats = stats_from_recent_matches(home_id, home_name, home_matches)
        away_stats = stats_from_recent_matches(away_id, away_name, away_matches)

        if not home_stats or not away_stats:
            _poisson_match_cache[key] = None
            return None

        lh, la = estimate_lambdas(home_stats, away_stats)
        probs = calc_probs(lh, la)
        _poisson_match_cache[key] = probs
        logger.info(
            f"Poisson {home_name} vs {away_name}: "
            f"λ={lh:.2f}/{la:.2f}  "
            f"1×2={probs.home_win:.0%}/{probs.draw:.0%}/{probs.away_win:.0%}"
        )
        return probs

    except Exception as e:
        logger.debug(f"Poisson enrichment error ({home_name} vs {away_name}): {e}")
        _poisson_match_cache[key] = None
        return None


def _poisson_prob_for_outcome(probs, outcome: str, home_name: str, away_name: str) -> float | None:
    """Mapea el nombre de un outcome a su probabilidad Poisson."""
    out_low = outcome.lower().strip()
    home_low = home_name.lower()
    away_low = away_name.lower()

    if out_low == "draw":
        return probs.draw
    if out_low in (home_low, "home", "1"):
        return probs.home_win
    if out_low in (away_low, "away", "2"):
        return probs.away_win

    # Totals: "Over 2.5 2.5" o "Under 2.5 2.5" (el outcome incluye el punto)
    parts = out_low.split()
    if len(parts) >= 2:
        direction = parts[0]
        # El punto puede estar al final ("Over 2.5" o "Over 2.5 2.5")
        for part in reversed(parts[1:]):
            try:
                line = float(part)
                if direction == "over":
                    return probs.over.get(line)
                if direction == "under":
                    return probs.under.get(line)
            except ValueError:
                continue

    return None


def _enrich_with_poisson(value_bets: list[ValueBet]) -> None:
    """
    Enriquece cada ValueBet con la probabilidad Poisson del outcome.
    Marca confidence="high" cuando Poisson confirma el edge del consenso sharp.
    Opera in-place; no lanza excepciones — FootApi es opcional.
    """
    for vb in value_bets:
        try:
            parts = vb.event_name.split(" vs ", 1)
            if len(parts) != 2:
                continue
            home_name, away_name = parts

            probs = _get_poisson_probs(home_name, away_name)
            if probs is None:
                continue

            p_poisson = _poisson_prob_for_outcome(probs, vb.outcome, home_name, away_name)
            if p_poisson is None:
                continue

            vb.poisson_prob = round(p_poisson, 4)

            # Confirmar si Poisson también ve edge y no discrepa demasiado del consenso sharp
            poisson_edge = vb.odds * p_poisson - 1
            prob_diff = abs(p_poisson - vb.true_prob)
            if poisson_edge > 0 and prob_diff <= 0.10:
                vb.confidence = "high"
            else:
                vb.confidence = "normal"

        except Exception as e:
            logger.debug(f"Poisson enrich error ({vb.event_name}): {e}")
