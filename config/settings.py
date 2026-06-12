from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # odds-api.net (opcional — dejar vacío si no se usa)
    ODDS_API_KEY: str = ""
    ODDS_API_BASE_URL: str = "https://api.odds-api.net/v1"

    # The Odds API (the-odds-api.com) — opcional, amplía cobertura de bookmakers
    THEODDS_API_KEY: str = ""
    THEODDS_REGIONS: str = "eu,uk"          # eu,uk,us,au — más regiones = más cuota usada
    THEODDS_CACHE_MINUTES: int = 10         # caché para no agotar las 500 req/mes gratis

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    # Bot config
    BANKROLL: float = 100.0
    MIN_ARB_MARGIN: float = 1.5
    MAX_ARB_MARGIN: float = 15.0
    SCAN_INTERVAL: int = 30

    # Filters
    SPORT_FILTER: str = "soccer"
    LEAGUE_FILTER: str = "world cup"

    # Solo casas con licencia DGOJ activa en España (True = activado)
    SPAIN_ONLY: bool = True

    # Mercados a escanear (h2h=resultado, totals=más/menos goles, btts=ambos marcan)
    MARKETS: str = "h2h,totals,btts"

    # Deportes adicionales más allá del Mundial (separados por coma, vacío = solo fútbol WC)
    # Ejemplo: "tennis_atp_wimbledon,basketball_nba"
    EXTRA_SPORTS: str = ""

    # Value Betting (+EV)
    # Edge mínimo para alertar una value bet (odds × P_real − 1) × 100 ≥ este valor
    MIN_VALUE_EDGE: float = 5.0
    # Stake mínimo en € — filtra longshots con apuestas insignificantes (quarter-Kelly)
    MIN_VALUE_STAKE: float = 1.0

    # RapidAPI — FootApi (estadísticas de fútbol para modelo Poisson)
    RAPIDAPI_KEY: str = ""


settings = Settings()
