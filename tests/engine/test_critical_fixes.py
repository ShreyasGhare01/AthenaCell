import pytest
import numpy as np
import pandas as pd
from engine.backtester import Backtester
from strategies.schema import validate_strategy_config

class SyntheticSource:
    def __init__(self, data_dict):
        self.data_dict = data_dict

    def fetch_data(self, ticker, start, end):
        return self.data_dict[ticker]

def make_base_config_dict() -> dict:
    return {
        "id": "test_strat",
        "name": "Test Strategy",
        "universe": ["TEST"],
        "entry_rules": {
            "type": "condition",
            "indicator_a": {"name": "PRICE_CLOSE"},
            "operator": ">",
            "indicator_b": 50.0
        },
        "exit_rules": {
            "type": "condition",
            "indicator_a": {"name": "PRICE_CLOSE"},
            "operator": ">",
            "indicator_b": 500.0
        },
        "position_sizing": {"type": "fixed_pct", "value": 0.1},
        "risk_management": {},
        "max_concurrent_positions": 5,
        "risk_per_trade_cap_pct": 0.02,
        "commission": 0.0,
        "slippage_pct": 0.0
    }

def test_same_bar_execution_and_next_open_fill():
    idx = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
    df = pd.DataFrame({
        "open":  [100.0, 105.0, 110.0],
        "high":  [102.0, 107.0, 112.0],
        "low":   [98.0,  103.0, 108.0],
        "close": [101.0, 106.0, 111.0],
        "volume": [1000, 1000, 1000]
    }, index=idx)

    source = SyntheticSource({"TEST": df})
    backtester = Backtester(source)

    cfg_dict = make_base_config_dict()
    cfg_dict["exit_rules"] = {
        "type": "condition",
        "indicator_a": {"name": "PRICE_CLOSE"},
        "operator": ">",
        "indicator_b": 105.0
    }
    config = validate_strategy_config(cfg_dict)

    res = backtester.run(config, "2025-01-01", "2025-01-03")
    trades = res["trades"]

    assert len(trades) == 1
    t = trades[0]
    assert t["entry_price"] == 105.0
    assert t["exit_price"] == 110.0
    assert t["exit_reason"] == "rule"


def test_transaction_costs_slippage_and_commission():
    idx = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
    df = pd.DataFrame({
        "open":  [100.0, 105.0, 110.0],
        "high":  [102.0, 107.0, 112.0],
        "low":   [98.0,  103.0, 108.0],
        "close": [101.0, 106.0, 111.0],
        "volume": [1000, 1000, 1000]
    }, index=idx)

    source = SyntheticSource({"TEST": df})

    # Run 1: No costs
    cfg_dict_no = make_base_config_dict()
    cfg_dict_no["position_sizing"]["value"] = 1.0
    cfg_dict_no["exit_rules"] = {
        "type": "condition",
        "indicator_a": {"name": "PRICE_CLOSE"},
        "operator": ">",
        "indicator_b": 105.0
    }
    config_no_costs = validate_strategy_config(cfg_dict_no)
    res_no_costs = Backtester(source).run(config_no_costs, "2025-01-01", "2025-01-03")

    # Run 2: High costs
    cfg_dict_with = make_base_config_dict()
    cfg_dict_with["position_sizing"]["value"] = 1.0
    cfg_dict_with["commission"] = 10.0
    cfg_dict_with["slippage_pct"] = 0.01
    cfg_dict_with["exit_rules"] = {
        "type": "condition",
        "indicator_a": {"name": "PRICE_CLOSE"},
        "operator": ">",
        "indicator_b": 105.0
    }
    config_with_costs = validate_strategy_config(cfg_dict_with)
    res_with_costs = Backtester(source).run(config_with_costs, "2025-01-01", "2025-01-03")

    assert len(res_no_costs["trades"]) == 1
    assert len(res_with_costs["trades"]) == 1

    trade_with = res_with_costs["trades"][0]
    assert trade_with["entry_price"] == 105.0 * 1.01
    assert trade_with["exit_price"] == 110.0 * 0.99
    assert res_with_costs["equity_curve"][-1]["equity"] < res_no_costs["equity_curve"][-1]["equity"]


