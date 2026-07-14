from typing import Callable, Dict, List, Protocol, runtime_checkable


_BAR_REQUIRED_KEYS = {"name", "ts_code", "freq", "window"}
_OHLCV_COLS = ["name", "ts", "open", "high", "low", "close", "vol", "amount"]


def validate_declare(declare_dict: Dict) -> None:
    if "bars" not in declare_dict:
        raise ValueError("declare必须包含bars字段")
    bars = declare_dict["bars"]
    if not isinstance(bars, list):
        raise ValueError("bars必须是list[dict]")
    for bar in bars:
        missing = _BAR_REQUIRED_KEYS - set(bar.keys())
        if missing:
            raise ValueError(f"bar声明缺少字段: {missing}")
    if "decision_freq" not in declare_dict:
        raise ValueError("declare必须包含decision_freq字段")
    if "fetch" not in declare_dict:
        raise ValueError("declare必须包含fetch字段")
    if not callable(declare_dict["fetch"]):
        raise ValueError("fetch必须是callable")


@runtime_checkable
class Predictor(Protocol):
    def declare(self) -> Dict:
        pass

    def decide(self, ctx: Dict) -> Dict[str, int]:
        pass
