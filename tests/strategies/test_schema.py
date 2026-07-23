import pytest
import os
from strategies.schema import validate_strategy_config, StrategyConfig, save_json_schema

def test_valid_sma_cross_rsi():
    import json
    path = "strategies/examples/sma_cross_rsi.json"
    assert os.path.exists(path)
    with open(path, "r") as f:
        data = json.load(f)
    config = validate_strategy_config(data)
    assert isinstance(config, StrategyConfig)
    assert config.id == "sma_cross_rsi"
    assert config.max_concurrent_positions == 5

def test_valid_bb_breakout_atr_stop():
    import json
    path = "strategies/examples/bb_breakout_atr_stop.json"
    assert os.path.exists(path)
    with open(path, "r") as f:
        data = json.load(f)
    config = validate_strategy_config(data)
    assert isinstance(config, StrategyConfig)
    assert config.id == "bb_breakout_atr_stop"

def test_invalid_config():
    import json
    from pydantic import ValidationError
    invalid_data = {
        "id": "invalid",
        "name": "Invalid strategy",
        "universe": ["AAPL"],
        "entry_rules": {
            "type": "invalid_type",
            "rules": []
        },
        "exit_rules": {
            "type": "condition",
            "indicator_a": {
                "name": "INVALID_INDICATOR"
            },
            "operator": ">>>",
            "indicator_b": 0.0
        }
    }
    with pytest.raises(ValidationError):
        validate_strategy_config(invalid_data)

def test_save_json_schema():
    out_path = "config/schema/strategy_config_schema.json"
    save_json_schema(out_path)
    assert os.path.exists(out_path)
    with open(out_path, "r") as f:
        schema = f.read()
    assert "StrategyConfig" in schema
