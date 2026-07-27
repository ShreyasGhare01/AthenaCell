import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

Base = declarative_base()

class DBRun(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    status = Column(String, default="idle")  # "idle", "running", "completed", "failed"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Run configuration stored as JSON
    config = Column(JSON, nullable=False)

    # Relationships
    generations = relationship("DBGeneration", back_populates="run", cascade="all, delete-orphan")

class DBGeneration(Base):
    __tablename__ = "generations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    generation_number = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    run = relationship("DBRun", back_populates="generations")
    strategies = relationship("DBStrategy", back_populates="generation", cascade="all, delete-orphan")

class DBStrategy(Base):
    __tablename__ = "strategies"

    id = Column(String, primary_key=True) # UUID or standard identifier (e.g., 'gen_1_strategy_3')
    generation_id = Column(Integer, ForeignKey("generations.id"), nullable=False)
    name = Column(String, nullable=False)

    # Fully validated StrategyConfig serialized as JSON
    config_json = Column(JSON, nullable=False)

    # Lineage / Mutation Tracking
    parent_id = Column(String, nullable=True) # ID of parent strategy, if any
    mutation_type = Column(String, nullable=True) # e.g. "parameter_jitter", "rule_swap"
    mutation_reason = Column(String, nullable=True) # LLM text or description of the modification

    # Summary of aggregate Performance across validation folds
    agg_validation_sharpe = Column(Float, default=0.0)
    agg_validation_drawdown = Column(Float, default=0.0)
    agg_validation_win_rate = Column(Float, default=0.0)
    agg_train_validation_gap = Column(Float, default=0.0) # gap indicator
    risk_cap_applied = Column(Boolean, default=True)

    # Relationships
    generation = relationship("DBGeneration", back_populates="strategies")
    folds = relationship("DBStrategyFold", back_populates="strategy", cascade="all, delete-orphan")
    trades = relationship("DBSimulatedTrade", back_populates="strategy", cascade="all, delete-orphan")

class DBStrategyFold(Base):
    __tablename__ = "strategy_folds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(String, ForeignKey("strategies.id"), nullable=False)
    fold_index = Column(Integer, nullable=False)

    # Training vs Validation periods
    train_start = Column(DateTime, nullable=False)
    train_end = Column(DateTime, nullable=False)
    val_start = Column(DateTime, nullable=False)
    val_end = Column(DateTime, nullable=False)

    # Training Performance Metrics
    train_sharpe = Column(Float, default=0.0)
    train_drawdown = Column(Float, default=0.0)
    train_win_rate = Column(Float, default=0.0)

    # Validation Performance Metrics
    val_sharpe = Column(Float, default=0.0)
    val_drawdown = Column(Float, default=0.0)
    val_win_rate = Column(Float, default=0.0)

    # Equity curve logging as lists of points: [{"date": "YYYY-MM-DD", "equity": 10000.0}, ...]
    train_equity_curve = Column(JSON, default=list)
    val_equity_curve = Column(JSON, default=list)

    strategy = relationship("DBStrategy", back_populates="folds")

class DBSimulatedTrade(Base):
    __tablename__ = "simulated_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(String, ForeignKey("strategies.id"), nullable=False)
    fold_index = Column(Integer, nullable=False)

    ticker = Column(String, nullable=False)
    entry_date = Column(DateTime, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_date = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    size = Column(Float, nullable=False)
    profit_pct = Column(Float, nullable=True)
    exit_reason = Column(String, nullable=True) # "rule", "stop_loss", "take_profit", "end_of_period"

    strategy = relationship("DBStrategy", back_populates="trades")


# Database initializer
class StorageManager:
    def __init__(self, db_url: str = "sqlite:///data/athenacell.db"):
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def get_session(self):
        return self.SessionLocal()
