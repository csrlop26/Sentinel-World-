"""
Cliente para FootApi (REcodeX / Sofascore) via RapidAPI.

Endpoints confirmados:
  /tournament/{id}                                         → info del torneo
  /tournament/{id}/seasons                                 → temporadas
  /tournament/{id}/season/{sid}/rounds                     → rondas disponibles
  /tournament/{id}/season/{sid}/events/round/{roundNum}    → partidos por ronda
  /team/{teamId}/events/last/{page}                        → últimos partidos del equipo
  /team/{teamId}/statistics/season/{sid}/tournament/{tid}  → stats del equipo
  /search/teams/{query}                                    → buscar equipo por nombre

Las rutas /events/next y /events/last devuelven 404 en WC 2026 —
FootApi usa rondas (group stage round 1, 2, 3...).

Free plan: 100 req/día (usa el caché).
"""

import logging
import time
import urllib.parse

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_BASE = "https://footapi7.p.rapidapi.com/api"
_HOST = "footapi7.p.rapidapi.com"

WC_TOURNAMENT_ID = 16

_cache: dict[str, tuple[float, object]] = {}
_TTL = 300          # 5 minutos por defecto
_TTL_STATIC = 3600  # 1 hora para datos que no cambian

# Caché de nombre → team_id para no gastar req en cada búsqueda
_team_id_cache: dict[str, int] = {}

# Circuit breaker: si el endpoint /team/{id}/events/last/ da 404 repetidamente
# (plan free no incluye historial de partidos), desactivar para la sesión.
_team_events_available: bool = True
_team_events_404_count: int = 0
_TEAM_EVENTS_404_THRESHOLD = 3  # tras 3 equipos sin datos → desactivar


def _get(path: str, ttl: int = _TTL) -> dict | list | None:
    """GET autenticado con caché en memoria. Los 404 también se cachean."""
    if not settings.RAPIDAPI_KEY:
        return None

    now = time.time()
    if path in _cache:
        ts, data = _cache[path]
        if now - ts < ttl:
            return data

    headers = {
        "X-RapidAPI-Key":  settings.RAPIDAPI_KEY,
        "X-RapidAPI-Host": _HOST,
    }
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{_BASE}{path}", headers=headers)
            logger.debug(f"FootApi {resp.status_code} → {path}")
            if resp.status_code == 404:
                # Cachear el 404 para no repetir la petición (plan free bloquea muchos endpoints)
                _cache[path] = (now, None)
                return None
            resp.raise_for_status()
            data = resp.json()
            _cache[path] = (now, data)
            return data
    except httpx.HTTPStatusError as e:
        logger.warning(f"FootApi HTTP {e.response.status_code}: {path}")
        return None
    except Exception as e:
        logger.warning(f"FootApi error ({path}): {e}")
        return None


# ── Torneos ───────────────────────────────────────────────────────────────────

def get_tournament_info(tournament_id: int = WC_TOURNAMENT_ID) -> dict | None:
    data = _get(f"/tournament/{tournament_id}", ttl=_TTL_STATIC)
    if isinstance(data, dict):
        return data.get("uniqueTournament") or data
    return None


def get_seasons(tournament_id: int = WC_TOURNAMENT_ID) -> list[dict]:
    data = _get(f"/tournament/{tournament_id}/seasons", ttl=_TTL_STATIC)
    if isinstance(data, dict):
        return data.get("seasons", [])
    return []


def get_current_season_id(tournament_id: int = WC_TOURNAMENT_ID) -> int | None:
    seasons = get_seasons(tournament_id)
    return seasons[0].get("id") if seasons else None


def get_rounds(
    tournament_id: int = WC_TOURNAMENT_ID,
    season_id: int | None = None,
) -> list[dict]:
    """Rondas disponibles del torneo (Group Stage R1, R2, R3, Round of 16…)."""
    sid = season_id or get_current_season_id(tournament_id)
    if not sid:
        return []
    data = _get(f"/tournament/{tournament_id}/season/{sid}/rounds", ttl=_TTL_STATIC)
    if isinstance(data, dict):
        return data.get("rounds", [])
    return []


