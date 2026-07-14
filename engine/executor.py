import logging
from typing import Callable, Dict, List, Optional

import pandas as pd

from engine.matcher import match, default_commission

logger = logging.getLogger(__name__)


def execute_backtest(target: Dict[str, int], positions: Dict[str, int],
                     cash: float, next_bars: pd.DataFrame,
                     aux_filters: Dict,
                     commission_fn: Optional[Callable] = None) -> Dict:
    return match(target, positions, cash, next_bars,
                 commission_fn=commission_fn,
                 limit_df=aux_filters.get("limit"),
                 suspend_df=aux_filters.get("suspend"),
                 st_df=aux_filters.get("st"))


def execute_live(target: Dict[str, int], positions: Dict[str, int],
                 cash: float, broker_fn: Callable) -> Dict:
    return broker_fn(target, positions, cash)
