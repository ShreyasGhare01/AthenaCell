import os
import yaml
import json
import logging
import datetime
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Union, Optional
import anthropic
from storage.db import DBStrategy, DBAthenaLog
from strategies.schema import StrategyConfig

logger = logging.getLogger("athenacell")

def parse_athena_md(filepath: str = "Athena.md") -> Dict[str, Any]:
    """
    Parses the YAML frontmatter from Athena.md. If missing or malformed,
    returns standard, robust default parameters. Also performs validation
    and appends any validation warnings to the "validation_warnings" list.
    """
    defaults = {
        "weights": {
            "sharpe": 0.40,
            "drawdown": -0.20,
            "gap": -0.25,
            "risk_cap": 0.15
        },
        "rules": {
            "demote_overfit_gap_threshold": 0.5,
            "demote_overfit_penalty": 0.35,
            "boost_risk_discipline_threshold": 0.85,
            "boost_risk_discipline_bonus": 0.12,
            "min_trades_threshold": 8,
            "insufficient_trades_ceiling": 0.1,
            "elite_pct": 0.20
        }
    }

    res = {
        "weights": defaults["weights"].copy(),
        "rules": defaults["rules"].copy(),
        "validation_warnings": []
    }

    if not os.path.exists(filepath):
        msg = "Athena.md not found — using default weights and rules."
        logger.warning(msg)
        res["validation_warnings"].append(msg)
        return res

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_data = yaml.safe_load(parts[1])
                if isinstance(yaml_data, dict):
                    parsed_weights = yaml_data.get("weights")
                    parsed_rules = yaml_data.get("rules")

                    # Validate weights
                    if parsed_weights is None:
                        res["validation_warnings"].append("Missing 'weights' section in Athena.md frontmatter — using default weights.")
                    elif not isinstance(parsed_weights, dict):
                        res["validation_warnings"].append("'weights' section in Athena.md frontmatter must be a dictionary.")
                    else:
                        all_zero = True
                        for k in ["sharpe", "drawdown", "gap", "risk_cap"]:
                            if k not in parsed_weights:
                                res["validation_warnings"].append(f"Missing weight parameter '{k}' in Athena.md — using default weight.")
                            else:
                                val = parsed_weights[k]
                                if not isinstance(val, (int, float)):
                                    res["validation_warnings"].append(f"Weight parameter '{k}' in Athena.md must be numeric (got {type(val).__name__}).")
                                else:
                                    res["weights"][k] = float(val)
                                    if float(val) != 0.0:
                                        all_zero = False
                        if all_zero:
                            res["validation_warnings"].append("All weight values in Athena.md are zero. This will make scoring ineffective.")

                    # Validate rules
                    if parsed_rules is None:
                        res["validation_warnings"].append("Missing 'rules' section in Athena.md frontmatter — using default rules.")
                    elif not isinstance(parsed_rules, dict):
                        res["validation_warnings"].append("'rules' section in Athena.md frontmatter must be a dictionary.")
                    else:
                        for k in ["demote_overfit_gap_threshold", "demote_overfit_penalty",
                                  "boost_risk_discipline_threshold", "boost_risk_discipline_bonus",
                                  "min_trades_threshold", "insufficient_trades_ceiling", "elite_pct"]:
                            if k not in parsed_rules:
                                res["validation_warnings"].append(f"Missing rule parameter '{k}' in Athena.md — using default rule value.")
                            else:
                                val = parsed_rules[k]
                                if not isinstance(val, (int, float)):
                                    res["validation_warnings"].append(f"Rule parameter '{k}' in Athena.md must be numeric (got {type(val).__name__}).")
                                else:
                                    res["rules"][k] = float(val) if isinstance(val, float) else val

                    return res
                else:
                    res["validation_warnings"].append("Frontmatter block in Athena.md is not a valid YAML dictionary.")
            else:
                res["validation_warnings"].append("Athena.md frontmatter is missing closing '---' marker.")
        else:
            res["validation_warnings"].append("Athena.md frontmatter is missing opening '---' marker.")
    except Exception as e:
        msg = f"Failed to parse Athena.md frontmatter: {e} — using defaults."
        logger.error(msg)
        res["validation_warnings"].append(msg)

    return res