# ── Partidos ──────────────────────────────────────────────────────────────────

def get_events_by_round(
    round_num: int,
    tournament_id: int = WC_TOURNAMENT_ID,
    season_id: int | None = None,
) -> list[dict]:
    """Partidos de una ronda concreta."""
    sid = season_id or get_current_season_id(tournament_id)
    if not sid:
        return []
    data = _get(f"/tournament/{tournament_id}/season/{sid}/events/round/{round_num}")
    if isinstance(data, dict):
        return data.get("events", [])
    return []


def get_upcoming_events(
    tournament_id: int = WC_TOURNAMENT_ID,
    season_id: int | None = None,
) -> list[dict]:
    """
    Próximos partidos del torneo.
    Intenta /events/next/{page} primero; si devuelve vacío o None,
    recorre rondas disponibles y filtra los no iniciados.
    """
    sid = season_id or get_current_season_id(tournament_id)
    if not sid:
        return []

    # Intento directo (puede funcionar en otras competiciones)
    data = _get(f"/tournament/{tournament_id}/season/{sid}/events/next/0")
    if isinstance(data, dict):
        events = data.get("events", [])
        if events:
            return events

    # Fallback: rondas → filtrar partidos no iniciados
    rounds = get_rounds(tournament_id, sid)
    upcoming: list[dict] = []
    for r in rounds:
        rn = r.get("round")
        if rn is None:
            continue
        for ev in get_events_by_round(rn, tournament_id, sid):
            status_type = (ev.get("status", {}).get("type") or "").lower()
            if status_type in ("notstarted", "scheduled", ""):
                upcoming.append(ev)

    return upcoming


def get_recent_events(
    tournament_id: int = WC_TOURNAMENT_ID,
    season_id: int | None = None,
) -> list[dict]:
    """
    Partidos recientes del torneo (finalizados).
    Mismo patrón: directo o por rondas.
    """
    sid = season_id or get_current_season_id(tournament_id)
    if not sid:
        return []

    data = _get(f"/tournament/{tournament_id}/season/{sid}/events/last/0")
    if isinstance(data, dict):
        events = data.get("events", [])
        if events:
            return events

    rounds = get_rounds(tournament_id, sid)
    finished: list[dict] = []
    for r in rounds:
        rn = r.get("round")
        if rn is None:
            continue
        for ev in get_events_by_round(rn, tournament_id, sid):
            status_type = (ev.get("status", {}).get("type") or "").lower()
            if status_type in ("finished", "ft", "aet", "pen"):
                finished.append(ev)

    return finished


def get_team_recent_matches(team_id: int, page: int = 0) -> list[dict]:
    """Últimos ~10 partidos del equipo. Devuelve [] si el plan free no incluye estos datos."""
    global _team_events_available, _team_events_404_count

    if not _team_events_available:
        return []

    data = _get(f"/team/{team_id}/events/last/{page}")
    if isinstance(data, dict):
        events = data.get("events", [])
        if events:
            _team_events_404_count = 0  # reset — hay datos
        return events

    # None puede ser 404 (bloqueado por plan) o error de red
    _team_events_404_count += 1
    if _team_events_404_count >= _TEAM_EVENTS_404_THRESHOLD:
        _team_events_available = False
        logger.warning(
            "FootApi: /team/events/last devuelve 404 repetidamente — "
            "historial de partidos no disponible en plan free. "
            "Poisson desactivado para esta sesión."
        )
    return []


# ── Equipos ───────────────────────────────────────────────────────────────────

