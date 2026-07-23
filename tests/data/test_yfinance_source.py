import os
import shutil
import pandas as pd
import pytest
from data.sources.yfinance_source import YFinanceSource

TEMP_CACHE_DIR = "tests/data/temp_cache"

@pytest.fixture(autouse=True)
def cleanup():
    # Setup
    if os.path.exists(TEMP_CACHE_DIR):
        shutil.rmtree(TEMP_CACHE_DIR)
    yield
    # Teardown
    if os.path.exists(TEMP_CACHE_DIR):
        shutil.rmtree(TEMP_CACHE_DIR)

def test_yfinance_source_cache():
    # Mocking or fetching a tiny bit of live data.
    # Let's request 10 days of SPY.
    source = YFinanceSource(cache_dir=TEMP_CACHE_DIR)
    ticker = "SPY"
    start_date = "2023-01-01"
    end_date = "2023-01-10"

    df = source.fetch_data(ticker, start_date, end_date)
    assert not df.empty
    assert "close" in df.columns
    assert "open" in df.columns
    assert "high" in df.columns
    assert "low" in df.columns
    assert "volume" in df.columns

    # Confirm parquet file created
    cache_file = os.path.join(TEMP_CACHE_DIR, f"{ticker}.parquet")
    assert os.path.exists(cache_file)

    # Verify reading from cache on a second request (should not crash and cover range)
    df2 = source.fetch_data(ticker, "2023-01-02", "2023-01-08")
    assert not df2.empty
    assert len(df2) <= len(df)
