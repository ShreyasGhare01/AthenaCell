import numpy as np
import pandas as pd
import logging
import random
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
                "trades": [],
                "risk_cap_applied": False
            }

        # Compile unique union of business days across all dataframes
        all_dates = sorted(list(set().union(*(df.index for df in tickers_data.values()))))
        if not all_dates:
            return {
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "equity_curve": [],
                "trades": [],
                "risk_cap_applied": False
            }

        cash = initial_cash
        positions = {} # ticker -> { 'entry_price', 'entry_date', 'size', 'stop_loss', 'take_profit', 'last_known_price' }
        trades_log = []
        equity_history = []

        # Track queued entries and exits for next-bar open execution
        queued_exits = [] # list of dicts: {"ticker": ticker, "reason": reason}
        queued_entries = [] # list of tickers

        # Serialize entry/exit rules to simple dictionaries for evaluate_rule
        entry_rules_dict = config.entry_rules.model_dump()
        exit_rules_dict = config.exit_rules.model_dump()

        # Check if the strategy has a stop-loss configured
        has_stop_loss = (config.risk_management.stop_loss_pct is not None) or (config.risk_management.atr_stop_multiplier is not None)

        for date in all_dates:
            # 1. Execute queued exits at today's Open
            for q_exit in list(queued_exits):
                ticker = q_exit["ticker"]
                reason = q_exit["reason"]
                pos = positions[ticker]
                df = tickers_data[ticker]

                execution_price = float(df.loc[date, "open"]) if date in df.index else pos["last_known_price"]
                effective_exit_price = execution_price * (1 - config.slippage_pct)
                cash_received = pos["size"] * effective_exit_price - config.commission
                cash += cash_received

                trades_log.append({
                    "ticker": ticker,
                    "entry_date": pos["entry_date"],
                    "entry_price": pos["entry_price"],
                    "exit_date": date,
                    "exit_price": effective_exit_price,
                    "size": pos["size"],
                    "profit_pct": (effective_exit_price - pos["entry_price"]) / pos["entry_price"],
                    "exit_reason": reason
                })
                positions.pop(ticker)
            queued_exits.clear()

            # Calculate current equity at the start of the day after exits but before entries
            # Using closing/last known prices for held positions, plus cash
            current_equity = cash + sum(p["size"] * p["last_known_price"] for p in positions.values())

            # 2. Execute queued entries at today's Open
            for ticker in list(queued_entries):
                df = tickers_data[ticker]
                execution_price = float(df.loc[date, "open"]) if date in df.index else None
                if execution_price is None:
                    continue

                effective_entry_price = execution_price * (1 + config.slippage_pct)

                # Compute stop loss and take profit relative to effective entry price
                sl_price = None
                tp_price = None

                # Find index position on the signal date (last date in df before `date`)
                df_before = df.loc[df.index < date]
                signal_index_pos = len(df_before) - 1 if not df_before.empty else 0

                if config.risk_management.stop_loss_pct:
                    sl_price = effective_entry_price * (1 - config.risk_management.stop_loss_pct)
                if config.risk_management.take_profit_pct:
                    tp_price = effective_entry_price * (1 + config.risk_management.take_profit_pct)
                if config.risk_management.atr_stop_multiplier:
                    atr_val = evaluate_indicator(df, {"name": "ATR", "period": 14}, signal_index_pos)
                    if atr_val > 0:
                        sl_price = effective_entry_price - (config.risk_management.atr_stop_multiplier * atr_val)

                # Sizing logic
                position_sizing_value = config.position_sizing.value

                if has_stop_loss and sl_price is not None:
                    # risk-based sizing
                    risk_cap = config.risk_per_trade_cap_pct
                    risk_amount = risk_cap * current_equity
                    risk_per_share = effective_entry_price - sl_price

                    if risk_per_share > 0:
                        target_size = risk_amount / risk_per_share
                    else:
                        target_size = (position_sizing_value * current_equity) / effective_entry_price

                    # Cap by position sizing % of equity limit
                    max_sizing_allocation = position_sizing_value * current_equity
                    size_from_sizing = max_sizing_allocation / effective_entry_price
                    size = min(target_size, size_from_sizing)
                else:
                    # Fallback to % of equity sizing
                    max_sizing_allocation = position_sizing_value * current_equity
                    size = max_sizing_allocation / effective_entry_price

                    logger = logging.getLogger("athenacell")
                    msg = f"Warning: Risk cap not applied for {ticker} because no stop-loss exists."
                    logger.warning(msg)
                    print(msg)

                # Cap by available cash (accounting for flat commission)
                max_cash_allocation = cash - config.commission
                if max_cash_allocation > 0:
                    size_from_cash = max_cash_allocation / effective_entry_price
                    size = min(size, size_from_cash)
                else:
                    size = 0.0

                if size > 0:
                    cash -= (size * effective_entry_price + config.commission)
                    positions[ticker] = {
                        "entry_price": effective_entry_price,
                        "entry_date": date,
                        "size": size,
                        "stop_loss": sl_price,
                        "take_profit": tp_price,
                        "last_known_price": effective_entry_price
                    }
            queued_entries.clear()

            # 3. Update current day's close valuations for held positions, and check signal triggers
            current_equity = cash
            for ticker, pos in list(positions.items()):
                df = tickers_data[ticker]
                if date in df.index:
                    current_price = float(df.loc[date, "close"])
                    pos["last_known_price"] = current_price
                    current_equity += pos["size"] * current_price

                    # Check exit triggers on Day N Close (executing on Day N+1 Open)
                    # 3a. Stop loss trigger
                    if pos["stop_loss"] and current_price <= pos["stop_loss"]:
                        queued_exits.append({"ticker": ticker, "reason": "stop_loss"})
                        continue

                    # 3b. Take profit trigger
                    if pos["take_profit"] and current_price >= pos["take_profit"]:
                        queued_exits.append({"ticker": ticker, "reason": "take_profit"})
                        continue

                    # 3c. Strategy EXIT Rule evaluation
                    index_pos = df.index.get_loc(date)
                    if evaluate_rule(exit_rules_dict, df, index_pos):
                        queued_exits.append({"ticker": ticker, "reason": "rule"})
                        continue
                else:
                    # Missing data: carry forward last known price
                    current_equity += pos["size"] * pos["last_known_price"]

            # Log daily equity at close of the day
            equity_history.append({
                "date": date.strftime("%Y-%m-%d"),
                "equity": current_equity
            })

            # 4. Check for new entry signals on Day N Close (executing on Day N+1 Open)
            active_slots = len(positions) + len(queued_entries) - len(queued_exits)
            if active_slots < config.max_concurrent_positions:
                shuffled_universe = list(config.universe)
                random.shuffle(shuffled_universe)

                for ticker in shuffled_universe:
                    if ticker in positions or ticker in queued_entries:
                        continue

                    df = tickers_data[ticker]
                    if date not in df.index:
                        continue

                    index_pos = df.index.get_loc(date)
                    if evaluate_rule(entry_rules_dict, df, index_pos):
                        queued_entries.append(ticker)
                        active_slots += 1
                        if active_slots >= config.max_concurrent_positions:
                            break

        # Close out any remaining positions at the end of the backtest
        end_date_ts = all_dates[-1]
        for ticker, pos in list(positions.items()):
            df = tickers_data[ticker]
            base_price = float(df.loc[end_date_ts, "close"]) if end_date_ts in df.index else pos["last_known_price"]

            # Apply slippage and commission
            effective_exit_price = base_price * (1 - config.slippage_pct)
            cash += pos["size"] * effective_exit_price - config.commission
            trades_log.append({
                "ticker": ticker,
                "entry_date": pos["entry_date"],
                "entry_price": pos["entry_price"],
                "exit_date": end_date_ts,
                "exit_price": effective_exit_price,
                "size": pos["size"],
                "profit_pct": (effective_exit_price - pos["entry_price"]) / pos["entry_price"],
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

        sharpe_val = sharpe_calc.calculate(daily_returns, equity_vals)
        dd_val = dd_calc.calculate(daily_returns, equity_vals)

        # Compute Win Rate directly from non-end_of_period trades as requested
        closed_trades = [t for t in trades_log if t["exit_reason"] != "end_of_period"]
        if closed_trades:
            winning_trades = [t for t in closed_trades if t["profit_pct"] > 0]
            win_rate_val = len(winning_trades) / len(closed_trades)
        else:
            win_rate_val = 0.0

        return {
            "sharpe": sharpe_val,
            "max_drawdown": dd_val,
            "win_rate": win_rate_val,
            "equity_curve": equity_history,
            "trades": trades_log,
            "risk_cap_applied": has_stop_loss
        }
