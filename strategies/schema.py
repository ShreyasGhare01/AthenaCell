import json
from typing import List, Union, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

# Supported technical indicators out-of-the-box:
# SMA, EMA, RSI, MACD, close > N-day high, Bollinger Bands, ATR.
IndicatorName = Literal["SMA", "EMA", "RSI", "MACD_LINE", "MACD_SIGNAL", "MACD_HIST", "BB_UPPER", "BB_LOWER", "BB_MIDDLE", "ATR", "PRICE_CLOSE", "PRICE_OPEN", "PRICE_HIGH", "PRICE_LOW", "VOLUME", "N_DAY_HIGH", "N_DAY_LOW"]

class IndicatorParam(BaseModel):
    name: IndicatorName
    period: Optional[int] = None
    field_ref: Optional[str] = None # e.g. "close", "high", "low"
    extra: Dict[str, Any] = Field(default_factory=dict)

class SimpleCondition(BaseModel):
    type: Literal["condition"] = "condition"
    indicator_a: IndicatorParam
    operator: Literal[">", "<", ">=", "<=", "==", "!="]
    # indicator_b can either be another indicator or a static numerical value
    indicator_b: Union[IndicatorParam, float]

# Forward references for nesting:
# A Rule can be a single condition, or a logical group (AND, OR, NOT) containing nested rules.
class LogicalRuleGroup(BaseModel):
    type: Literal["and", "or", "not"]
    rules: List[Union[SimpleCondition, 'LogicalRuleGroup']]

RuleType = Union[SimpleCondition, LogicalRuleGroup]

# Resolve the self-referencing forward declaration in Pydantic v2
LogicalRuleGroup.model_rebuild()

class PositionSizingRule(BaseModel):
    type: Literal["fixed_pct", "risk_adjusted_atr"] = "fixed_pct"
    value: float = 0.1 # e.g. 10% of portfolio value per position

class StopLossTakeProfit(BaseModel):
    stop_loss_pct: Optional[float] = None # e.g. 0.05 for 5%
    take_profit_pct: Optional[float] = None # e.g. 0.10 for 10%
    atr_stop_multiplier: Optional[float] = None # multiplier of ATR for stop

class StrategyConfig(BaseModel):
    id: str
    name: str
    universe: List[str]
    timeframe: Literal["1d", "1h"] = "1d"
    entry_rules: RuleType
    exit_rules: RuleType
    position_sizing: PositionSizingRule = Field(default_factory=PositionSizingRule)
    risk_management: StopLossTakeProfit = Field(default_factory=StopLossTakeProfit)
    max_concurrent_positions: int = 5
    risk_per_trade_cap_pct: float = 0.02 # Max risk 2% of portfolio value per trade

def validate_strategy_config(config_dict: dict) -> StrategyConfig:
    """Validates a strategy config dictionary against the Pydantic StrategyConfig schema."""
    return StrategyConfig.model_validate(config_dict)

def save_json_schema(filepath: str):
    """Saves the JSON schema representation of the StrategyConfig Pydantic model to a file."""
    schema = StrategyConfig.model_json_schema()
    with open(filepath, "w") as f:
        json.dump(schema, f, indent=2)
