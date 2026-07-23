import random
import uuid
from typing import List, Dict, Any
from evolution.base import MutationOperator, CrossoverOperator, StrategySeedSource
from strategies.schema import StrategyConfig, SimpleCondition, LogicalRuleGroup, IndicatorParam, PositionSizingRule, StopLossTakeProfit

INDICATORS = ["SMA", "EMA", "RSI", "MACD_LINE", "BB_UPPER", "BB_LOWER", "ATR"]
OPERATORS = [">", "<", ">=", "<="]

def create_random_indicator() -> Dict[str, Any]:
    name = random.choice(INDICATORS)
    period = random.choice([5, 10, 14, 20, 50, 100, 200])
    return {
        "name": name,
        "period": period,
        "field_ref": "close",
        "extra": {}
    }

def create_random_rule() -> Dict[str, Any]:
    # 80% simple condition, 20% nested rule group
    if random.random() < 0.8:
        return {
            "type": "condition",
            "indicator_a": {
                "name": random.choice(["PRICE_CLOSE", "RSI"])
            },
            "operator": random.choice(OPERATORS),
            "indicator_b": random.choice([float(random.randint(10, 90)), create_random_indicator()])
        }
    else:
        return {
            "type": "and",
            "rules": [
                {
                    "type": "condition",
                    "indicator_a": {"name": "PRICE_CLOSE"},
                    "operator": random.choice(OPERATORS),
                    "indicator_b": create_random_indicator()
                },
                {
                    "type": "condition",
                    "indicator_a": {"name": "RSI"},
                    "operator": random.choice(OPERATORS),
                    "indicator_b": float(random.randint(20, 80))
                }
            ]
        }

class RandomStrategyGenerator(StrategySeedSource):
    """
    A concrete StrategySeedSource that constructs completely random strategy genomes.
    """
    def __init__(self, universe: List[str] = None):
        self.universe = universe or ["AAPL", "MSFT", "GOOGL"]

    def generate(self) -> StrategyConfig:
        strat_id = f"rand_{uuid.uuid4().hex[:8]}"
        config_dict = {
            "id": strat_id,
            "name": f"Random Strategy {strat_id}",
            "universe": self.universe,
            "timeframe": "1d",
            "entry_rules": create_random_rule(),
            "exit_rules": create_random_rule(),
            "position_sizing": {
                "type": "fixed_pct",
                "value": round(random.uniform(0.05, 0.2), 2)
            },
            "risk_management": {
                "stop_loss_pct": round(random.uniform(0.02, 0.1), 2),
                "take_profit_pct": round(random.uniform(0.05, 0.3), 2)
            },
            "max_concurrent_positions": random.choice([3, 5, 7]),
            "risk_per_trade_cap_pct": 0.02
        }
        return StrategyConfig.model_validate(config_dict)

class ParameterJitterMutator(MutationOperator):
    """
    Randomly jitters numeric strategy thresholds and periods.
    """
    def mutate(self, strategy: StrategyConfig, reason_log: list) -> StrategyConfig:
        strat_dict = strategy.model_dump()
        strat_dict["id"] = f"mut_{uuid.uuid4().hex[:8]}"
        strat_dict["name"] = f"Jittered {strategy.name}"

        # Jitter stop loss & take profit
        if strat_dict["risk_management"]["stop_loss_pct"]:
            old_sl = strat_dict["risk_management"]["stop_loss_pct"]
            new_sl = max(0.01, min(0.2, old_sl + random.choice([-0.01, 0.01])))
            strat_dict["risk_management"]["stop_loss_pct"] = round(new_sl, 2)
            reason_log.append(f"Jittered stop_loss_pct from {old_sl} to {round(new_sl, 2)}")

        if strat_dict["risk_management"]["take_profit_pct"]:
            old_tp = strat_dict["risk_management"]["take_profit_pct"]
            new_tp = max(0.02, min(0.5, old_tp + random.choice([-0.02, 0.02])))
            strat_dict["risk_management"]["take_profit_pct"] = round(new_tp, 2)
            reason_log.append(f"Jittered take_profit_pct from {old_tp} to {round(new_tp, 2)}")

        return StrategyConfig.model_validate(strat_dict)

