# AthenaCell Architecture

## Core Design Principle: Modularity & Interface-Registry Pattern

AthenaCell is designed as a highly modular, pluggable, and configurable framework. To maintain decoupling between core components (engine, evolution, storage) and specific implementations, every major capability is defined as an interface (Abstract Base Class or Protocol) with a corresponding implementation registered in a unified registry system.

Adding a new technical indicator, mutation operator, scoring metric, selection strategy, or data source is as simple as creating a subclass and decorating or registering it, with no modification required to the core execution engine.

### System Components Overview

1. **DataSource Interface (`data/sources/`)**
   - Defines methods to fetch historical market data.
   - Core Interface: `DataSource` (`fetch_data`)
   - Concrete implementations: `YFinanceSource` (caches raw data locally as Parquet under `data/cache/` to ensure performance and avoid rate-limiting), later `AlpacaPaperSource`.

2. **Strategy Config & Rules (`strategies/`)**
   - Strategies in AthenaCell are structured data objects (not executable python files).
   - Validated against a strict schema utilizing `Pydantic` and JSON schemas (`strategies/schema.py`).
   - Supports nested conditional statements (`AND`, `OR`, `NOT`) mapping to indicator-based rule objects.

3. **Walk-Forward engine & Backtester (`engine/`)**
   - Evaluates strategies across rolling validation folds to catch overfitted or curve-fitted strategies.
   - Performance metrics evaluated per fold and logged separately in the database.
   - Core Interface: `ScoringMetric` (e.g. `SharpeRatio`, `MaxDrawdown`, `WinRate`, `SortinoRatio`).

4. **Evolution & Genome Management (`evolution/`)**
   - Pluggable `MutationOperator`, `CrossoverOperator`, and `SelectionStrategy`.
   - Performs parent-child lineage tracking and records mutation history/reasoning directly to SQLite.

5. **Storage / Registry (`storage/`)**
   - SQLite backed via SQLModel/SQLAlchemy for easy migrations and structural updates.
   - Stores all run meta-data, generation statistics, individual genomes, and daily paper-trading logs.

6. **Research Extraction (`research/`)**
   - Interfacing with Anthropic Claude and using `pdfplumber` for PDF-to-schema extraction. Caches extracted papers locally.

---

## Unified Registry Design

A central registry (located in `strategies/schema.py` or a core registry module) houses all pluggable components. Components are looked up by a unique string ID corresponding to the identifier listed in `run_config.yaml`.

Example registration pattern:
```python
# Registration Decorator
class Registry:
    _sources = {}
    _metrics = {}
    _mutators = {}

    @classmethod
    def register_source(cls, name: str):
        def decorator(subclass):
            cls._sources[name] = subclass
            return subclass
        return decorator
```

Configurations are dynamic and resolved at runtime based on `config/run_config.yaml`.
