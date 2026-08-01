import os
import random
import yaml
import uuid
import queue
import pandas as pd
from typing import List, Dict, Any, Callable, Optional
from storage.db import StorageManager, DBRun, DBGeneration, DBStrategy, DBStrategyFold, DBSimulatedTrade
from data.loader import DataLoader
from engine.walk_forward import generate_rolling_folds
from engine.backtester import Backtester
from strategies.schema import StrategyConfig
from evolution.mutation.operators import RandomStrategyGenerator, EvolutionRegistry
from evolution.athena import get_selection_policy

class EvolutionLoop:
    """
    Orchestrates the entire walk-forward strategy evolution sequence.
    Scores, ranks, selects, mutates, and persists results.
    """
    def __init__(self, run_config_path: str = "config/run_config.yaml", db_url: str = "sqlite:///data/athenacell.db"):
        self.run_config_path = run_config_path
        self.db_url = db_url

        # Load run config
        with open(run_config_path, "r") as f:
            self.config = yaml.safe_load(f)

        self.storage = StorageManager(db_url=self.db_url)
        self.data_loader = DataLoader()

    def run_evolution(self, run_id: Optional[int] = None, broadcast_queue: Optional[queue.Queue] = None):
        """
        Executes the evolution run step-by-step and persists details synchronously.
        """
        session = self.storage.get_session()

        # 1. Create or retrieve DBRun record
        if run_id is not None:
            db_run = session.query(DBRun).filter_by(id=run_id).first()
            if db_run:
                db_run.status = "running"
                session.commit()
                # Ensure we use the config from the DBRun if resuming, or fallback to file config
                run_config = db_run.config if db_run.config else self.config
            else:
                run_config = self.config
        else:
            db_run = DBRun(
                name=self.config["run"]["name"],
                status="running",
                config=self.config
            )
            session.add(db_run)
            session.commit()
            session.refresh(db_run)
            run_id = db_run.id
            run_config = self.config

        try:
            # 2. Set up components and data source
            pop_size = run_config["run"]["population_size"]
            generations_count = run_config["run"]["generations"]
            universe = run_config["run"]["universe"]
            start_date = run_config["run"]["start_date"]
            end_date = run_config["run"]["end_date"]

            # Setup rolling folds
            wf_params = run_config["walk_forward"]
            folds = generate_rolling_folds(
                start_date=start_date,
                end_date=end_date,
                train_months=wf_params["train_months"],
                validate_months=wf_params["validate_months"],
                step_months=wf_params["step_months"]
            )

            if not folds:
                raise ValueError("No rolling folds generated with current date/month configs.")

            source_name = run_config["components"]["data_source"]
            validate_cross_source = run_config["components"].get("validate_cross_source", False)
            validation_threshold = run_config["components"].get("validation_threshold", 0.01)
            validation_sample_rate = run_config["components"].get("validation_sample_rate", 0.1)

            data_source = self.data_loader.get_source(
                source_name,
                validate_cross_source=validate_cross_source,
                validation_threshold=validation_threshold,
                validation_sample_rate=validation_sample_rate
            )

            # Set context for FallbackDataSource to write data quality warnings
            if hasattr(data_source, "set_run_context"):
                data_source.set_run_context(run_id=run_id, db_url=self.db_url)

            # Auto-warm up cash/parquet caches for all universe tickers
            for ticker in universe:
                try:
                    data_source.fetch_data(ticker, start_date, end_date)
                except Exception as e:
                    print(f"Pre-caching error for {ticker}: {e}")

            backtester = Backtester(data_source)

            # Check if there's any completed generation in this DBRun to resume from
            completed_gens = session.query(DBGeneration).filter_by(run_id=run_id).order_by(DBGeneration.generation_number.desc()).all()

            # Find the last generation that has saved strategies
            starting_gen_idx = 0
            population: List[StrategyConfig] = []
            parent_info = {} # strategy_id -> (parent_id, mutation_type, reason)

            last_completed_gen = None
            for gen in completed_gens:
                strats = session.query(DBStrategy).filter_by(generation_id=gen.id).all()
                if len(strats) >= pop_size:
                    last_completed_gen = gen
                    break

            if last_completed_gen is not None:
                # Resume from the last completed generation
                print(f"Resuming run_id {run_id} from completed generation {last_completed_gen.generation_number}")
                starting_gen_idx = last_completed_gen.generation_number + 1

                # Load population from DB
                db_strats = session.query(DBStrategy).filter_by(generation_id=last_completed_gen.id).all()
                for s in db_strats:
                    population.append(StrategyConfig.model_validate(s.config_json))

                # Check if we have completed all generations
                if starting_gen_idx >= generations_count:
                    print("All generations already completed. Finishing run.")
                    db_run.status = "completed"
                    session.commit()
                    if broadcast_queue:
                        broadcast_queue.put({
                            "run_id": run_id,
                            "status": "completed"
                        })
                    return
            else:
                # 3. Create generation 0 fresh
                seed_gen = RandomStrategyGenerator(universe=universe)
                for _ in range(pop_size):
                    population.append(seed_gen.generate())

            for gen_idx in range(starting_gen_idx, generations_count):
                print(f"\n--- Generation {gen_idx} Evolution ---")

                # Create DBGeneration (or reuse if existed somehow)
                db_gen = session.query(DBGeneration).filter_by(run_id=run_id, generation_number=gen_idx).first()
                if not db_gen:
                    db_gen = DBGeneration(run_id=run_id, generation_number=gen_idx)
                    session.add(db_gen)
                    session.commit()
                    session.refresh(db_gen)

                # Evaluate strategy candidates against all rolling folds
                evaluated_population = []

                for strat in population:
                    # Check if strategy is already saved for this generation to avoid re-evaluating
                    existing_strat = session.query(DBStrategy).filter_by(id=strat.id, generation_id=db_gen.id).first()
                    if existing_strat:
                        # Strategy already evaluated and saved in this run/gen (e.g. from a partial previous run)
                        evaluated_population.append((strat, existing_strat.agg_validation_sharpe))
                        continue

                    strat_folds_metrics = []
                    all_trades = []

                    # Store variables for aggregate scoring
                    val_sharpes = []
                    val_drawdowns = []
                    val_win_rates = []
                    train_sharpes = []

                    global_total_entries = 0
                    global_risk_capped_entries = 0

                    # Evaluate has_stop_loss property
                    has_stop_loss = (strat.risk_management.stop_loss_pct is not None) or (strat.risk_management.atr_stop_multiplier is not None)

                    for fold_idx, fold in enumerate(folds):
                        # Backtest on Training fold
                        train_res = backtester.run(
                            strat,
                            start_date=fold["train_start"].strftime("%Y-%m-%d"),
                            end_date=fold["train_end"].strftime("%Y-%m-%d"),
                            initial_cash=run_config["risk"]["initial_cash"]
                        )

                        # Backtest on Validation fold
                        val_res = backtester.run(
                            strat,
                            start_date=fold["val_start"].strftime("%Y-%m-%d"),
                            end_date=fold["val_end"].strftime("%Y-%m-%d"),
                            initial_cash=run_config["risk"]["initial_cash"]
                        )

                        val_sharpes.append(val_res["sharpe"])
                        val_drawdowns.append(val_res["max_drawdown"])
                        val_win_rates.append(val_res["win_rate"])
                        train_sharpes.append(train_res["sharpe"])

                        global_total_entries += val_res.get("total_entries", 0)
                        global_risk_capped_entries += val_res.get("risk_capped_entries", 0)

                        # Store fold details
                        strat_folds_metrics.append({
                            "fold_index": fold_idx,
                            "train_start": fold["train_start"],
                            "train_end": fold["train_end"],
                            "val_start": fold["val_start"],
                            "val_end": fold["val_end"],
                            "train_sharpe": train_res["sharpe"],
                            "train_drawdown": train_res["max_drawdown"],
                            "train_win_rate": train_res["win_rate"],
                            "val_sharpe": val_res["sharpe"],
                            "val_drawdown": val_res["max_drawdown"],
                            "val_win_rate": val_res["win_rate"],
                            "train_equity_curve": train_res["equity_curve"],
                            "val_equity_curve": val_res["equity_curve"]
                        })

                        # Store simulated trades
                        for t in val_res["trades"]:
                            all_trades.append({
                                "fold_index": fold_idx,
                                "ticker": t["ticker"],
                                "entry_date": pd.to_datetime(t["entry_date"]),
                                "entry_price": t["entry_price"],
                                "exit_date": pd.to_datetime(t["exit_date"]) if t["exit_date"] else None,
                                "exit_price": t["exit_price"],
                                "size": t["size"],
                                "profit_pct": t["profit_pct"],
                                "exit_reason": t["exit_reason"]
                            })

                    # Calculate aggregate scores (validation period aggregated across folds)
                    agg_sharpe = sum(val_sharpes) / len(val_sharpes) if val_sharpes else 0.0
                    agg_drawdown = sum(val_drawdowns) / len(val_drawdowns) if val_drawdowns else 0.0
                    agg_win_rate = sum(val_win_rates) / len(val_win_rates) if val_win_rates else 0.0

                    # Gap indicator: absolute difference between average train and validate Sharpe ratio
                    avg_train_sharpe = sum(train_sharpes) / len(train_sharpes) if train_sharpes else 0.0
                    agg_gap = max(0.0, avg_train_sharpe - agg_sharpe)

                    # Calculate global risk cap applied ratio across folds
                    global_risk_cap_pct = float(global_risk_capped_entries / global_total_entries) if global_total_entries > 0 else 0.0

                    # Persist Strategy Genome
                    p_id, m_type, m_reason = parent_info.get(strat.id, (None, None, None))
                    db_strat = DBStrategy(
                        id=strat.id,
                        generation_id=db_gen.id,
                        name=strat.name,
                        config_json=strat.model_dump(),
                        parent_id=p_id,
                        mutation_type=m_type,
                        mutation_reason=m_reason,
                        agg_validation_sharpe=agg_sharpe,
                        agg_validation_drawdown=agg_drawdown,
                        agg_validation_win_rate=agg_win_rate,
                        agg_train_validation_gap=agg_gap,
                        risk_cap_applied_pct=global_risk_cap_pct,
                        validation_trade_count=global_total_entries
                    )
                    session.add(db_strat)
                    session.flush() # Flushes so strategy table contains records before children are referenced

                    # Persist fold details
                    for f in strat_folds_metrics:
                        db_fold = DBStrategyFold(
                            strategy_id=strat.id,
                            fold_index=f["fold_index"],
                            train_start=f["train_start"],
                            train_end=f["train_end"],
                            val_start=f["val_start"],
                            val_end=f["val_end"],
                            train_sharpe=f["train_sharpe"],
                            train_drawdown=f["train_drawdown"],
                            train_win_rate=f["train_win_rate"],
                            val_sharpe=f["val_sharpe"],
                            val_drawdown=f["val_drawdown"],
                            val_win_rate=f["val_win_rate"],
                            train_equity_curve=f["train_equity_curve"],
                            val_equity_curve=f["val_equity_curve"]
                        )
                        session.add(db_fold)

                    # Persist simulated trades
                    for t in all_trades:
                        db_trade = DBSimulatedTrade(
                            strategy_id=strat.id,
                            fold_index=t["fold_index"],
                            ticker=t["ticker"],
                            entry_date=t["entry_date"],
                            entry_price=t["entry_price"],
                            exit_date=t["exit_date"],
                            exit_price=t["exit_price"],
                            size=t["size"],
                            profit_pct=t["profit_pct"],
                            exit_reason=t["exit_reason"]
                        )
                        session.add(db_trade)

                    evaluated_population.append((strat, agg_sharpe))

                session.commit()

                # Pluggable Selection Policy ranking
                selection_strategy = run_config["components"].get("selection_strategy", "tournament")
                selection_policy = get_selection_policy(selection_strategy)

                # rank_and_select will rank, log, write journal DB records, and return ranked (StrategyConfig, score)
                evaluated_population = selection_policy.rank_and_select(
                    session=session,
                    db_gen=db_gen,
                    evaluated_population=evaluated_population,
                    broadcast_queue=broadcast_queue
                )

                # Push progress update via WebSocket callback (queue)
                if broadcast_queue:
                    broadcast_queue.put({
                        "run_id": run_id,
                        "generation": gen_idx,
                        "total_generations": generations_count,
                        "status": "evolving",
                        "best_sharpe": evaluated_population[0][1],
                        "avg_sharpe": sum(x[1] for x in evaluated_population) / len(evaluated_population)
                    })

                # 4. Selection & Reproduction to construct next generation
                if gen_idx < generations_count - 1:
                    next_generation: List[StrategyConfig] = []
                    parent_info = {} # clear out for new gen

                    # Keep Elite (using dynamic elite_pct from selection policy if available, defaulting to 0.2)
                    elite_pct = getattr(selection_policy, "elite_pct", 0.2)
                    elite_count = max(1, int(pop_size * elite_pct))
                    elites = [x[0] for x in evaluated_population[:elite_count]]

                    # Duplicate elites with a clean new UUID ID (Moderate Fix #9)
                    for elite in elites:
                        elite_dict = elite.model_dump()
                        old_id = elite_dict["id"]
                        new_id = uuid.uuid4().hex[:12]
                        elite_dict["id"] = new_id
                        cloned_elite = StrategyConfig.model_validate(elite_dict)
                        next_generation.append(cloned_elite)
                        parent_info[new_id] = (old_id, "survival", "Survived elite ranking from previous generation.")

                    # Fill the remaining population size using selection and mutations
                    mutators_list = run_config["components"]["mutators"]

                    while len(next_generation) < pop_size:
                        # Simple Tournament selection between two random strategies
                        p1 = random.choice(evaluated_population[:int(pop_size * 0.5)])[0]

                        if random.random() < 0.4 and len(elites) > 1:
                            # 40% Crossover with an elite
                            p2 = random.choice(elites)
                            cross_op = EvolutionRegistry.get_crossover("uniform")
                            reasons = []
                            child = cross_op.crossover(p1, p2, reasons)
                            parent_info[child.id] = (p1.id, "crossover", ", ".join(reasons))
                            next_generation.append(child)
                        else:
                            # 60% Mutate
                            mutator_name = random.choice(mutators_list)
                            mut_op = EvolutionRegistry.get_mutator(mutator_name)
                            reasons = []
                            child = mut_op.mutate(p1, reasons)
                            parent_info[child.id] = (p1.id, mutator_name, ", ".join(reasons))
                            next_generation.append(child)

                    population = next_generation

            # Set Run complete
            db_run = session.query(DBRun).filter_by(id=run_id).first()
            if db_run:
                db_run.status = "completed"
                session.commit()

            if broadcast_queue:
                broadcast_queue.put({
                    "run_id": run_id,
                    "status": "completed"
                })

        except Exception as e:
            db_run = session.query(DBRun).filter_by(id=run_id).first()
            if db_run:
                db_run.status = "failed"
                session.commit()
            if broadcast_queue:
                broadcast_queue.put({
                    "run_id": run_id,
                    "status": "failed",
                    "error": str(e)
                })
            raise e
        finally:
            session.close()
