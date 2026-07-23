import os
from data.sources.yfinance_source import YFinanceSource

class DataLoader:
    """
    Registry and wrapper to manage loading of historical datasets.
    """
    _sources = {
        "yfinance": YFinanceSource
    }

    @classmethod
    def get_source(cls, source_name: str, cache_dir: str = "data/cache"):
        if source_name not in cls._sources:
            raise ValueError(f"Unknown data source: {source_name}")
        return cls._sources[source_name](cache_dir=cache_dir)
