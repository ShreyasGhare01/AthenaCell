import os
import json
import uuid
import pdfplumber
import anthropic
from typing import Dict, Any, Optional
from strategies.schema import StrategyConfig

class ResearchExtractor:
    """
    Translates research paper text or PDF tables/layouts into structured strategy configurations.
    Uses Anthropic's Claude API with a robust mock fallback for offline environments and live testing.
    """
    def __init__(self, seed_library_dir: str = "research/seed_library"):
        self.seed_library_dir = seed_library_dir
        os.makedirs(self.seed_library_dir, exist_ok=True)
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Uses pdfplumber to extract all text elements cleanly, maintaining layout structures."""
        text_content = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_content.append(text)
        return "\n".join(text_content)

    def extract_strategy_from_text(self, text: str) -> StrategyConfig:
        """
        Interfaces with Claude or falls back to a deterministic structured mock strategy
        if ANTHROPIC_API_KEY is missing or fails.
        """
        # Save source paper text hash/cache
        paper_id = f"paper_{uuid.uuid5(uuid.NAMESPACE_DNS, text[:200]).hex[:8]}"
        cache_path = os.path.join(self.seed_library_dir, f"{paper_id}.json")

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                data = json.load(f)
            return StrategyConfig.model_validate(data)

        if not self.api_key:
            # Fallback Mock strategy representing classic trend following / mean reversion paper
            print("ANTHROPIC_API_KEY not found. Falling back to structured mock seed strategy.")
            mock_strategy = {
                "id": f"seed_{paper_id}",
                "name": f"Paper Seed {paper_id} (Mock SMA/RSI Trend)",
                "universe": ["AAPL", "MSFT", "GOOGL"],
                "timeframe": "1d",
                "entry_rules": {
                    "type": "and",
                    "rules": [
                        {
                            "type": "condition",
                            "indicator_a": {"name": "PRICE_CLOSE"},
                            "operator": ">",
                            "indicator_b": {"name": "SMA", "period": 50}
                        },
                        {
                            "type": "condition",
                            "indicator_a": {"name": "RSI", "period": 14},
                            "operator": "<",
                            "indicator_b": 40.0
                        }
                    ]
                },
                "exit_rules": {
                    "type": "condition",
                    "indicator_a": {"name": "PRICE_CLOSE"},
                    "operator": "<",
                    "indicator_b": {"name": "SMA", "period": 50}
                },
                "position_sizing": {
                    "type": "fixed_pct",
                    "value": 0.15
                },
                "risk_management": {
                    "stop_loss_pct": 0.04,
                    "take_profit_pct": 0.12
                },
                "max_concurrent_positions": 4,
                "risk_per_trade_cap_pct": 0.02
            }
            validated = StrategyConfig.model_validate(mock_strategy)

            # Cache it
            with open(cache_path, "w") as f:
                json.dump(mock_strategy, f, indent=2)

            return validated

        # Live Claude API Request
        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            prompt = f"""
You are an expert quantitative research analyst. You are reading a stock-trading strategy research paper.
Your task is to parse the rules and parameters mentioned in the text and structure them strictly into the requested JSON schema.

Paper Content:
---
{text[:8000]}
---

Please output a JSON object adhering exactly to the following properties:
- id: a short string identifier
- name: descriptive name of the strategy
- universe: array of strings of tickers (e.g., ["AAPL", "MSFT"])
- timeframe: "1d" or "1h"
- entry_rules: condition or nested logical rule group matching the schema structure. Supported indicator names are: "SMA", "EMA", "RSI", "MACD_LINE", "BB_UPPER", "BB_LOWER", "ATR", "PRICE_CLOSE", "PRICE_OPEN", "PRICE_HIGH", "PRICE_LOW", "VOLUME", "N_DAY_HIGH", "N_DAY_LOW".
- exit_rules: condition or nested logical rule group.
- position_sizing: dict with "type" ("fixed_pct") and "value" (float)
- risk_management: dict with keys like "stop_loss_pct" (float), "take_profit_pct" (float), and "atr_stop_multiplier" (float)
- max_concurrent_positions: integer
- risk_per_trade_cap_pct: float

Return ONLY the raw, valid JSON block. Do not include any conversational markdown wrapper outside of the JSON block.
"""
            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=4000,
                temperature=0.0,
                system="You are a system that returns purely structured JSON strategy configuration formats.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            content_text = message.content[0].text.strip()
            # Clean up potential markdown wrappers
            if content_text.startswith("```json"):
                content_text = content_text[7:]
            if content_text.endswith("```"):
                content_text = content_text[:-3]
            content_text = content_text.strip()

            data = json.loads(content_text)

            # Re-generate clean structure with custom paper id
            data["id"] = f"seed_{paper_id}"
            validated = StrategyConfig.model_validate(data)

            # Cache it
            with open(cache_path, "w") as f:
                json.dump(data, f, indent=2)

            return validated

        except Exception as e:
            print(f"Claude API Extraction failed: {e}. Falling back to mock strategy.")
            # Fallback mock strategy cache
            mock_strategy = {
                "id": f"seed_{paper_id}",
                "name": f"Paper Seed {paper_id} (API Error Fallback)",
                "universe": ["AAPL", "MSFT", "GOOGL"],
                "timeframe": "1d",
                "entry_rules": {
                    "type": "condition",
                    "indicator_a": {"name": "RSI", "period": 14},
                    "operator": "<",
                    "indicator_b": 30.0
                },
                "exit_rules": {
                    "type": "condition",
                    "indicator_a": {"name": "RSI", "period": 14},
                    "operator": ">",
                    "indicator_b": 70.0
                },
                "position_sizing": {
                    "type": "fixed_pct",
                    "value": 0.10
                },
                "risk_management": {
                    "stop_loss_pct": 0.05,
                    "take_profit_pct": 0.15
                },
                "max_concurrent_positions": 5,
                "risk_per_trade_cap_pct": 0.02
            }
            validated = StrategyConfig.model_validate(mock_strategy)
            with open(cache_path, "w") as f:
                json.dump(mock_strategy, f, indent=2)
            return validated
