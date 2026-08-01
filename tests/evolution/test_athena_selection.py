import os
import pytest
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
    assert parsed["weights"]["sharpe"] == 0.5
    assert parsed["rules"]["demote_overfit_penalty"] == 0.3

@patch("evolution.athena.parse_athena_md")
def test_tournament_vs_athena_selection(mock_parse, db_session):
    # Mock Athena.md configurations
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
            "boost_risk_discipline_bonus": 0.2
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
        risk_cap_applied_pct=0.4
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
        risk_cap_applied_pct=0.9 # > 0.7 (boost bonus)
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
        risk_cap_applied_pct=0.2
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

    # Tournament policy should rank strictly by validation Sharpe: strat_a (2.5), strat_b (1.8), strat_c (1.2)
    assert ranked_tourney[0][0].id == "strat_a"
    assert ranked_tourney[1][0].id == "strat_b"
    assert ranked_tourney[2][0].id == "strat_c"

    # --- 2. Test Athena Selection ---
    athena = get_selection_policy("athena")
    assert isinstance(athena, AthenaSelectionPolicy)
    ranked_athena = athena.rank_and_select(db_session, db_gen, pop)

    # Let's calculate expected Athena Scores:
    # Weights: sharpe: 0.6, drawdown: -0.2, gap: -0.1, risk_cap: 0.3
    # Rules: demote gap (>0.5): -0.4, boost risk cap (>0.7): +0.2
    #
    # Strat A:
    #   base = (0.6 * 2.5) + (-0.2 * 0.10) + (-0.1 * 0.8) + (0.3 * 0.4) = 1.5 - 0.02 - 0.08 + 0.12 = 1.52
    #   gap of 0.8 triggers demote (-0.4) -> final = 1.12
    #
    # Strat B:
    #   base = (0.6 * 1.8) + (-0.2 * 0.08) + (-0.1 * 0.2) + (0.3 * 0.9) = 1.08 - 0.016 - 0.02 + 0.27 = 1.314
    #   risk cap of 0.9 triggers boost (+0.2) -> final = 1.514
    #
    # Strat C:
    #   base = (0.6 * 1.2) + (-0.2 * 0.15) + (-0.1 * 0.1) + (0.3 * 0.2) = 0.72 - 0.03 - 0.01 + 0.06 = 0.74
    #   no rules triggered -> final = 0.74
    #
    # Athena ranking order should be: Strat B (1.514), Strat A (1.12), Strat C (0.74)
    assert ranked_athena[0][0].id == "strat_b"
    assert ranked_athena[1][0].id == "strat_a"
    assert ranked_athena[2][0].id == "strat_c"

    # Assert that a DBAthenaLog was written to the database for this generation
    db_log = db_session.query(DBAthenaLog).filter_by(generation_id=db_gen.id).first()
    assert db_log is not None
    assert "Strategy B" in db_log.entry_text
    assert "Strategy A" in db_log.entry_text
