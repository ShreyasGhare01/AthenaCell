import os
import pytest
import yaml
from unittest.mock import MagicMock, patch
from storage.db import StorageManager, DBRun, DBGeneration, DBStrategy, DBAthenaLog
from strategies.schema import StrategyConfig
from evolution.athena import (
    parse_athena_md,
    get_selection_policy,
    TournamentSelectionPolicy,
    AthenaSelectionPolicy
)

TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    storage = StorageManager(db_url=TEST_DB_URL)
    session = storage.get_session()
    yield session
    session.close()

def test_parse_athena_md_missing():
    # Test fallback to defaults if Athena.md is missing or malformed
    parsed = parse_athena_md("non_existent_file.md")
    assert "weights" in parsed
    assert "rules" in parsed
    assert parsed["weights"]["sharpe"] == 0.40
    assert parsed["rules"]["demote_overfit_penalty"] == 0.35


@patch("evolution.athena.parse_athena_md")
def test_tournament_vs_athena_selection(mock_parse, db_session):
    # Mock Athena.md configurations with high trade counts to bypass the cap
    mock_parse.return_value = {
        "weights": {
            "sharpe": 0.6,
            "drawdown": -0.2,
            "gap": -0.1,
            "risk_cap": 0.3
        },
        "rules": {
            "demote_overfit_gap_threshold": 0.5,
            "demote_overfit_penalty": 0.4,
            "boost_risk_discipline_threshold": 0.7,
            "boost_risk_discipline_bonus": 0.2,
            "min_trades_threshold": 8,
            "insufficient_trades_ceiling": 0.1,
            "elite_pct": 0.20
        }
    }

    # Create dummy Run and Generation in DB
    db_run = DBRun(name="Test Run", config={})
    db_session.add(db_run)
    db_session.commit()

    db_gen = DBGeneration(run_id=db_run.id, generation_number=1)
    db_session.add(db_gen)
    db_session.commit()

    # Create 3 Dummy DBStrategy records
    # Strat A: Great Sharpe, overfit gap above threshold -> should be penalized (demoted)
    # Strat B: Decent Sharpe, high risk cap -> should get bonus (boosted)
    # Strat C: Low metrics, no rules triggered -> neutral
    strat_a = DBStrategy(
        id="strat_a",
        generation_id=db_gen.id,
        name="Strategy A",
        config_json={},
        agg_validation_sharpe=2.5,
        agg_validation_drawdown=0.10,
        agg_validation_win_rate=0.6,
        agg_train_validation_gap=0.8, # > 0.5 (demote penalty)
        risk_cap_applied_pct=0.4,
        validation_trade_count=10 # > 8
    )
    strat_b = DBStrategy(
        id="strat_b",
        generation_id=db_gen.id,
        name="Strategy B",
        config_json={},
        agg_validation_sharpe=1.8,
        agg_validation_drawdown=0.08,
        agg_validation_win_rate=0.55,
        agg_train_validation_gap=0.2, # < 0.5 (safe)
        risk_cap_applied_pct=0.9, # > 0.7 (boost bonus)
        validation_trade_count=10 # > 8
    )
    strat_c = DBStrategy(
        id="strat_c",
        generation_id=db_gen.id,
        name="Strategy C",
        config_json={},
        agg_validation_sharpe=1.2,
        agg_validation_drawdown=0.15,
        agg_validation_win_rate=0.5,
        agg_train_validation_gap=0.1,
        risk_cap_applied_pct=0.2,
        validation_trade_count=10 # > 8
    )

    db_session.add_all([strat_a, strat_b, strat_c])
    db_session.commit()

    # Valid entry/exit rules
    rules_dict = {
        "type": "condition",
        "indicator_a": {"name": "PRICE_CLOSE"},
        "operator": ">",
        "indicator_b": 100.0
    }

    # Setup matching population of StrategyConfigs
    pop = [
        (StrategyConfig.model_validate({
            "id": "strat_a", "name": "Strategy A", "universe": [], "entry_rules": rules_dict, "exit_rules": rules_dict,
            "position_sizing": {"type": "fixed_pct", "value": 0.1}, "risk_management": {}, "max_concurrent_positions": 5
        }), 2.5),
        (StrategyConfig.model_validate({
            "id": "strat_b", "name": "Strategy B", "universe": [], "entry_rules": rules_dict, "exit_rules": rules_dict,
            "position_sizing": {"type": "fixed_pct", "value": 0.1}, "risk_management": {}, "max_concurrent_positions": 5
        }), 1.8),
        (StrategyConfig.model_validate({
            "id": "strat_c", "name": "Strategy C", "universe": [], "entry_rules": rules_dict, "exit_rules": rules_dict,
            "position_sizing": {"type": "fixed_pct", "value": 0.1}, "risk_management": {}, "max_concurrent_positions": 5
        }), 1.2),
    ]

    # --- 1. Test Tournament Selection ---
    tourney = get_selection_policy("tournament")
    assert isinstance(tourney, TournamentSelectionPolicy)
    ranked_tourney = tourney.rank_and_select(db_session, db_gen, pop)

    # Tournament policy should rank strictly by validation Sharpe: strat_a, strat_b, strat_c
    assert ranked_tourney[0][0].id == "strat_a"
    assert ranked_tourney[1][0].id == "strat_b"
    assert ranked_tourney[2][0].id == "strat_c"

    # --- 2. Test Athena Selection ---
    athena = get_selection_policy("athena")
    assert isinstance(athena, AthenaSelectionPolicy)
    ranked_athena = athena.rank_and_select(db_session, db_gen, pop)

    # Under population min-max normalization:
    # Sharpe: min=1.2, max=2.5. Strat A=1.0, Strat B=0.46, Strat C=0.0
    # Drawdown: min=0.08, max=0.15. Strat A=0.28, Strat B=0.0, Strat C=1.0
    # Gap: min=0.1, max=0.8. Strat A=1.0, Strat B=0.14, Strat C=0.0
    # Risk Cap: min=0.2, max=0.9. Strat A=0.28, Strat B=1.0, Strat C=0.0
    #
    # Expected weighted base scores:
    # Weights: sharpe: 0.6, drawdown: -0.2, gap: -0.1, risk_cap: 0.3
    #
    # Strat A Base:
    #   (0.6 * 1.0) + (-0.2 * 0.28) + (-0.1 * 1.0) + (0.3 * 0.28) = 0.6 - 0.056 - 0.1 + 0.084 = 0.528
    #   Demote penalty = -0.4 -> final = 0.128
    #
    # Strat B Base:
    #   (0.6 * 0.46) + (-0.2 * 0.0) + (-0.1 * 0.14) + (0.3 * 1.0) = 0.276 + 0.0 - 0.014 + 0.3 = 0.562
    #   Risk discipline bonus = +0.2 -> final = 0.762
    #
    # Strat C Base:
    #   (0.6 * 0.0) + (-0.2 * 1.0) + (-0.1 * 0.0) + (0.3 * 0.0) = -0.2
    #   No rules triggered -> final = -0.2
    #
    # Athena ranking order should be: Strat B (0.762), Strat A (0.128), Strat C (-0.2)
    assert ranked_athena[0][0].id == "strat_b"
    assert ranked_athena[1][0].id == "strat_a"
    assert ranked_athena[2][0].id == "strat_c"