class SelectionPolicy(ABC):
    """
    Abstract Base Class for Strategy Selection policies.
    Determines ranking, survivability, and generates selection journals.
    """
    @abstractmethod
    def rank_and_select(
        self,
        session,
        db_gen,
        evaluated_population: List[tuple],
        broadcast_queue: Optional[Any] = None
    ) -> List[tuple]:
        """
        Ranks the population and returns a list of (StrategyConfig, float_score) sorted descending by score.
        """
        pass


class TournamentSelectionPolicy(SelectionPolicy):
    """
    Default Selection Policy. Ranks strategies strictly on their raw walk-forward validation Sharpe ratio.
    """
    def rank_and_select(
        self,
        session,
        db_gen,
        evaluated_population: List[tuple],
        broadcast_queue: Optional[Any] = None
    ) -> List[tuple]:
        # Return population sorted by validation Sharpe ratio descending
        # evaluated_population is a list of (StrategyConfig, agg_sharpe)
        sorted_pop = sorted(evaluated_population, key=lambda x: x[1], reverse=True)
        return sorted_pop


class AthenaSelectionPolicy(SelectionPolicy):
    """
    Athena Lead Selection Agent Policy.
    Calculates a risk-and-overfit-adjusted score from Athena.md weights/rules,
    ranks the population, and narrates a natural-language journal entry.
    """
    def __init__(self):
        self.elite_pct = 0.20

    def rank_and_select(
        self,
        session,
        db_gen,
        evaluated_population: List[tuple],
        broadcast_queue: Optional[Any] = None
    ) -> List[tuple]:
        config = parse_athena_md()
        weights = config["weights"]
        rules = config["rules"]

        # Dynamically set elite_pct so that the loop can retrieve it
        self.elite_pct = rules.get("elite_pct", 0.20)

        # 1. Fetch DBStrategy records for this generation
        db_strats = session.query(DBStrategy).filter_by(generation_id=db_gen.id).all()
        db_map = {s.id: s for s in db_strats}

        # 2. Extract raw metrics and prepare maps for population min-max normalization
        raw_sharpes = []
        raw_drawdowns = []
        raw_gaps = []
        raw_risk_caps = []

        for strat, _ in evaluated_population:
            db_strat = db_map.get(strat.id)
            if db_strat:
                raw_sharpes.append(db_strat.agg_validation_sharpe)
                raw_drawdowns.append(db_strat.agg_validation_drawdown)
                raw_gaps.append(db_strat.agg_train_validation_gap)
                raw_risk_caps.append(db_strat.risk_cap_applied_pct)

        def normalize_series(values: List[float]) -> dict:
            # Memoized by raw value (not index) — ties in a metric correctly
            # collapse to the same normalized score, this is intentional.
            if not values:
                return {}
            v_min = min(values)
            v_max = max(values)
            denom = v_max - v_min
            res_map = {}
            for v in values:
                if denom == 0.0:
                    res_map[v] = 0.5
                else:
                    res_map[v] = (v - v_min) / denom
            return res_map

        norm_sharpe_map = normalize_series(raw_sharpes)
        norm_drawdown_map = normalize_series(raw_drawdowns)
        norm_gap_map = normalize_series(raw_gaps)
        norm_risk_cap_map = normalize_series(raw_risk_caps)

        scored_population = []
        rule_adjustments_applied = []
        strat_details_for_prompt = []

        # 3. Compute Athena scores and log rule promotions/demotions
        for strat, raw_sharpe in evaluated_population:
            db_strat = db_map.get(strat.id)
            if not db_strat:
                # Fallback if DB record missing
                scored_population.append((strat, raw_sharpe))
                continue

            # Extract metrics from DBStrategy record
            sharpe = db_strat.agg_validation_sharpe
            drawdown = db_strat.agg_validation_drawdown
            gap = db_strat.agg_train_validation_gap
            risk_cap = db_strat.risk_cap_applied_pct
            trade_count = getattr(db_strat, "validation_trade_count", 0)

            # Get normalized values
            n_sharpe = norm_sharpe_map.get(sharpe, 0.5)
            n_drawdown = norm_drawdown_map.get(drawdown, 0.5)
            n_gap = norm_gap_map.get(gap, 0.5)
            n_risk_cap = norm_risk_cap_map.get(risk_cap, 0.5)

            # Base weighted score using normalized values (0-1 range)
            base_score = (
                weights.get("sharpe", 0.40) * n_sharpe +
                weights.get("drawdown", -0.20) * n_drawdown +
                weights.get("gap", -0.25) * n_gap +
                weights.get("risk_cap", 0.15) * n_risk_cap
            )

            athena_score = base_score

            # Overfit penalty check (on raw value)
            demote_gap_thresh = rules.get("demote_overfit_gap_threshold", 0.5)
            demote_penalty = rules.get("demote_overfit_penalty", 0.35)
            if gap > demote_gap_thresh:
                athena_score -= demote_penalty
                adj_msg = f"Demoted Strategy '{db_strat.name}' ({db_strat.id}) with a train/val gap penalty (-{demote_penalty}) for gap of {gap:.2f} > {demote_gap_thresh:.2f}."
                rule_adjustments_applied.append(adj_msg)

            # Risk discipline bonus check (on raw value)
            boost_risk_thresh = rules.get("boost_risk_discipline_threshold", 0.85)
            boost_bonus = rules.get("boost_risk_discipline_bonus", 0.12)
            if risk_cap > boost_risk_thresh:
                athena_score += boost_bonus
                adj_msg = f"Boosted Strategy '{db_strat.name}' ({db_strat.id}) with risk discipline bonus (+{boost_bonus}) for risk_cap_applied_pct of {risk_cap * 100:.0f}% > {boost_risk_thresh * 100:.0f}%."
                rule_adjustments_applied.append(adj_msg)

            # Minimum trade count safeguard (Item 6)
            min_trades = rules.get("min_trades_threshold", 8)
            trades_ceiling = rules.get("insufficient_trades_ceiling", 0.1)
            if trade_count < min_trades:
                athena_score = min(athena_score, trades_ceiling)
                adj_msg = f"Capped Strategy '{db_strat.name}' ({db_strat.id}) at {trades_ceiling} due to insufficient validation trade count of {trade_count} < {min_trades}."
                rule_adjustments_applied.append(adj_msg)

            scored_population.append((strat, athena_score))

            strat_details_for_prompt.append({
                "id": db_strat.id,
                "name": db_strat.name,
                "metrics": {
                    "val_sharpe": sharpe,
                    "val_drawdown": drawdown,
                    "train_val_gap": gap,
                    "risk_cap_applied_pct": risk_cap,
                    "validation_trade_count": trade_count
                },
                "base_score": base_score,
                "athena_score": athena_score
            })

        # 4. Sort strictly by Athena Score descending
        ranked_population = sorted(scored_population, key=lambda x: x[1], reverse=True)

        # 5. Generate selection journal
        journal_text = self._generate_journal_narrative(
            generation_number=db_gen.generation_number,
            weights=weights,
            rules=rules,
            strat_details=strat_details_for_prompt,
            rule_adjustments=rule_adjustments_applied
        )

        # Append validation warnings to the persistent banner format if they exist
        if config.get("validation_warnings"):
            warning_prefix = "!!!WARNINGS: " + " | ".join(config["validation_warnings"]) + "!!!\n\n"
            journal_text = warning_prefix + journal_text

        # Save narrative to the database
        print(f"\n[Athena Journal - Gen {db_gen.generation_number}]:\n{journal_text}\n")
        db_log = DBAthenaLog(
            generation_id=db_gen.id,
            entry_text=journal_text
        )
        session.add(db_log)
        session.commit()

        # Broadcast Athena selection journal entry via WebSockets
        if broadcast_queue:
            broadcast_queue.put({
                "run_id": db_gen.run_id,
                "generation": db_gen.generation_number,
                "status": "athena_journal",
                "entry_text": journal_text
            })

        return ranked_population

    def _generate_journal_narrative(
        self,
        generation_number: int,
        weights: dict,
        rules: dict,
        strat_details: List[dict],
        rule_adjustments: List[str]
    ) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY")

        population_summary = json.dumps(strat_details[:10], indent=2) # Narrative focuses on top strategies
        adjustments_summary = "\n".join(rule_adjustments) if rule_adjustments else "No special rules triggered."

        # Fetch custom model name configuration from run_config.yaml
        narration_model = "claude-haiku-4-5-20251001"
        try:
            with open("config/run_config.yaml", "r") as f:
                run_config = yaml.safe_load(f)
                narration_model = run_config.get("components", {}).get("athena_narration_model", "claude-haiku-4-5-20251001")
        except Exception:
            pass

        # If Anthropic API key is available, generate prose using Claude
        if api_key:
            try:
                client = anthropic.Anthropic(api_key=api_key)
                prompt = f"""
You are Athena, the lead selection agent of AthenaCell.
Your role is to write a highly professional, concise, plain-language journal entry (prose) narrating the key promotion and demotion decisions made for Generation {generation_number} of strategy evolution.

The decisions have already been made deterministically based on your scoring rules:
Weights: {json.dumps(weights)}
Rules: {json.dumps(rules)}

Here is the population performance and Athena scores (Top 10 candidates):
{population_summary}

Deterministic rule adjustments applied:
{adjustments_summary}

Please write a cohesive journal entry narrating these key decisions. Highlight cases where a strategy with a higher raw Sharpe was demoted due to overfit penalties (high train/val gap), or a strategy was boosted due to excellent risk discipline (high risk cap applied). Explicitly mention cases where a strategy was capped due to an insufficient sample of validation trades. Explain the selection rationale clearly in 2-3 paragraphs. Keep it professional, insightful, and focused on risk discipline and overfit prevention.
Do not use any markdown formatting like code blocks, lists, bold text markers, or headers in your response. Just write clean, cohesive paragraphs of prose.
"""
                message = client.messages.create(
                    model=narration_model,
                    max_tokens=2000,
                    temperature=0.3,
                    system="You are Athena. You write elegant, insightful paragraphs of selection logs with no markdown tags.",
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                journal_text = message.content[0].text.strip()
                if journal_text:
                    return journal_text
            except Exception as e:
                logger.warning(f"Claude API call for Athena Journal failed: {e}. Falling back to deterministic narrative.")

        # Fallback deterministic generator
        paragraphs = [
            f"Generation {generation_number} strategy evaluation complete. Evaluated {len(strat_details)} candidates using Athena's weighted scoring philosophy (Weights: Sharpe {weights.get('sharpe'):.2f}, Drawdown {weights.get('drawdown'):.2f}, Gap {weights.get('gap'):.2f}, Risk Cap {weights.get('risk_cap'):.2f})."
        ]

        if rule_adjustments:
            paragraphs.append("The following selection adjustments were made during ranking: " + " ".join(rule_adjustments))
        else:
            paragraphs.append("No special overfit or risk-discipline adjustment triggers were activated this generation. Candidate ranking proceeded strictly according to weighted scoring parameters.")

        if strat_details:
            # Sort local details by score to present best
            local_ranked = sorted(strat_details, key=lambda x: x["athena_score"], reverse=True)
            best = local_ranked[0]
            paragraphs.append(
                f"Strategy '{best['name']}' ({best['id']}) succeeded to rank 1st with an Athena score of {best['athena_score']:.4f} "
                f"(Raw Sharpe: {best['metrics']['val_sharpe']:.2f}, Max Drawdown: {best['metrics']['val_drawdown'] * 100:.1f}%, "
                f"Train/Val Gap: {best['metrics']['train_val_gap']:.2f}, Risk Cap: {best['metrics']['risk_cap_applied_pct'] * 100:.0f}%, "
                f"Validation Trade Count: {best['metrics']['validation_trade_count']})."
            )

        return "\n\n".join(paragraphs)


def get_selection_policy(name: str) -> SelectionPolicy:
    """
    Factory to retrieve the specified SelectionPolicy.
    """
    name = name.lower()
    if name == "athena":
        return AthenaSelectionPolicy()
    elif name == "tournament" or name == "sharpe" or not name:
        return TournamentSelectionPolicy()
    else:
        logger.warning(f"Unknown selection strategy: {name}. Defaulting to Tournament Selection.")
        return TournamentSelectionPolicy()
