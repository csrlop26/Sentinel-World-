"""
Cliente para FootApi (REcodeX / Sofascore) via RapidAPI.

Endpoints principales:
  /tournament/{id}                                    → info del torneo
  /tournament/{id}/seasons                            → temporadas disponibles
  /tournament/{id}/season/{sid}/events/next/{page}    → próximos partidos
  /tournament/{id}/season/{sid}/events/last/{page}    → resultados recientes
  /team/{teamId}/events/last/{page}                   → últimos partidos del equipo
  /team/{teamId}/statistics/season/{sid}/tournament/{tid}  → stats del equipo

Free plan: 100 req/día (usa el caché).
"""

import logging
import time

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_BASE    = "https://footapi7.p.rapidapi.com/api"
_HOST    = "footapi7.p.rapidapi.com"

# ID del torneo FIFA World Cup en Sofascore (constante histórica)
WC_TOURNAMENT_ID = 16

# Caché en memoria: {cache_key: (timestamp, data)}
_cache: dict[str, tuple[float, object]] = {}
_TTL = 300  # 5 minutos por defecto


def _get(path: str, ttl: int = _TTL) -> dict | list | None:
    """GET autenticado con caché en memoria."""
    if not settings.RAPIDAPI_KEY:
        return None

    key = path
    now = time.time()
    if key in _cache:
        ts, data = _cache[key]
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
            resp.raise_for_status()
            data = resp.json()
            _cache[key] = (now, data)
            return data
    except httpx.HTTPStatusError as e:
        logger.warning(f"FootApi HTTP {e.response.status_code}: {path}")
        return None
    except Exception as e:
        logger.warning(f"FootApi error: {e}")
        return None


# ── Torneos ───────────────────────────────────────────────────────────────────

def get_tournament_info(tournament_id: int = WC_TOURNAMENT_ID) -> dict | None:
    data = _get(f"/tournament/{tournament_id}", ttl=3600)
    if isinstance(data, dict):
        return data.get("uniqueTournament") or data
    return None


def get_seasons(tournament_id: int = WC_TOURNAMENT_ID) -> list[dict]:
    data = _get(f"/tournament/{tournament_id}/seasons", ttl=3600)
    if isinstance(data, dict):
        return data.get("seasons", [])
    return []


def get_current_season_id(tournament_id: int = WC_TOURNAMENT_ID) -> int | None:
    """Devuelve el ID de la temporada activa más reciente."""
    seasons = get_seasons(tournament_id)
    if not seasons:
        return None
    # Sofascore ordena las temporadas de más reciente a más antigua
    return seasons[0].get("id")


# ── Partidos ──────────────────────────────────────────────────────────────────

def get_upcoming_events(
    tournament_id: int = WC_TOURNAMENT_ID,
    season_id: int | None = None,
    page: int = 0,
) -> list[dict]:
    """Próximos partidos del torneo."""
    sid = season_id or get_current_season_id(tournament_id)
    if not sid:
        return []
    data = _get(f"/tournament/{tournament_id}/season/{sid}/events/next/{page}")
    if isinstance(data, dict):
        return data.get("events", [])
    return []


def get_recent_events(
    tournament_id: int = WC_TOURNAMENT_ID,
    season_id: int | None = None,
    page: int = 0,
) -> list[dict]:
    """Partidos jugados recientemente en el torneo."""
    sid = season_id or get_current_season_id(tournament_id)
    if not sid:
        return []
    data = _get(f"/tournament/{tournament_id}/season/{sid}/events/last/{page}")
    if isinstance(data, dict):
        return data.get("events", [])
    return []


def get_team_recent_matches(team_id: int, page: int = 0) -> list[dict]:
    """Últimos ~10 partidos del equipo (todos los torneos)."""
    data = _get(f"/team/{team_id}/events/last/{page}")
    if isinstance(data, dict):
        return data.get("events", [])
    return []


# ── Estadísticas ──────────────────────────────────────────────────────────────

def get_team_stats(
    team_id: int,
    tournament_id: int = WC_TOURNAMENT_ID,
    season_id: int | None = None,
) -> dict | None:
    """Estadísticas del equipo en el torneo: goles, asistencias, etc."""
    sid = season_id or get_current_season_id(tournament_id)
    if not sid:
        return None
    data = _get(
        f"/team/{team_id}/statistics/season/{sid}/tournament/{tournament_id}",
        ttl=900,  # 15 min — las stats cambian tras cada partido
    )
    if isinstance(data, dict):
        return data.get("statistics") or data
    return None


# ── Resolución de nombre → ID de equipo ──────────────────────────────────────

def search_team(name: str) -> dict | None:
    """Busca un equipo por nombre. Devuelve el primero coincidente."""
    data = _get(f"/search/team/{name.replace(' ', '%20')}", ttl=3600)
    if isinstance(data, dict):
        results = data.get("teams", [])
        if results:
            return results[0]
    return None


# ── Diagnóstico / discovery ───────────────────────────────────────────────────

def diagnose() -> dict:
    """
    Comprueba conectividad y devuelve los IDs necesarios para el bot.
    Útil para validar la integración con 'python main.py footapi'.
    """
    result: dict = {}

    if not settings.RAPIDAPI_KEY:
        result["error"] = "RAPIDAPI_KEY no configurada en .env"
        return result

    info = get_tournament_info(WC_TOURNAMENT_ID)
    result["tournament"] = info.get("name") if info else "Error al obtener info"

    season_id = get_current_season_id(WC_TOURNAMENT_ID)
    result["season_id"] = season_id

    if season_id:
        upcoming = get_upcoming_events(WC_TOURNAMENT_ID, season_id)
        result["upcoming_matches"] = len(upcoming)
        if upcoming:
            ev = upcoming[0]
            home = ev.get("homeTeam", {})
            away = ev.get("awayTeam", {})
            result["next_match"] = f"{home.get('name')} vs {away.get('name')}"
            result["home_team_id"] = home.get("id")
            result["away_team_id"] = away.get("id")

        recent = get_recent_events(WC_TOURNAMENT_ID, season_id)
        result["recent_matches"] = len(recent)

    return result