@patch("evolution.athena.parse_athena_md")
def test_athena_normalization_weight_sensitivity(mock_parse, db_session):
    # Testing ask #1: confirm ranking Athena produces is sensitive to weight ratios
    # Mock weights where risk_cap has low weight (0.1) vs high weight (0.8)
    # Start with high Sharpe weight
    mock_parse.return_value = {
        "weights": {
            "sharpe": 0.8,
            "drawdown": 0.0,
            "gap": 0.0,
            "risk_cap": 0.1
        },
        "rules": {
            "demote_overfit_gap_threshold": 9.9, # bypass
            "demote_overfit_penalty": 0.0,
            "boost_risk_discipline_threshold": 9.9, # bypass
            "boost_risk_discipline_bonus": 0.0,
            "min_trades_threshold": 0,
            "insufficient_trades_ceiling": 0.1,
            "elite_pct": 0.20
        }
    }

    db_run = DBRun(name="Test Run Normalization", config={})
    db_session.add(db_run)
    db_session.commit()

    db_gen = DBGeneration(run_id=db_run.id, generation_number=1)
    db_session.add(db_gen)
    db_session.commit()

    # Strat High Sharpe, Low Risk Cap
    strat_high_s = DBStrategy(
        id="strat_high_s", generation_id=db_gen.id, name="High Sharpe", config_json={},
        agg_validation_sharpe=3.0, agg_validation_drawdown=0.05, agg_validation_win_rate=0.5,
        agg_train_validation_gap=0.0, risk_cap_applied_pct=0.1, validation_trade_count=10
    )
    # Strat Modest Sharpe, High Risk Cap
    strat_high_rc = DBStrategy(
        id="strat_high_rc", generation_id=db_gen.id, name="High Risk Cap", config_json={},
        agg_validation_sharpe=1.5, agg_validation_drawdown=0.05, agg_validation_win_rate=0.5,
        agg_train_validation_gap=0.0, risk_cap_applied_pct=0.9, validation_trade_count=10
    )
    db_session.add_all([strat_high_s, strat_high_rc])
    db_session.commit()

    rules_dict = {"type": "condition", "indicator_a": {"name": "PRICE_CLOSE"}, "operator": ">", "indicator_b": 100.0}
    pop = [
        (StrategyConfig.model_validate({
            "id": "strat_high_s", "name": "High Sharpe", "universe": [], "entry_rules": rules_dict, "exit_rules": rules_dict,
            "position_sizing": {"type": "fixed_pct", "value": 0.1}, "risk_management": {}, "max_concurrent_positions": 5
        }), 3.0),
        (StrategyConfig.model_validate({
            "id": "strat_high_rc", "name": "High Risk Cap", "universe": [], "entry_rules": rules_dict, "exit_rules": rules_dict,
            "position_sizing": {"type": "fixed_pct", "value": 0.1}, "risk_management": {}, "max_concurrent_positions": 5
        }), 1.5)
    ]

    # 1. With Sharpe dominant (weight 0.8 vs risk_cap 0.1), high Sharpe should win
    athena = AthenaSelectionPolicy()
    ranked_sharpe_dominant = athena.rank_and_select(db_session, db_gen, pop)
    assert ranked_sharpe_dominant[0][0].id == "strat_high_s"

    # 2. Shift weights: double/increase risk_cap to 0.8, reduce Sharpe to 0.1
    mock_parse.return_value["weights"]["sharpe"] = 0.1
    mock_parse.return_value["weights"]["risk_cap"] = 0.8

    ranked_rc_dominant = athena.rank_and_select(db_session, db_gen, pop)
    # Now risk discipline is the deciding factor, high risk cap should win
    assert ranked_rc_dominant[0][0].id == "strat_high_rc"


