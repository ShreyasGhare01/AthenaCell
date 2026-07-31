import pytest
import numpy as np
import pandas as pd
from engine.walk_forward import generate_rolling_folds
from engine.metrics.implementations import MetricRegistry
from engine.backtester import Backtester, evaluate_indicator, evaluate_rule
from strategies.schema import validate_strategy_config

def test_generate_rolling_folds():
    folds = generate_rolling_folds(
        start_date="2020-01-01",
        end_date="2021-06-30",
        train_months=12,
        validate_months=3,
        step_months=3
    )
    # Fold 1: train 2020-01-01 to 2020-12-31, val 2021-01-01 to 2021-03-31
    # Fold 2: train 2020-04-01 to 2021-03-31, val 2021-04-01 to 2021-06-30
    assert len(folds) == 2
    assert folds[0]["train_start"] == pd.to_datetime("2020-01-01")
    assert folds[0]["val_end"] == pd.to_datetime("2021-03-31")

def test_metrics():
    returns = np.array([0.01, -0.005, 0.02, 0.01, -0.01])
    equity = np.array([100, 101, 100.5, 102.5, 103.5, 102.5])

    sharpe = MetricRegistry.get_metric("sharpe")
    dd = MetricRegistry.get_metric("max_drawdown")

    assert sharpe.calculate(returns, equity) > 0
    assert dd.calculate(returns, equity) > 0

class MockSource:
    def fetch_data(self, ticker, start, end):
        # Create mock pandas dataframe
        idx = pd.date_range(start, end, freq="B")
        df = pd.DataFrame({
            "open": np.linspace(100, 150, len(idx)),
            "high": np.linspace(102, 152, len(idx)),
            "low": np.linspace(98, 148, len(idx)),
            "close": np.linspace(101, 151, len(idx)),
            "volume": [1000] * len(idx)
        }, index=idx)
        return df

def test_backtester_run():
    # Load example strategy
    import json
    with open("strategies/examples/sma_cross_rsi.json", "r") as f:
        data = json.load(f)

    config = validate_strategy_config(data)
    # Restrict universe for testing
    config.universe = ["TEST"]

    source = MockSource()
    backtester = Backtester(source)

    res = backtester.run(config, "2023-01-01", "2023-06-30")
    assert "sharpe" in res
    assert "equity_curve" in res
    assert len(res["equity_curve"]) > 0
