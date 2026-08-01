---
weights:
  sharpe: 0.5
  drawdown: -0.2
  gap: -0.1
  risk_cap: 0.2

rules:
  demote_overfit_gap_threshold: 0.5    # Demote if train/val Sharpe gap > 0.5
  demote_overfit_penalty: 0.3          # Subtract 0.3 from Athena score
  boost_risk_discipline_threshold: 0.8 # Boost if risk_cap_applied_pct > 80%
  boost_risk_discipline_bonus: 0.1     # Add 0.1 to Athena score
---

# Athena Selection Philosophy

This document guides Athena, the Lead Selection Agent, on how to score, promote, and demote candidate trading strategies in the AthenaCell Research Sandbox.

Athena applies a strict risk-and-overfit-aware scoring framework to guide populations towards robust performance rather than raw curve-fitting.

## Pluggable Weights
- **Validation Sharpe Ratio (Weight: 0.5)**: Measures risk-adjusted returns during validation folds. Higher is rewarded.
- **Validation Max Drawdown (Weight: -0.2)**: Penalizes severe peak-to-trough losses. Larger drawdowns result in larger penalties.
- **Train-to-Validation Gap (Weight: -0.1)**: Penalizes strategies where the training Sharpe is much higher than the validation Sharpe, indicating curve-fitting/overfitting.
- **Risk Cap Applied Pct (Weight: 0.2)**: Rewards strategies that consistently execute with strict risk discipline (e.g., active stop-losses/position-sizing limits).

## Rule-Based Adjustments
- **Overfit Prevention Rule**: If a strategy's Train-to-Validation Sharpe Ratio gap exceeds `0.5`, it is penalized by subtracting `0.3` from its overall score to prevent overfit candidates from surviving.
- **Risk Discipline Rule**: If a strategy applies risk-cap sizing on more than `80%` of its trades, it is boosted by adding `0.1` to its overall score to reward capital protection discipline.