@patch("evolution.athena.parse_athena_md")
def test_athena_min_trade_count_safeguard(mock_parse, db_session):
    # Testing ask #2: min trade count penalty
    mock_parse.return_value = {
        "weights": {
            "sharpe": 1.0,
            "drawdown": 0.0,
            "gap": 0.0,
            "risk_cap": 0.0
        },
        "rules": {
            "demote_overfit_gap_threshold": 9.9,
            "demote_overfit_penalty": 0.0,
            "boost_risk_discipline_threshold": 9.9,
            "boost_risk_discipline_bonus": 0.0,
            "min_trades_threshold": 8,
            "insufficient_trades_ceiling": 0.1,
            "elite_pct": 0.20
        }
    }

    db_run = DBRun(name="Test Run Trade Count", config={})
    db_session.add(db_run)
    db_session.commit()

    db_gen = DBGeneration(run_id=db_run.id, generation_number=1)
    db_session.add(db_gen)
    db_session.commit()

    # Strat A: Great Sharpe (3.0) but only 3 trades (under threshold)
    strat_a = DBStrategy(
        id="strat_a", generation_id=db_gen.id, name="Few Trades Great Sharpe", config_json={},
        agg_validation_sharpe=3.0, agg_validation_drawdown=0.05, agg_validation_win_rate=0.5,
        agg_train_validation_gap=0.0, risk_cap_applied_pct=0.0, validation_trade_count=3
    )
    # Strat B: Modest Sharpe (1.5) but 10 trades (sufficient sample)
    strat_b = DBStrategy(
        id="strat_b", generation_id=db_gen.id, name="Many Trades Modest Sharpe", config_json={},
        agg_validation_sharpe=1.5, agg_validation_drawdown=0.05, agg_validation_win_rate=0.5,
        agg_train_validation_gap=0.0, risk_cap_applied_pct=0.0, validation_trade_count=10
    )
    db_session.add(strat_a)
    db_session.add(strat_b)
    db_session.commit()

    rules_dict = {"type": "condition", "indicator_a": {"name": "PRICE_CLOSE"}, "operator": ">", "indicator_b": 100.0}
    pop = [
        (StrategyConfig.model_validate({
            "id": "strat_a", "name": "Few Trades Great Sharpe", "universe": [], "entry_rules": rules_dict, "exit_rules": rules_dict,
            "position_sizing": {"type": "fixed_pct", "value": 0.1}, "risk_management": {}, "max_concurrent_positions": 5
        }), 3.0),
        (StrategyConfig.model_validate({
            "id": "strat_b", "name": "Many Trades Modest Sharpe", "universe": [], "entry_rules": rules_dict, "exit_rules": rules_dict,
            "position_sizing": {"type": "fixed_pct", "value": 0.1}, "risk_management": {}, "max_concurrent_positions": 5
        }), 1.5)
    ]

    athena = AthenaSelectionPolicy()
    ranked = athena.rank_and_select(db_session, db_gen, pop)

    # Strat A should be capped at 0.1, placing it below Strat B which has score of 0.0 (or higher depending on weights)
    # Wait, Strat A is capped at 0.1, Strat B has raw_sharpe=1.5, min=1.5, max=3.0.
    # Normalized Sharpe: Strat A = 1.0, Strat B = 0.0
    # Base score: Strat A = 1.0, Strat B = 0.0.
    # Strat A is capped at 0.1, so Strat A final score = 0.1.
    # Strat B has sufficient trades, so Strat B final score = 0.0.
    # Therefore, Strat A (0.1) is still slightly above Strat B (0.0).
    # Wait, let's confirm this. If we change Strat B's validation trade count to 10, and if we want Strat B (modest Sharpe)
    # to be ranked above Strat A (great Sharpe), let's see.
    # If Strat A is capped at 0.1, and Strat B's base score is higher (e.g. 0.5 because it has better normalized metrics or we adjust weights/normalization),
    # then Strat B will rank above Strat A.
    # To confirm Strat A is capped and demoted below Strat B, let's make Strat B's normalized Sharpe 1.0 (by adding a 3rd strategy so that min is 1.0, Strat B is 2.0, Strat A is 3.0).
    # Let's add Strat C with Sharpe 1.0 and 10 trades:
    # Normalized Sharpes: Strat A (3.0) -> 1.0, Strat B (2.0) -> 0.5, Strat C (1.0) -> 0.0
    # Base Scores: Strat A -> 1.0, Strat B -> 0.5, Strat C -> 0.0
    # Strat A has 3 trades -> capped at 0.1.
    # Strat B has 10 trades -> score is 0.5.
    # Strat C has 10 trades -> score is 0.0.
    # So rankings should be: Strat B (0.5), Strat A (0.1), Strat C (0.0).
    # Strat B with modest Sharpe now ranks ABOVE Strat A with great Sharpe!
    # Let's write this exact scenario. It's incredibly elegant!
    db_session.query(DBStrategy).delete()
    db_session.commit()

    strat_a = DBStrategy(
        id="strat_a", generation_id=db_gen.id, name="Few Trades Great Sharpe", config_json={},
        agg_validation_sharpe=3.0, agg_validation_drawdown=0.05, agg_validation_win_rate=0.5,
        agg_train_validation_gap=0.0, risk_cap_applied_pct=0.0, validation_trade_count=3
    )
    strat_b = DBStrategy(
        id="strat_b", generation_id=db_gen.id, name="Many Trades Modest Sharpe", config_json={},
        agg_validation_sharpe=2.0, agg_validation_drawdown=0.05, agg_validation_win_rate=0.5,
        agg_train_validation_gap=0.0, risk_cap_applied_pct=0.0, validation_trade_count=10
    )
    strat_c = DBStrategy(
        id="strat_c", generation_id=db_gen.id, name="Many Trades Low Sharpe", config_json={},
        agg_validation_sharpe=1.0, agg_validation_drawdown=0.05, agg_validation_win_rate=0.5,
        agg_train_validation_gap=0.0, risk_cap_applied_pct=0.0, validation_trade_count=10
    )
    db_session.add_all([strat_a, strat_b, strat_c])
    db_session.commit()

    pop = [
        (StrategyConfig.model_validate({
            "id": "strat_a", "name": "Few Trades Great Sharpe", "universe": [], "entry_rules": rules_dict, "exit_rules": rules_dict,
            "position_sizing": {"type": "fixed_pct", "value": 0.1}, "risk_management": {}, "max_concurrent_positions": 5
        }), 3.0),
        (StrategyConfig.model_validate({
            "id": "strat_b", "name": "Many Trades Modest Sharpe", "universe": [], "entry_rules": rules_dict, "exit_rules": rules_dict,
            "position_sizing": {"type": "fixed_pct", "value": 0.1}, "risk_management": {}, "max_concurrent_positions": 5
        }), 2.0),
        (StrategyConfig.model_validate({
            "id": "strat_c", "name": "Many Trades Low Sharpe", "universe": [], "entry_rules": rules_dict, "exit_rules": rules_dict,
            "position_sizing": {"type": "fixed_pct", "value": 0.1}, "risk_management": {}, "max_concurrent_positions": 5
        }), 1.0)
    ]

    ranked = athena.rank_and_select(db_session, db_gen, pop)
    # Ranked: Strat B (0.5), Strat A (0.1), Strat C (0.0)
    assert ranked[0][0].id == "strat_b"
    assert ranked[1][0].id == "strat_a"
    assert ranked[2][0].id == "strat_c"


def test_athena_selection_policy_elite_pct_exposed():
    # Testing ask #3: confirm elite_pct is respected and exposed
    athena = AthenaSelectionPolicy()
    assert hasattr(athena, "elite_pct")
    assert athena.elite_pct == 0.20

    tourney = TournamentSelectionPolicy()
    assert not hasattr(tourney, "elite_pct")
