# AthenaCell

AthenaCell is a local-first stock strategy research sandbox that evolves populations of trading strategies through simulated paper trading and walk-forward validation folds. It utilizes dynamic abstract registries for seamless integration of custom technical indicators, mutation operations, and multi-sourced market feeds.

## Key System Features
- **Strict Simulated Paper Trading Only:** 100% paper simulation. No live broker integrations, credentials, or actual capital usage.
- **Walk-Forward Validation folds:** Protects against curve-fitting by executing multi-fold sliding windows configured dynamically.
- **Modular Registries:** Pluggable abstract boundaries for all `DataSource`, `ScoringMetric`, `MutationOperator`, and `CrossoverOperator` instances.
- **LLM Research Extractor:** Intelligently translates paper texts or complex PDF layout schemas (using `pdfplumber`) into structured JSON strategy conditions via Anthropic's Claude. Includes robust offline mock system fallback capabilities.
- **SQLite Database Tracking:** Persists lineage logs, daily performance indicators, and trade statistics automatically.
- **High-Performance Parquet Caching:** Ensures immediate responses and eliminates yfinance rate-limiting.

---

## Technical Stack
- **Backend:** FastAPI (Python 3.11+)
- **ORM / Storage:** SQLAlchemy & SQLite (Multi-table relations)
- **Data Caching:** Pandas & PyArrow (Parquet)
- **Frontend UI:** Lightweight Vanilla JS, HTML, CSS (Gold/Charcoal theme) with local Chart.js

---

## 💻 VS Code Setup & Developer Debugging Guide

AthenaCell provides optimized integration files under the `.vscode/` folder for immediate setup:

1. **Recommended Extensions (`.vscode/extensions.json`):**
   - **Python:** Standard syntax highlighting, linter, formatting.
   - **Pylance:** Powerful typesafe refactoring and IntelliSense predictions.
   - **Jupyter:** Easily draft or prototype technical indicators in notebooks.

2. **Run Config debug configurations (`.vscode/launch.json`):**
   - **AthenaCell: CLI Main Run:** Instantly triggers an offline walk-forward evolution run from the terminal using the settings configured inside `config/run_config.yaml`.
   - **AthenaCell: Dashboard Server:** Launches the FastAPI backend application on `http://127.0.0.1:8000` to monitor active evolution, browse generation leaderboards, or upload PDF files.
   - **AthenaCell: Run Tests:** Runs the full unit testing coverage suites via Pytest.

---

## 🚀 Step-by-Step Run Instructions

1. **Set up virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Trigger an Evolution Run via CLI:**
   ```bash
   python3 main.py --config config/run_config.yaml
   ```

3. **Start the Web Dashboard Server:**
   ```bash
   python3 main.py --serve
   ```
   Now visit `http://127.0.0.1:8000` inside your browser to access the control panels and leaderboards.

4. **Verify the codebase with automated tests:**
   ```bash
   PYTHONPATH=. pytest -v
   ```

---

## 💾 Database, Caching & Backups

AthenaCell saves historical research metadata, lineage trees, and simulation results locally:
- **SQLite Database:** Saved at `data/athenacell.db`.
- **Market Data Cache:** Saved as Parquet files at `data/cache/`.

Both paths are listed in `.gitignore` to prevent committing raw data or localized results. Copying these files/directories elsewhere is a fully valid manual backup option.

### Automated Backups & Restoration

You can use the built-in CLI backup and restore commands to safely copy your workspace:

1. **Back up your database:**
   ```bash
   python main.py --backup ~/path/to/backup_dir
   ```
   *To optionally back up the Parquet market data cache directory alongside the DB, include the `--include-cache` flag:*
   ```bash
   python main.py --backup ~/path/to/backup_dir --include-cache
   ```

2. **Restore your database:**
   ```bash
   python main.py --restore ~/path/to/backup_dir
   ```
   *(Include `--include-cache` if you also wish to restore cached parquet files from that backup).*

---

## 📈 Redundant Data Sources & Fallback Mechanism

AthenaCell features a robust multi-source fallback mechanism to ensure stock EOD data is always successfully loaded without relying on a single provider.

### Configured Sources
- **YFinanceSource (`yfinance`)**: The default primary EOD provider (loads EOD data and caches as Parquet locally).
- **StooqSource (`stooq`)**: Fallback provider using Stooq's free CSV historical API. Automatically appends the `.US` suffix to US equity tickers and handles anti-scraping checks.

### Fallback Priority Setup
Inside `config/run_config.yaml`, you can configure the data source as an ordered priority list:
```yaml
components:
  data_source: ["yfinance", "stooq"]
```
When configured with a list, `FallbackDataSource` sequentially attempts to load each ticker from the sources in the specified order. If a source fails due to empty returns or network timeout, the fallback logic logs the warning and automatically transitions to the next provider.

### Cross-Source Validation
When multiple sources are enabled, you can optionally enable lightweight closing price validation:
```yaml
components:
  validate_cross_source: true
  validation_threshold: 0.01 # 1% divergence trigger
```
If enabled, when a ticker is fetched from the primary source, the last ~30 days are fetched from the secondary source as well. If their EOD closing prices diverge by more than the threshold, a clear warning log is printed and logged, signaling potential adjustments differences.

---

## 🦉 Athena Selection Policy & Lead Selection Agent

Athena is a deterministic, risk-and-overfit-aware Lead Selection Agent guided by a markdown philosophy file (`Athena.md`).

### Athena Scoring Philosophy (`Athena.md`)
- **Weights**: Configures relative scoring weights for validation Sharpe ratio, validation max drawdown, train-vs-validation Sharpe gap, and risk cap applied percentage.
- **Rules**: Implements deterministic promotions/demotions beyond raw score, e.g.:
  - **Overfit Penalty**: Deducts points if the train-validation gap is too high.
  - **Risk Discipline Bonus**: Adds points if a high ratio of trades utilized active risk caps.

To activate Athena's selection policy, set the selection strategy inside `config/run_config.yaml`:
```yaml
components:
  selection_strategy: "athena"
```

### Athena Selection Journals
Upon completing each generation's scoring, Athena writes a plain-language journal entry detailing her promotional and demotional rationale to the database. These are generated via Claude (Anthropic API) when online, and fall back to a rich, deterministic templated narrative when offline.

Journal entries appear live on the dashboard within the dedicated **Athena Selection Journal** panel!
