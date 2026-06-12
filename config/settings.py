from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Odds API
    ODDS_API_KEY: str
    ODDS_API_BASE_URL: str = "https://api.odds-api.net/v1"

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


settings = Settings()
