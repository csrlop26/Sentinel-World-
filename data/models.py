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
class ValueBet:
    """
    Value bet (+EV) — cuota de una casa blanda superior a la probabilidad real
    estimada por el consenso de casas sharp (Pinnacle, Betfair Exchange...).

    Edge = (odds × P_real − 1) × 100
    Stake = Quarter-Kelly × Bankroll (cap 10%)
    """
    event_id: str
    event_name: str
    league: str
    commence_time: str
    market: str          # "1×2", "Más/Menos 2.5 goles"
    outcome: str         # "Over 2.5", "Home", "Draw", etc.
    bookmaker: str       # donde apostar
    odds: float
    true_prob: float     # probabilidad real según consenso sharp (0-1)
    edge_pct: float      # (odds × true_prob − 1) × 100
    kelly_pct: float     # % del bankroll recomendado (quarter-Kelly)
    stake: float         # stake en € recomendado
    sharp_ref: str       # casas usadas como referencia
    poisson_prob: float | None = None   # probabilidad Poisson para este outcome (si disponible)
    confidence: str = "normal"          # "high" si Poisson confirma el consenso sharp
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def unique_key(self) -> str:
        return f"value:{self.event_id}:{self.market}:{self.outcome}:{self.bookmaker}"


@dataclass
class ArbLeg:
    bookmaker: str
    outcome: str
    odds: float
    stake: float
    is_dgoj: bool = True   # False si la casa no tiene licencia DGOJ española


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