def search_team(name: str) -> dict | None:
    """
    Busca un equipo por nombre usando la búsqueda general (/search/{query}).
    Filtra por deporte fútbol si hay información disponible.
    """
    query = urllib.parse.quote(name)
    data = _get(f"/search/{query}", ttl=_TTL_STATIC)
    if not isinstance(data, dict):
        return None

    # La respuesta puede tener varias estructuras según la versión de la API
    teams: list[dict] = data.get("teams", [])
    if not teams:
        results = data.get("results", [])
        teams = [
            r.get("entity", r)
            for r in results
            if r.get("type") in ("team", "uniqueTeam", None)
        ]

    if not teams:
        return None

    # Preferir equipos de fútbol (sport.id == 1 en Sofascore)
    for team in teams:
        sport = team.get("sport")
        if isinstance(sport, dict):
            if sport.get("id") == 1 or (sport.get("name") or "").lower() == "football":
                return team
        elif sport is None:
            return team  # sin info de deporte → asumir fútbol

    return teams[0]


def get_team_id_by_name(name: str) -> int | None:
    """
    Devuelve el team_id de FootApi para un nombre de equipo.
    Resultado cacheado en memoria para evitar req repetidas.
    """
    normalized = name.lower().strip()
    if normalized in _team_id_cache:
        return _team_id_cache[normalized]

    team = search_team(name)
    if team:
        tid = team.get("id")
        if tid:
            _team_id_cache[normalized] = int(tid)
            logger.info(f"FootApi team '{name}' → ID {tid} ({team.get('name', '?')})")
            return int(tid)

    logger.warning(f"FootApi: equipo '{name}' no encontrado")
    return None


# ── Estadísticas ──────────────────────────────────────────────────────────────

def get_team_stats(
    team_id: int,
    tournament_id: int = WC_TOURNAMENT_ID,
    season_id: int | None = None,
) -> dict | None:
    sid = season_id or get_current_season_id(tournament_id)
    if not sid:
        return None
    data = _get(
        f"/team/{team_id}/statistics/season/{sid}/tournament/{tournament_id}",
        ttl=900,
    )
    if isinstance(data, dict):
        return data.get("statistics") or data
    return None


# ── Diagnóstico ───────────────────────────────────────────────────────────────

def diagnose() -> dict:
    result: dict = {}

    if not settings.RAPIDAPI_KEY:
        result["error"] = "RAPIDAPI_KEY no configurada en .env"
        return result

    info = get_tournament_info(WC_TOURNAMENT_ID)
    result["tournament"] = info.get("name") if info else "ERROR"

    sid = get_current_season_id(WC_TOURNAMENT_ID)
    result["season_id"] = sid

    if sid:
        rounds = get_rounds(WC_TOURNAMENT_ID, sid)
        result["rounds_available"] = len(rounds)
        result["round_numbers"] = [r.get("round") for r in rounds[:8]]

        upcoming = get_upcoming_events(WC_TOURNAMENT_ID, sid)
        result["upcoming_matches"] = len(upcoming)
        recent = get_recent_events(WC_TOURNAMENT_ID, sid)
        result["recent_matches"] = len(recent)

        if upcoming:
            ev = upcoming[0]
            home = ev.get("homeTeam", {})
            away = ev.get("awayTeam", {})
            result["next_match"] = f"{home.get('name')} vs {away.get('name')}"
            result["home_team_id"] = home.get("id")
            result["away_team_id"] = away.get("id")
        elif recent:
            # Si no hay próximos, probar con el más reciente para test Poisson
            ev = recent[0]
            home = ev.get("homeTeam", {})
            away = ev.get("awayTeam", {})
            result["next_match"] = f"{home.get('name')} vs {away.get('name')} (reciente)"
            result["home_team_id"] = home.get("id")
            result["away_team_id"] = away.get("id")

    # Probar búsqueda de equipo
    test_team = search_team("Spain")
    result["search_test"] = (
        f"OK — Spain ID={test_team.get('id')}" if test_team else "FAIL — /search no responde"
    )

    return result
