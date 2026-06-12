from data.models import ArbLeg

# Market keys treated as main 1x2 / moneyline market
_MAIN_MARKETS = {"moneyline", "h2h", "1x2", "match_winner", "winner"}


def find_best_odds(odds_items: list[dict]) -> dict[str, tuple[str, float]]:
    """
    Returns {outcome_name: (bookmaker, best_odds)} across all available bookmakers.
    Only considers the main 1x2 / moneyline market.
    """
    best: dict[str, tuple[str, float]] = {}

    for item in odds_items:
        if not item.get("is_available", True):
            continue

        market = (item.get("market_key") or "").lower()
        if market and market not in _MAIN_MARKETS:
            continue

        outcome = (
            item.get("selection_name")
            or item.get("side")
            or item.get("name")
            or ""
        ).strip()
        bookmaker = (
            item.get("bookmaker")
            or item.get("bookmaker_name")
            or ""
        ).strip()
        try:
            odds = float(item.get("odds") or item.get("price") or 0)
        except (TypeError, ValueError):
            continue

        if not outcome or not bookmaker or odds <= 1.0:
            continue

        if outcome not in best or odds > best[outcome][1]:
            best[outcome] = (bookmaker, odds)

    return best


def calculate_arb(
    best_odds: dict[str, tuple[str, float]],
    bankroll: float,
) -> tuple[float, dict[str, tuple[str, float, float]]]:
    """
    Calculates arbitrage opportunity.

    Returns:
        (profit_pct, {outcome: (bookmaker, odds, stake)})
        profit_pct is 0.0 if no arb exists.

    Formula:
        inv_sum = Σ (1/odd_i)
        arb exists when inv_sum < 1
        profit_pct = (1/inv_sum - 1) * 100
        stake_i = bankroll * (1/odd_i) / inv_sum  →  equal payout on all outcomes
    """
    if len(best_odds) < 2:
        return 0.0, {}

    inv_sum = sum(1.0 / odds for _, odds in best_odds.values())

    if inv_sum >= 1.0:
        return 0.0, {}

    profit_pct = (1.0 / inv_sum - 1.0) * 100.0

    stakes: dict[str, tuple[str, float, float]] = {}
    for outcome, (bookmaker, odds) in best_odds.items():
        stake = round(bankroll * (1.0 / odds) / inv_sum, 2)
        stakes[outcome] = (bookmaker, odds, stake)

    return profit_pct, stakes


def build_legs(stakes: dict[str, tuple[str, float, float]]) -> list[ArbLeg]:
    return [
        ArbLeg(bookmaker=bm, outcome=outcome, odds=odds, stake=stake)
        for outcome, (bm, odds, stake) in stakes.items()
    ]
