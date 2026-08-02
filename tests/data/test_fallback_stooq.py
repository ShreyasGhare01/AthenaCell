import os
import shutil
import pytest
import pandas as pd
import requests
from unittest.mock import MagicMock, patch
from data.sources.exceptions import (
    DataSourceError,
    DataSourceNoDataError,
    DataSourceConnectionError,
    DataSourceRateLimitError,
    AllDataSourcesFailedError
)
from data.sources.yfinance_source import YFinanceSource
from data.sources.stooq_source import StooqSource
from data.sources.fallback_source import FallbackDataSource
from data.loader import DataLoader

TEMP_TEST_CACHE = "tests/data/temp_stooq_cache"

@pytest.fixture(autouse=True)
def cleanup_cache():
    if os.path.exists(TEMP_TEST_CACHE):
        shutil.rmtree(TEMP_TEST_CACHE)
    yield
    if os.path.exists(TEMP_TEST_CACHE):
        shutil.rmtree(TEMP_TEST_CACHE)

def test_stooq_source_ticker_helper():
    source = StooqSource(cache_dir=TEMP_TEST_CACHE)
    assert source._get_stooq_ticker("AAPL") == "AAPL.US"
    assert source._get_stooq_ticker("aapl.us") == "AAPL.US"
    assert source._get_stooq_ticker("AAPL.US") == "AAPL.US"