def test_risk_per_trade_cap_sizing():
    idx = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
    df = pd.DataFrame({
        "open":  [100.0, 100.0, 100.0],
        "high":  [102.0, 102.0, 102.0],
        "low":   [98.0,  98.0,  98.0],
        "close": [101.0, 101.0, 101.0],
        "volume": [1000, 1000, 1000]
    }, index=idx)

    source = SyntheticSource({"TEST": df})
    backtester = Backtester(source)

    cfg_dict = make_base_config_dict()
    cfg_dict["position_sizing"]["value"] = 0.5
    cfg_dict["risk_management"] = {"stop_loss_pct": 0.05}
    cfg_dict["risk_per_trade_cap_pct"] = 0.01

    config = validate_strategy_config(cfg_dict)

    res = backtester.run(config, "2025-01-01", "2025-01-03", initial_cash=100000.0)
    trades = res["trades"]

    assert len(trades) > 0
    t = trades[0]
    assert t["size"] == pytest.approx(200.0)
    assert res["risk_cap_applied"] is True


def test_win_rate_matches_trades():
    idx = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"])

    df_win = pd.DataFrame({
        "open":  [100.0, 100.0, 110.0, 110.0],
        "high":  [100.0, 100.0, 110.0, 110.0],
        "low":   [100.0, 100.0, 110.0, 110.0],
        "close": [101.0, 101.0, 111.0, 111.0],
        "volume": [1000] * 4
    }, index=idx)

    df_loss = pd.DataFrame({
        "open":  [100.0, 100.0, 90.0, 90.0],
        "high":  [100.0, 100.0, 90.0, 90.0],
        "low":   [100.0, 100.0, 90.0, 90.0],
        "close": [101.0, 101.0, 89.0, 89.0],
        "volume": [1000] * 4
    }, index=idx)

    df_end = pd.DataFrame({
        "open":  [100.0, 100.0, 100.0, 100.0],
        "high":  [100.0, 100.0, 100.0, 100.0],
        "low":   [100.0, 100.0, 100.0, 100.0],
        "close": [101.0, 101.0, 101.0, 101.0],
        "volume": [1000] * 4
    }, index=idx)

    source = SyntheticSource({"WIN": df_win, "LOSS": df_loss, "END": df_end})
    backtester = Backtester(source)

    cfg_dict = make_base_config_dict()
    cfg_dict["universe"] = ["WIN", "LOSS", "END"]
    cfg_dict["max_concurrent_positions"] = 3
    cfg_dict["position_sizing"]["value"] = 0.2
    cfg_dict["exit_rules"] = {
        "type": "condition",
        "indicator_a": {"name": "PRICE_CLOSE"},
        "operator": "!=",
        "indicator_b": 101.0
    }
    config = validate_strategy_config(cfg_dict)

    res = backtester.run(config, "2025-01-01", "2025-01-04")
    trades = res["trades"]

    closed_trades = [t for t in trades if t["exit_reason"] != "end_of_period"]
    assert len(closed_trades) == 2
    assert res["win_rate"] == 0.5


def test_missing_data_carry_forward():
    idx_a = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
    df_a = pd.DataFrame({
        "open":  [100.0, 100.0, 100.0],
        "high":  [102.0, 102.0, 102.0],
        "low":   [98.0,  98.0,  98.0],
        "close": [101.0, 101.0, 101.0],
        "volume": [1000, 1000, 1000]
    }, index=idx_a)

    # Ticker B is missing Day 3 (index_a[2])
    idx_b = pd.to_datetime(["2025-01-01", "2025-01-02"])
    df_b = pd.DataFrame({
        "open":  [100.0, 100.0],
        "high":  [102.0, 102.0],
        "low":   [98.0,  98.0],
        "close": [101.0, 120.0], # Day 2 (index_a[1]) close is 120
        "volume": [1000, 1000]
    }, index=idx_b)

    source = SyntheticSource({"A": df_a, "B": df_b})
    backtester = Backtester(source)

    cfg_dict = make_base_config_dict()
    cfg_dict["universe"] = ["A", "B"]
    cfg_dict["max_concurrent_positions"] = 2
    cfg_dict["position_sizing"]["value"] = 0.5

    config = validate_strategy_config(cfg_dict)

    res = backtester.run(config, "2025-01-01", "2025-01-03")
    equity_history = res["equity_curve"]
    assert len(equity_history) == 3

    # On 2025-01-03, B has no data. It should carry forward 120.0 as last_known_price.
    # Day 1 close: A close=101.0, B close=120.0. Equity = 110,500
    # Day 2: B has no data, so it carries forward 120.0. A close=101.0. Total equity = 110,500.
    day_3_equity = [pt["equity"] for pt in equity_history if pt["date"] == "2025-01-03"][0]
    assert day_3_equity == pytest.approx(110500.0)
