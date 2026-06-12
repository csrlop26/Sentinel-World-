from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ArbLeg:
    bookmaker: str
    outcome: str
    odds: float
    stake: float


@dataclass
class ArbOpportunity:
    event_id: str
    event_name: str
    sport: str
    league: str
    commence_time: str
    legs: list
    margin_pct: float
    bankroll: float
    min_profit: float
    market: str = "1×2"
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def unique_key(self) -> str:
        legs_part = "_".join(sorted(f"{l.bookmaker}:{l.outcome}" for l in self.legs))
        return f"{self.event_id}:{self.market}:{legs_part}"

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "sport": self.sport,
            "league": self.league,
            "commence_time": self.commence_time,
            "legs": [
                {
                    "bookmaker": l.bookmaker,
                    "outcome": l.outcome,
                    "odds": l.odds,
                    "stake": l.stake,
                }
                for l in self.legs
            ],
            "margin_pct": self.margin_pct,
            "bankroll": self.bankroll,
            "min_profit": self.min_profit,
            "detected_at": self.detected_at,
        }