class IndicatorThresholdDriftMutator(MutationOperator):
    """
    Alters rules' numerical bounds/indicator values.
    """
    def mutate(self, strategy: StrategyConfig, reason_log: list) -> StrategyConfig:
        strat_dict = strategy.model_dump()
        strat_dict["id"] = f"mut_{uuid.uuid4().hex[:8]}"
        strat_dict["name"] = f"Drifted {strategy.name}"

        def recurse_drift(rule):
            if rule.get("type") in ["and", "or", "not"]:
                for r in rule.get("rules", []):
                    recurse_drift(r)
            else:
                # Simple condition: drift indicator_b if it's float
                if isinstance(rule.get("indicator_b"), (int, float)):
                    old_val = rule["indicator_b"]
                    drift = random.choice([-5.0, 5.0]) if old_val > 20 else random.choice([-0.5, 0.5])
                    rule["indicator_b"] = max(0.1, old_val + drift)
                    reason_log.append(f"Drifted indicator parameter from {old_val} to {rule['indicator_b']}")

        recurse_drift(strat_dict["entry_rules"])
        recurse_drift(strat_dict["exit_rules"])
        return StrategyConfig.model_validate(strat_dict)

class RuleSwapMutator(MutationOperator):
    """
    Swaps entry rules and exit rules or replaces them completely.
    """
    def mutate(self, strategy: StrategyConfig, reason_log: list) -> StrategyConfig:
        strat_dict = strategy.model_dump()
        strat_dict["id"] = f"mut_{uuid.uuid4().hex[:8]}"
        strat_dict["name"] = f"Swapped {strategy.name}"

        # Swap entry and exit rules
        strat_dict["entry_rules"], strat_dict["exit_rules"] = strat_dict["exit_rules"], strat_dict["entry_rules"]
        reason_log.append("Swapped entry and exit rules completely.")
        return StrategyConfig.model_validate(strat_dict)

class UniformCrossover(CrossoverOperator):
    """
    Combines rule structures from parent A and parent B.
    """
    def crossover(self, parent_a: StrategyConfig, parent_b: StrategyConfig, reason_log: list) -> StrategyConfig:
        dict_a = parent_a.model_dump()
        dict_b = parent_b.model_dump()

        child_dict = {
            "id": f"cross_{uuid.uuid4().hex[:8]}",
            "name": f"Crossover of {parent_a.name} and {parent_b.name}",
            "universe": parent_a.universe,
            "timeframe": parent_a.timeframe,
            "entry_rules": dict_a["entry_rules"] if random.random() < 0.5 else dict_b["entry_rules"],
            "exit_rules": dict_b["exit_rules"] if random.random() < 0.5 else dict_a["exit_rules"],
            "position_sizing": dict_a["position_sizing"] if random.random() < 0.5 else dict_b["position_sizing"],
            "risk_management": dict_a["risk_management"] if random.random() < 0.5 else dict_b["risk_management"],
            "max_concurrent_positions": random.choice([parent_a.max_concurrent_positions, parent_b.max_concurrent_positions]),
            "risk_per_trade_cap_pct": parent_a.risk_per_trade_cap_pct
        }
        reason_log.append(f"Performed crossover between parent '{parent_a.id}' and parent '{parent_b.id}'")
        return StrategyConfig.model_validate(child_dict)


class EvolutionRegistry:
    _mutators = {
        "parameter_jitter": ParameterJitterMutator,
        "indicator_threshold_drift": IndicatorThresholdDriftMutator,
        "rule_swap": RuleSwapMutator
    }
    _crossovers = {
        "uniform": UniformCrossover
    }

    @classmethod
    def get_mutator(cls, name: str) -> MutationOperator:
        if name not in cls._mutators:
            raise ValueError(f"Unknown mutator: {name}")
        return cls._mutators[name]()

    @classmethod
    def get_crossover(cls, name: str) -> CrossoverOperator:
        if name not in cls._crossovers:
            raise ValueError(f"Unknown crossover: {name}")
        return cls._crossovers[name]()
