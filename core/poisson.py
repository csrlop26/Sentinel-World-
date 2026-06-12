"""
Modelo de Poisson para fútbol.

Dado que los goles en fútbol siguen aproximadamente una distribución
de Poisson independiente por equipo, podemos estimar la probabilidad
de cualquier resultado a partir de dos parámetros:

  λ_home = goles esperados del equipo local
  λ_away = goles esperados del equipo visitante

Proceso de estimación de λ:
  1. Calcular la "media de liga" (= media del Mundial / internacionales)
  2. Por equipo: attack_strength = goals_scored / league_avg_scored
                 defense_strength = goals_conceded / league_avg_conceded
  3. λ_A = attack_A × defense_B × league_avg_scored_per_game

Con λ_home y λ_away se genera la matriz de resultados y se calculan
todas las probabilidades de mercado.
"""

import math
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_MAX_GOALS = 8    # truncar la distribución a 8 goles por equipo
_WC_AVG_GOALS = 2.7  # media histórica de goles por partido en Mundiales


@dataclass
class TeamStats:
    team_id: int
    team_name: str
    goals_per_game: float       # ataque
    conceded_per_game: float    # defensa
    n_matches: int


@dataclass
class PoissonProbs:
    home_win: float
    draw: float
    away_win: float
    over: dict[float, float]    # {1.5: P(over 1.5), 2.5: ..., 3.5: ...}
    under: dict[float, float]   # {1.5: P(under 1.5), ...}
    lambda_home: float
    lambda_away: float


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _score_matrix(lam_home: float, lam_away: float) -> dict[tuple[int, int], float]:
    """Matriz de probabilidades de resultado exacto (i goles local, j visitante)."""
    matrix = {}
    for i in range(_MAX_GOALS + 1):
        p_i = _poisson_pmf(i, lam_home)
        for j in range(_MAX_GOALS + 1):
            matrix[(i, j)] = p_i * _poisson_pmf(j, lam_away)
    return matrix


def calc_probs(lam_home: float, lam_away: float) -> PoissonProbs:
    """Calcula todas las probabilidades de mercado a partir de los λ."""
    matrix = _score_matrix(lam_home, lam_away)

    home_win = sum(p for (i, j), p in matrix.items() if i > j)
    draw     = sum(p for (i, j), p in matrix.items() if i == j)
    away_win = sum(p for (i, j), p in matrix.items() if i < j)

    over  = {}
    under = {}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        ov = sum(p for (i, j), p in matrix.items() if i + j > line)
        over[line]  = ov
        under[line] = 1 - ov

    return PoissonProbs(
        home_win=round(home_win, 4),
        draw=round(draw, 4),
        away_win=round(away_win, 4),
        over={k: round(v, 4) for k, v in over.items()},
        under={k: round(v, 4) for k, v in under.items()},
        lambda_home=round(lam_home, 3),
        lambda_away=round(lam_away, 3),
    )


def estimate_lambdas(
    home: TeamStats,
    away: TeamStats,
    avg_goals: float = _WC_AVG_GOALS,
) -> tuple[float, float]:
    """
    Estima λ_home y λ_away usando el modelo de fuerza relativa.

    avg_goals es la media de goles por equipo por partido en el contexto
    del torneo (para el Mundial usar ~1.35, que es WC_AVG / 2).
    """
    half_avg = avg_goals / 2.0

    attack_home  = home.goals_per_game / half_avg if half_avg else 1.0
    defense_home = home.conceded_per_game / half_avg if half_avg else 1.0
    attack_away  = away.goals_per_game / half_avg if half_avg else 1.0
    defense_away = away.conceded_per_game / half_avg if half_avg else 1.0

    lam_home = attack_home * defense_away * half_avg
    lam_away = attack_away * defense_home * half_avg

    # Limitar lambdas a valores razonables para fútbol
    lam_home = max(0.3, min(4.0, lam_home))
    lam_away = max(0.3, min(4.0, lam_away))

    return lam_home, lam_away


def stats_from_recent_matches(
    team_id: int,
    team_name: str,
    matches: list[dict],
    limit: int = 10,
) -> TeamStats | None:
    """
    Calcula TeamStats a partir de los partidos recientes de FootApi.

    matches: lista de eventos de FootApi con scores.homeScore / awayScore
    """
    goals_for = 0
    goals_against = 0
    count = 0

    for match in matches[:limit]:
        home_team = match.get("homeTeam", {})
        away_team = match.get("awayTeam", {})
        home_score = match.get("homeScore", {})
        away_score = match.get("awayScore", {})

        if not home_score or not away_score:
            continue

        # Partidos finalizados únicamente
        status = (match.get("status", {}).get("type") or "").lower()
        if status not in ("finished", "ft", "aet", "pen"):
            continue

        gh = home_score.get("current") or home_score.get("normaltime", 0)
        ga = away_score.get("current") or away_score.get("normaltime", 0)
        if gh is None or ga is None:
            continue

        is_home = home_team.get("id") == team_id
        goals_for     += gh if is_home else ga
        goals_against += ga if is_home else gh
        count += 1

    if count < 3:
        logger.debug(f"Poisson: datos insuficientes para {team_name} ({count} partidos)")
        return None

    return TeamStats(
        team_id=team_id,
        team_name=team_name,
        goals_per_game=round(goals_for / count, 3),
        conceded_per_game=round(goals_against / count, 3),
        n_matches=count,
    )
