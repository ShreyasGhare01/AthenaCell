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
    returns standard, robust default parameters.
    """
    defaults = {
        "weights": {
            "sharpe": 0.5,
            "drawdown": -0.2,
            "gap": -0.1,
            "risk_cap": 0.2
        },
        "rules": {
            "demote_overfit_gap_threshold": 0.5,
            "demote_overfit_penalty": 0.3,
            "boost_risk_discipline_threshold": 0.8,
            "boost_risk_discipline_bonus": 0.1
        }
    }

    if not os.path.exists(filepath):
        logger.warning("Athena.md not found. Proceeding with default scoring policy.")
        return defaults

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_data = yaml.safe_load(parts[1])
                if isinstance(yaml_data, dict):
                    # Ensure both weights and rules exist in parsed data
                    res = {}
                    res["weights"] = yaml_data.get("weights", defaults["weights"])
                    res["rules"] = yaml_data.get("rules", defaults["rules"])
                    return res
    except Exception as e:
        logger.error(f"Failed to parse Athena.md frontmatter: {e}. Falling back to default scoring policy.")

    return defaults


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

        # 1. Fetch DBStrategy records for this generation
        db_strats = session.query(DBStrategy).filter_by(generation_id=db_gen.id).all()
        db_map = {s.id: s for s in db_strats}

        scored_population = []
        rule_adjustments_applied = []
        strat_details_for_prompt = []

        # 2. Compute Athena scores and log rule promotions/demotions
        for strat, raw_sharpe in evaluated_population:
            db_strat = db_map.get(strat.id)
            if not db_strat:
                # Fallback if DB record missing (should not happen in normal flow)
                scored_population.append((strat, raw_sharpe))
                continue

            # Extract metrics from DBStrategy record
            sharpe = db_strat.agg_validation_sharpe
            drawdown = db_strat.agg_validation_drawdown
            gap = db_strat.agg_train_validation_gap
            risk_cap = db_strat.risk_cap_applied_pct

            # Base weighted score
            base_score = (
                weights.get("sharpe", 0.5) * sharpe +
                weights.get("drawdown", -0.2) * drawdown +
                weights.get("gap", -0.1) * gap +
                weights.get("risk_cap", 0.2) * risk_cap
            )

            athena_score = base_score

            # Overfit penalty check
            demote_gap_thresh = rules.get("demote_overfit_gap_threshold", 0.5)
            demote_penalty = rules.get("demote_overfit_penalty", 0.3)
            if gap > demote_gap_thresh:
                athena_score -= demote_penalty
                adj_msg = f"Demoted Strategy '{db_strat.name}' ({db_strat.id}) with a train/val gap penalty (-{demote_penalty}) for gap of {gap:.2f} > {demote_gap_thresh:.2f}."
                rule_adjustments_applied.append(adj_msg)

            # Risk discipline bonus check
            boost_risk_thresh = rules.get("boost_risk_discipline_threshold", 0.8)
            boost_bonus = rules.get("boost_risk_discipline_bonus", 0.1)
            if risk_cap > boost_risk_thresh:
                athena_score += boost_bonus
                adj_msg = f"Boosted Strategy '{db_strat.name}' ({db_strat.id}) with risk discipline bonus (+{boost_bonus}) for risk_cap_applied_pct of {risk_cap * 100:.0f}% > {boost_risk_thresh * 100:.0f}%."
                rule_adjustments_applied.append(adj_msg)

            scored_population.append((strat, athena_score))

            strat_details_for_prompt.append({
                "id": db_strat.id,
                "name": db_strat.name,
                "metrics": {
                    "val_sharpe": sharpe,
                    "val_drawdown": drawdown,
                    "train_val_gap": gap,
                    "risk_cap_applied_pct": risk_cap
                },
                "base_score": base_score,
                "athena_score": athena_score
            })

        # 3. Sort strictly by Athena Score descending
        ranked_population = sorted(scored_population, key=lambda x: x[1], reverse=True)

        # 4. Generate selection journal
        journal_text = self._generate_journal_narrative(
            generation_number=db_gen.generation_number,
            weights=weights,
            rules=rules,
            strat_details=strat_details_for_prompt,
            rule_adjustments=rule_adjustments_applied
        )

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

Please write a cohesive journal entry narrating these key decisions. Highlight cases where a strategy with a higher raw Sharpe was demoted due to overfit penalties (high train/val gap), or a strategy was boosted due to excellent risk discipline (high risk cap applied). Explain the selection rationale clearly in 2-3 paragraphs. Keep it professional, insightful, and focused on risk discipline and overfit prevention.
Do not use any markdown formatting like code blocks, lists, bold text markers, or headers in your response. Just write clean, cohesive paragraphs of prose.
"""
                message = client.messages.create(
                    model="claude-3-haiku-20240307",
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
            f"Generation {generation_number} strategy evaluation complete. Evaluated {len(strat_details)} candidates using Athena's weighted scoring philosophy (Weights: Sharpe {weights.get('sharpe')}, Drawdown {weights.get('drawdown')}, Gap {weights.get('gap')}, Risk Cap {weights.get('risk_cap')})."
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
                f"Train/Val Gap: {best['metrics']['train_val_gap']:.2f}, Risk Cap: {best['metrics']['risk_cap_applied_pct'] * 100:.0f}%)."
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
