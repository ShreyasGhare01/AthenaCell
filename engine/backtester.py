import numpy as np
import pandas as pd
from typing import Dict, Any, List
from strategies.schema import StrategyConfig, RuleType, SimpleCondition, LogicalRuleGroup

def evaluate_indicator(df: pd.DataFrame, indicator: Dict[str, Any], index_pos: int) -> float:
    """
    Computes or retrieves an indicator value for a given DataFrame at index_pos.
    Supported indicators: SMA, EMA, RSI, MACD (LINE, SIGNAL, HIST), BB (UPPER, LOWER, MIDDLE), ATR, PRICE_CLOSE, PRICE_OPEN, PRICE_HIGH, PRICE_LOW, VOLUME, N_DAY_HIGH, N_DAY_LOW.
    """
    name = indicator.get("name")
    period = indicator.get("period")
    if period is None:
        period = 14
    else:
        period = int(period)

    # We slice up to index_pos to avoid lookahead bias during valuation
    df_slice = df.iloc[:index_pos + 1]
    if len(df_slice) == 0:
        return 0.0

    if name == "PRICE_CLOSE":
        return float(df_slice["close"].iloc[-1])
    elif name == "PRICE_OPEN":
        return float(df_slice["open"].iloc[-1])
    elif name == "PRICE_HIGH":
        return float(df_slice["high"].iloc[-1])
    elif name == "PRICE_LOW":
        return float(df_slice["low"].iloc[-1])
    elif name == "VOLUME":
        return float(df_slice["volume"].iloc[-1])

    elif name == "SMA":
        if len(df_slice) < period:
            return float(df_slice["close"].mean())
        return float(df_slice["close"].iloc[-period:].mean())

    elif name == "EMA":
        if len(df_slice) < period:
            return float(df_slice["close"].mean())
        # Fast approximation of EMA
        return float(df_slice["close"].ewm(span=period, adjust=False).mean().iloc[-1])

    elif name == "RSI":
        if len(df_slice) < period + 1:
            return 50.0
        delta = df_slice["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        val = rsi.iloc[-1]
        return 50.0 if pd.isna(val) else float(val)

    elif name in ["MACD_LINE", "MACD_SIGNAL", "MACD_HIST"]:
        if len(df_slice) < 26:
            return 0.0
        ema12 = df_slice["close"].ewm(span=12, adjust=False).mean()
        ema26 = df_slice["close"].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_signal
        if name == "MACD_LINE":
            return float(macd_line.iloc[-1])
        elif name == "MACD_SIGNAL":
            return float(macd_signal.iloc[-1])
        else:
            return float(macd_hist.iloc[-1])

    elif name in ["BB_UPPER", "BB_LOWER", "BB_MIDDLE"]:
        if len(df_slice) < period:
            period = min(len(df_slice), period)
        std = df_slice["close"].iloc[-period:].std()
        sma = df_slice["close"].iloc[-period:].mean()
        if pd.isna(std):
            std = 0.0
        if name == "BB_UPPER":
            return float(sma + 2 * std)
        elif name == "BB_LOWER":
            return float(sma - 2 * std)
        else:
            return float(sma)

    elif name == "ATR":
        # Average True Range
        if len(df_slice) < 2:
            return 0.0
        highs = df_slice["high"]
        lows = df_slice["low"]
        closes = df_slice["close"].shift(1)
        tr1 = highs - lows
        tr2 = (highs - closes).abs()
        tr3 = (lows - closes).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        val = tr.rolling(window=period).mean().iloc[-1]
        return 0.0 if pd.isna(val) else float(val)

    elif name == "N_DAY_HIGH":
        if len(df_slice) < period:
            return float(df_slice["high"].max())
        return float(df_slice["high"].iloc[-period:].max())

    elif name == "N_DAY_LOW":
        if len(df_slice) < period:
            return float(df_slice["low"].min())
        return float(df_slice["low"].iloc[-period:].min())

    return 0.0

def evaluate_rule(rule: Dict[str, Any], df: pd.DataFrame, index_pos: int) -> bool:
    """
    Evaluates a recursive rule configuration against a single ticker DataFrame at index_pos.
    """
    rule_type = rule.get("type")

    if rule_type in ["and", "or", "not"]:
        nested_rules = rule.get("rules", [])
        if rule_type == "and":
            return all(evaluate_rule(r, df, index_pos) for r in nested_rules) if nested_rules else False
        elif rule_type == "or":
            return any(evaluate_rule(r, df, index_pos) for r in nested_rules) if nested_rules else False
        elif rule_type == "not":
            return not evaluate_rule(nested_rules[0], df, index_pos) if nested_rules else False

    # Simple condition
    indicator_a = rule.get("indicator_a")
    operator = rule.get("operator")
    indicator_b = rule.get("indicator_b")

    if not indicator_a or not operator:
        return False

    val_a = evaluate_indicator(df, indicator_a, index_pos)

    if isinstance(indicator_b, dict):
        val_b = evaluate_indicator(df, indicator_b, index_pos)
    elif isinstance(indicator_b, (int, float)):
        val_b = float(indicator_b)
    else:
        return False

    if operator == ">":
        return val_a > val_b
    elif operator == "<":
        return val_a < val_b
    elif operator == ">=":
        return val_a >= val_b
    elif operator == "<=":
        return val_a <= val_b
    elif operator == "==":
        return val_a == val_b
    elif operator == "!=":
        return val_a != val_b

    return False


class Backtester:
    """
    Simulated paper backtesting engine.
    Runs a validated StrategyConfig against historical data for a given date range.
    No live trading, completely offline and risk-free.
    """
    def __init__(self, data_source):
        self.data_source = data_source

    def run(
        self,
        config: StrategyConfig,
        start_date: str,
        end_date: str,
        initial_cash: float = 100000.0,
        risk_per_trade_cap_pct: float = 0.02
    ) -> Dict[str, Any]:
        """
        Runs backtest. Returns performance metrics, detailed trade log, and daily equity curve.
        """
        # Fetch historical data for all universe tickers
        tickers_data = {}
        for ticker in config.universe:
            try:
                tickers_data[ticker] = self.data_source.fetch_data(ticker, start_date, end_date)
            except Exception as e:
                print(f"Error fetching data for {ticker}: {e}")

        if not tickers_data:
            return {
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "equity_curve": [],
                "trades": []
            }

        # Compile unique union of business days across all dataframes
        all_dates = sorted(list(set().union(*(df.index for df in tickers_data.values()))))
        if not all_dates:
            return {
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "equity_curve": [],
                "trades": []
            }

        cash = initial_cash
        positions = {} # ticker -> { 'entry_price', 'entry_date', 'size', 'stop_loss', 'take_profit' }
        trades_log = []
        equity_history = []

        # Serialize entry/exit rules to simple dictionaries for evaluate_rule
        entry_rules_dict = config.entry_rules.model_dump()
        exit_rules_dict = config.exit_rules.model_dump()

        for date in all_dates:
            # Update position valuations and check exits/stop-losses
            current_equity = cash
            for ticker, pos in list(positions.items()):
                df = tickers_data[ticker]
                if date in df.index:
                    current_price = float(df.loc[date, "close"])
                    pos_val = pos["size"] * current_price
                    current_equity += pos_val

                    # 1. Stop loss trigger
                    if pos["stop_loss"] and current_price <= pos["stop_loss"]:
                        # Sell
                        cash += pos["size"] * current_price
                        trades_log.append({
                            "ticker": ticker,
                            "entry_date": pos["entry_date"],
                            "entry_price": pos["entry_price"],
                            "exit_date": date,
                            "exit_price": current_price,
                            "size": pos["size"],
                            "profit_pct": (current_price - pos["entry_price"]) / pos["entry_price"],
                            "exit_reason": "stop_loss"
                        })
                        positions.pop(ticker)
                        continue

                    # 2. Take profit trigger
                    if pos["take_profit"] and current_price >= pos["take_profit"]:
                        cash += pos["size"] * current_price
                        trades_log.append({
                            "ticker": ticker,
                            "entry_date": pos["entry_date"],
                            "entry_price": pos["entry_price"],
                            "exit_date": date,
                            "exit_price": current_price,
                            "size": pos["size"],
                            "profit_pct": (current_price - pos["entry_price"]) / pos["entry_price"],
                            "exit_reason": "take_profit"
                        })
                        positions.pop(ticker)
                        continue

                    # 3. Strategy EXIT Rule evaluation
                    index_pos = df.index.get_loc(date)
                    if evaluate_rule(exit_rules_dict, df, index_pos):
                        cash += pos["size"] * current_price
                        trades_log.append({
                            "ticker": ticker,
                            "entry_date": pos["entry_date"],
                            "entry_price": pos["entry_price"],
                            "exit_date": date,
                            "exit_price": current_price,
                            "size": pos["size"],
                            "profit_pct": (current_price - pos["entry_price"]) / pos["entry_price"],
                            "exit_reason": "rule"
                        })
                        positions.pop(ticker)
                        continue
                else:
                    # Ticker doesn't have data on this date, assume holding value remains same
                    current_equity += pos["size"] * pos["entry_price"]

            # Log daily equity
            equity_history.append({
                "date": date.strftime("%Y-%m-%d"),
                "equity": current_equity
            })

            # Check for new ENTRYS if we have open slots
            if len(positions) < config.max_concurrent_positions:
                for ticker in config.universe:
                    if ticker in positions:
                        continue
                    df = tickers_data[ticker]
                    if date not in df.index:
                        continue

                    index_pos = df.index.get_loc(date)
                    if evaluate_rule(entry_rules_dict, df, index_pos):
                        # Determine entry price and initial parameters
                        entry_price = float(df.loc[date, "close"])

                        # Position sizing logic
                        allocation_pct = config.position_sizing.value

                        # Risk sizing: Max amount to allocate is current_equity * allocation_pct
                        max_allocation = current_equity * allocation_pct

                        # Set Stop Loss / Take Profit
                        sl_price = None
                        tp_price = None

                        if config.risk_management.stop_loss_pct:
                            sl_price = entry_price * (1 - config.risk_management.stop_loss_pct)
                        if config.risk_management.take_profit_pct:
                            tp_price = entry_price * (1 + config.risk_management.take_profit_pct)

                        # Use ATR stop if applicable
                        if config.risk_management.atr_stop_multiplier:
                            atr_val = evaluate_indicator(df, {"name": "ATR", "period": 14}, index_pos)
                            if atr_val > 0:
                                sl_price = entry_price - (config.risk_management.atr_stop_multiplier * atr_val)

                        # Calculate size based on allocation
                        if cash >= max_allocation and max_allocation > 0:
                            size = max_allocation / entry_price
                            cash -= max_allocation
                            positions[ticker] = {
                                "entry_price": entry_price,
                                "entry_date": date,
                                "size": size,
                                "stop_loss": sl_price,
                                "take_profit": tp_price
                            }

        # Close out any remaining positions at the end of the backtest
        end_date_ts = all_dates[-1]
        for ticker, pos in list(positions.items()):
            df = tickers_data[ticker]
            exit_price = float(df.loc[end_date_ts, "close"]) if end_date_ts in df.index else pos["entry_price"]
            cash += pos["size"] * exit_price
            trades_log.append({
                "ticker": ticker,
                "entry_date": pos["entry_date"],
                "entry_price": pos["entry_price"],
                "exit_date": end_date_ts,
                "exit_price": exit_price,
                "size": pos["size"],
                "profit_pct": (exit_price - pos["entry_price"]) / pos["entry_price"],
                "exit_reason": "end_of_period"
            })

        # Compile Metrics
        equity_vals = np.array([pt["equity"] for pt in equity_history])
        if len(equity_vals) > 1:
            daily_returns = (equity_vals[1:] - equity_vals[:-1]) / equity_vals[:-1]
        else:
            daily_returns = np.array([])

        from engine.metrics.implementations import MetricRegistry
        sharpe_calc = MetricRegistry.get_metric("sharpe")
        dd_calc = MetricRegistry.get_metric("max_drawdown")
        wr_calc = MetricRegistry.get_metric("win_rate")

        sharpe_val = sharpe_calc.calculate(daily_returns, equity_vals)
        dd_val = dd_calc.calculate(daily_returns, equity_vals)
        win_rate_val = wr_calc.calculate(daily_returns, equity_vals)

        return {
            "sharpe": sharpe_val,
            "max_drawdown": dd_val,
            "win_rate": win_rate_val,
            "equity_curve": equity_history,
            "trades": trades_log
        }
