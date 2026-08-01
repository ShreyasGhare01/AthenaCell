import os
from typing import List, Union
from data.sources.base import DataSource
from data.sources.yfinance_source import YFinanceSource
from data.sources.stooq_source import StooqSource
from data.sources.fallback_source import FallbackDataSource

class DataLoader:
    """
    Registry and wrapper to manage loading of historical datasets.
    Supports single data sources or priority-ordered lists of sources for redundancy.
    """
    _sources = {
        "yfinance": YFinanceSource,
        "stooq": StooqSource
    }

    @classmethod
    def get_source(cls, source_name: Union[str, List[str]], cache_dir: str = "data/cache",
                   validate_cross_source: bool = False, validation_threshold: float = 0.01) -> DataSource:
        """
        Retrieves a DataSource instance. If a list of source names is passed, constructs
        a FallbackDataSource wrapping those sources in the specified priority order.
        """
        if isinstance(source_name, list):
            # Construct a FallbackDataSource wrapping the named sources in that order
            sources = []
            for name in source_name:
                if name not in cls._sources:
                    raise ValueError(f"Unknown data source in fallback list: {name}")
                # Separate subdirectories for namespace safety
                sources.append(cls._sources[name](cache_dir=os.path.join(cache_dir, name)))
            return FallbackDataSource(
                sources=sources,
                validate_cross_source=validate_cross_source,
                validation_threshold=validation_threshold
            )
        else:
            if source_name not in cls._sources:
                raise ValueError(f"Unknown data source: {source_name}")
            # Separate subdirectories for namespace safety
            return cls._sources[source_name](cache_dir=os.path.join(cache_dir, source_name))
