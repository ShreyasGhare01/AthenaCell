import numpy as np
from engine.metrics.base import ScoringMetric

class SharpeRatio(ScoringMetric):
    def __init__(self, risk_free_rate: float = 0.0, annualization_factor: int = 252):
        self.risk_free_rate = risk_free_rate
        self.annualization_factor = annualization_factor

    def calculate(self, daily_returns: np.ndarray, equity_curve: np.ndarray) -> float:
        if len(daily_returns) == 0:
            return 0.0
        mean_ret = np.mean(daily_returns)
        std_ret = np.std(daily_returns)
        if std_ret == 0:
            return 0.0
        # Annualized Sharpe Ratio
        return float((mean_ret - self.risk_free_rate) / std_ret * np.sqrt(self.annualization_factor))

class MaxDrawdown(ScoringMetric):
    def calculate(self, daily_returns: np.ndarray, equity_curve: np.ndarray) -> float:
        if len(equity_curve) == 0:
            return 0.0
        peak = np.maximum.accumulate(equity_curve)
        # Avoid division by zero if peak is 0
        peak = np.where(peak == 0, 1.0, peak)
        drawdowns = (peak - equity_curve) / peak
        return float(np.max(drawdowns))

class MetricRegistry:
    _metrics = {
        "sharpe": SharpeRatio,
        "max_drawdown": MaxDrawdown
    }

    @classmethod
    def get_metric(cls, name: str) -> ScoringMetric:
        if name not in cls._metrics:
            raise ValueError(f"Unknown metric: {name}")
        return cls._metrics[name]()
