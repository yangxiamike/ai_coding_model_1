import logging
from typing import Dict

logger = logging.getLogger(__name__)


def update_portfolio(match_result: Dict) -> Dict:
    positions = match_result["positions"]
    cash = match_result["cash"]
    return {"positions": positions, "cash": cash}


def total_asset(positions: Dict[str, int], prices: Dict[str, float]) -> float:
    market_value = sum(positions.get(code, 0) * prices.get(code, 0.0)
                       for code in positions)
    return market_value


def initial_state(cash: float = None) -> Dict:
    if cash is None:
        from engine import config
        cash = config.get("engine.initial_cash", 1000000.0)
    return {"positions": {}, "cash": cash}
