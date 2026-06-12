from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MiddleOpportunity:
    """
    'Middle' — Over X.5 (casa A) + Under (X+1).5 (casa B).
    Si el partido acaba con exactamente X+1 goles, AMBAS apuestas ganan.
    """
    event_id: str
    event_name: str
    league: str
    commence_time: str
    over_line: float           # e.g. 2.5
    under_line: float          # e.g. 3.5
    middle_goal: int           # goles exactos donde ambas ganan (e.g. 3)
    over_bookmaker: str
    under_bookmaker: str
    over_odds: float
    under_odds: float
    stake_each: float          # stake recomendado por lado
    both_win_profit: float     # ganancia si el middle golpea
    over_wins_result: float    # resultado neto si goles > under_line
    under_wins_result: float   # resultado neto si goles < over_line
    implied_middle_prob: float # probabilidad implícita del middle (%)
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def unique_key(self) -> str:
        return (
            f"middle:{self.event_id}:"
            f"over{self.over_line}@{self.over_bookmaker}:"
            f"under{self.under_line}@{self.under_bookmaker}"
        )


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