@patch("requests.get")
def test_stooq_source_success(mock_get):
    # Mock successful CSV response from Stooq
    csv_data = """Date,Open,High,Low,Close,Volume
2023-01-01,100.0,105.0,99.0,102.0,1000
2023-01-02,102.0,106.0,101.0,104.0,1500
2023-01-03,104.0,108.0,103.0,107.0,2000
"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = csv_data
    mock_get.return_value = mock_resp

    source = StooqSource(cache_dir=TEMP_TEST_CACHE)
    df = source.fetch_data("AAPL", "2023-01-01", "2023-01-02")

    assert not df.empty
    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.loc["2023-01-01", "close"] == 102.0
    assert df.loc["2023-01-02", "close"] == 104.0

    # Confirm cache file is saved namespaced under the custom folder
    cache_file = os.path.join(TEMP_TEST_CACHE, "AAPL.parquet")
    assert os.path.exists(cache_file)

@patch("requests.get")
def test_stooq_source_anti_scraping_block(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><noscript>Browser verification required</noscript></html>"
    mock_get.return_value = mock_resp

    source = StooqSource(cache_dir=TEMP_TEST_CACHE)
    with pytest.raises(DataSourceRateLimitError) as exc:
        source.fetch_data("AAPL", "2023-01-01", "2023-01-02")
    assert "anti-scraping" in str(exc.value)

@patch("requests.get")
def test_stooq_source_not_found(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "Not Found"
    mock_get.return_value = mock_resp

    source = StooqSource(cache_dir=TEMP_TEST_CACHE)
    with pytest.raises(DataSourceNoDataError) as exc:
        source.fetch_data("AAPL", "2023-01-01", "2023-01-02")
    assert "No EOD data found" in str(exc.value)

@patch("requests.get")
def test_stooq_source_malformed_csv(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "Date,Open,High,Low,Volume\n2023-01-01,100,101,99,1000" # Missing Close
    mock_get.return_value = mock_resp

    source = StooqSource(cache_dir=TEMP_TEST_CACHE)
    with pytest.raises(DataSourceNoDataError) as exc:
        source.fetch_data("AAPL", "2023-01-01", "2023-01-02")
    assert "No EOD data found" in str(exc.value) or "Missing columns" in str(exc.value)

@patch("requests.get")
def test_stooq_source_network_timeout(mock_get):
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

    source = StooqSource(cache_dir=TEMP_TEST_CACHE)
    with pytest.raises(DataSourceConnectionError) as exc:
        source.fetch_data("AAPL", "2023-01-01", "2023-01-02")
    assert "Network error" in str(exc.value)


def test_fallback_data_source_primary_succeeds():
    mock_primary = MagicMock()
    mock_secondary = MagicMock()

    dummy_df = pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [100]},
        index=pd.to_datetime(["2023-01-01"])
    )
    mock_primary.fetch_data.return_value = dummy_df

    fallback = FallbackDataSource(sources=[mock_primary, mock_secondary])
    df = fallback.fetch_data("AAPL", "2023-01-01", "2023-01-01")

    assert df is dummy_df
    mock_primary.fetch_data.assert_called_once_with("AAPL", "2023-01-01", "2023-01-01")
    mock_secondary.fetch_data.assert_not_called()


def test_fallback_data_source_primary_fails_secondary_succeeds():
    mock_primary = MagicMock()
    mock_secondary = MagicMock()

    mock_primary.fetch_data.side_effect = DataSourceConnectionError("Timeout on primary")
    dummy_df = pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [100]},
        index=pd.to_datetime(["2023-01-01"])
    )
    mock_secondary.fetch_data.return_value = dummy_df

    fallback = FallbackDataSource(sources=[mock_primary, mock_secondary])
    df = fallback.fetch_data("AAPL", "2023-01-01", "2023-01-01")

    assert df is dummy_df
    mock_primary.fetch_data.assert_called_once_with("AAPL", "2023-01-01", "2023-01-01")
    mock_secondary.fetch_data.assert_called_once_with("AAPL", "2023-01-01", "2023-01-01")


def test_fallback_data_source_all_fail():
    mock_primary = MagicMock()
    mock_secondary = MagicMock()

    mock_primary.fetch_data.side_effect = DataSourceConnectionError("Timeout on primary")
    mock_secondary.fetch_data.side_effect = DataSourceNoDataError("No data on secondary")

    fallback = FallbackDataSource(sources=[mock_primary, mock_secondary])
    with pytest.raises(AllDataSourcesFailedError) as exc:
        fallback.fetch_data("AAPL", "2023-01-01", "2023-01-01")

    assert "Tried: [MagicMock]: Timeout on primary, [MagicMock]: No data on secondary" in str(exc.value)


@patch("logging.Logger.warning")
def test_fallback_data_source_cross_source_validation_divergence(mock_warn):
    mock_primary = MagicMock()
    mock_secondary = MagicMock()

    # Define primary data
    p_df = pd.DataFrame(
        {"open": [10.0, 10.0], "high": [11.0, 11.0], "low": [9.0, 9.0], "close": [100.0, 100.0], "volume": [100, 100]},
        index=pd.to_datetime(["2023-01-01", "2023-01-02"])
    )
    mock_primary.fetch_data.return_value = p_df

    # Define secondary data with 5% divergence on 2023-01-02
    s_df = pd.DataFrame(
        {"open": [10.0, 10.0], "high": [11.0, 11.0], "low": [9.0, 9.0], "close": [100.0, 95.0], "volume": [100, 100]},
        index=pd.to_datetime(["2023-01-01", "2023-01-02"])
    )
    mock_secondary.fetch_data.return_value = s_df

    fallback = FallbackDataSource(
        sources=[mock_primary, mock_secondary],
        validate_cross_source=True,
        validation_threshold=0.01, # 1% threshold
        validation_sample_rate=1.0 # Force validation in test
    )

    df = fallback.fetch_data("AAPL", "2023-01-01", "2023-01-02")
    assert df is p_df

    # Verify secondary source was called for the validation slice
    mock_secondary.fetch_data.assert_called_once()
    # Verify warning was logged due to 5% divergence > 1% threshold
    mock_warn.assert_called_once()
    assert "Cross-source validation divergence detected" in mock_warn.call_args[0][0]


def test_data_loader_build_behavior():
    # String config returns simple source
    src_string = DataLoader.get_source("stooq", cache_dir=TEMP_TEST_CACHE)
    assert isinstance(src_string, StooqSource)
    assert src_string.cache_dir == os.path.join(TEMP_TEST_CACHE, "stooq")

    # List config returns FallbackDataSource
    src_list = DataLoader.get_source(["yfinance", "stooq"], cache_dir=TEMP_TEST_CACHE)
    assert isinstance(src_list, FallbackDataSource)
    assert len(src_list.sources) == 2
    assert isinstance(src_list.sources[0], YFinanceSource)
    assert isinstance(src_list.sources[1], StooqSource)
    assert src_list.sources[0].cache_dir == os.path.join(TEMP_TEST_CACHE, "yfinance")
    assert src_list.sources[1].cache_dir == os.path.join(TEMP_TEST_CACHE, "stooq")


def test_fallback_data_source_storage_manager_integration():
    from storage.db import StorageManager, DBRun, DBDataQualityWarning
    # Create SQLite in-memory StorageManager
    storage = StorageManager(db_url="sqlite:///:memory:")

    # Create dummy run
    with storage.get_session() as session:
        run = DBRun(name="Test Run", config={})
        session.add(run)
        session.commit()
        run_id = run.id

    mock_primary = MagicMock()
    mock_secondary = MagicMock()

    # Define primary data
    p_df = pd.DataFrame(
        {"open": [10.0, 10.0], "high": [11.0, 11.0], "low": [9.0, 9.0], "close": [100.0, 100.0], "volume": [100, 100]},
        index=pd.to_datetime(["2023-01-01", "2023-01-02"])
    )
    mock_primary.fetch_data.return_value = p_df

    # Define secondary data with 5% divergence on 2023-01-02
    s_df = pd.DataFrame(
        {"open": [10.0, 10.0], "high": [11.0, 11.0], "low": [9.0, 9.0], "close": [100.0, 95.0], "volume": [100, 100]},
        index=pd.to_datetime(["2023-01-01", "2023-01-02"])
    )
    mock_secondary.fetch_data.return_value = s_df

    fallback = FallbackDataSource(
        sources=[mock_primary, mock_secondary],
        validate_cross_source=True,
        validation_threshold=0.01,
        validation_sample_rate=1.0
    )

    fallback.set_run_context(run_id=run_id, storage=storage)
    fallback.fetch_data("AAPL", "2023-01-01", "2023-01-02")

    # Assert that warning was correctly saved in the DB
    with storage.get_session() as session:
        warnings = session.query(DBDataQualityWarning).all()
        assert len(warnings) == 1
        warn = warnings[0]
        assert warn.run_id == run_id
        assert warn.ticker == "AAPL"
        assert warn.source_a == "MagicMock"
        assert warn.source_b == "MagicMock"
        assert abs(warn.divergence_pct - 0.05) < 1e-6
