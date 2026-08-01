---
weights:
  sharpe: 0.40
  drawdown: -0.20
  gap: -0.25
  risk_cap: 0.15

rules:
  demote_overfit_gap_threshold: 0.5
  demote_overfit_penalty: 0.35
  boost_risk_discipline_threshold: 0.85
  boost_risk_discipline_bonus: 0.12
  min_trades_threshold: 8
  insufficient_trades_ceiling: 0.1
  elite_pct: 0.20
---

# Athena Selection Philosophy

Athena is the lead selection agent of AthenaCell. Her job is to decide, at the end of
every generation, which strategies survive, reproduce, and propagate their traits
forward — and which don't. This file is the only place that decision-making logic
lives. Athena does not write to this file or reinterpret it; she reads it exactly as
written. If her behavior needs to change, this file is what changes.

## Priorities, in order

1. **Don't reward luck.** A strategy that traded rarely and got lucky is worth less
   than a strategy that traded consistently and performed honestly, even if the lucky
   one's raw Sharpe ratio looks better on paper. See `min_trades_threshold` below.
2. **Don't reward overfitting.** A strategy that looks great on training data and
   mediocre on validation data is showing you curve-fitting, not skill. The gap
   between the two matters as much as the validation performance itself.
3. **Reward risk discipline.** A strategy that respects its own stated risk limits
   on most of its trades has demonstrated something real about how it will behave
   with money on the line, independent of whether this particular backtest window
   was favorable to it.
4. **Then, and only then, reward raw performance.** Sharpe ratio and drawdown matter,
   but they are the last filter applied, not the first.

## Weights

Applied to each metric after it's been normalized (0-1 scale) across the current
generation's population, so these weights represent genuine relative importance,
not raw units:

- **`sharpe` (0.40):** Validation-period Sharpe ratio. The primary performance signal,
  but deliberately not the dominant term — see priorities above.
- **`drawdown` (-0.20):** Validation-period max drawdown. Penalized — a strategy that
  occasionally posts good returns via large peak-to-trough swings is not what this
  project is trying to find.
- **`gap` (-0.25):** Difference between training and validation Sharpe. Weighted the
  most heavily of the penalty terms, deliberately — overfitting is the single most
  common way an evolutionary strategy search fools itself, and this project exists
  partly to guard against exactly that.
- **`risk_cap` (0.15):** Percentage of trades where risk-based position sizing was
  actually applied (`risk_cap_applied_pct`). A meaningful but secondary signal —
  it rewards strategies that are honest about risk, without letting a strategy
  "win" purely by having a stop-loss configured while otherwise underperforming.

## Rules

- **Overfit demotion:** if the train/validation Sharpe gap exceeds
  `demote_overfit_gap_threshold` (0.5), subtract `demote_overfit_penalty` (0.35)
  from the final score. This is a hard penalty on top of the weighted `gap` term
  above — overfitting is penalized twice, once continuously and once as a
  threshold cutoff, because it's the failure mode this whole selection system
  is most worried about.
- **Risk discipline bonus:** if `risk_cap_applied_pct` exceeds
  `boost_risk_discipline_threshold` (0.85), add `boost_risk_discipline_bonus`
  (0.12) to the final score.
- **Insufficient sample penalty:** if a strategy's total validation trade count
  is below `min_trades_threshold` (8), its final score is capped at
  `insufficient_trades_ceiling` (0.1). A strategy with a great
  Sharpe on 3 trades hasn't demonstrated anything yet — it gets to stay in the
  population (it might turn into something real after more mutation and more
  data), but it doesn't get to lead the generation on a small sample.

## Reward strength

- **`elite_pct` (0.20):** the top 20% of the ranked population survives unchanged
  into the next generation and becomes eligible to serve as crossover parents.
  This is the literal mechanism of "reward" in this system — surviving and
  reproducing. Raising this value makes survival less competitive (more
  strategies persist generation to generation); lowering it makes selection
  pressure more aggressive (fewer survive, population turns over faster).

## A note on tuning this file

If you change these values, do it deliberately and watch what happens over a
few generations — a swing that's too aggressive in either direction (e.g.
`gap` weighted so heavily that no strategy survives, or `min_trades_threshold`
so low it stops filtering anything) will show up as a leaderboard that stops
producing interesting results. Athena's journal entries are the place to check
this: if every entry says "no special rules triggered," the rules are probably
too lenient to matter; if every strategy is getting demoted, they're probably
too strict.
