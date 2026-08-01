import os
import io
import requests
import pandas as pd
from data.sources.base import DataSource
from data.sources.exceptions import (
    DataSourceNoDataError,
    DataSourceConnectionError,
    DataSourceRateLimitError
)

class StooqSource(DataSource):
    """
    A concrete DataSource using Stooq EOD CSV endpoints.
    Saves historical data locally as Parquet files under `data/cache/stooq/` to minimize rate-limiting and ensure offline functionality.
    """
    def __init__(self, cache_dir: str = "data/cache"):
        # Namespace standard default cache to subfolder to keep sources separate
        if cache_dir == "data/cache":
            self.cache_dir = os.path.join(cache_dir, "stooq")
        else:
            self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_filepath(self, ticker: str) -> str:
        return os.path.join(self.cache_dir, f"{ticker.upper()}.parquet")

    def _get_stooq_ticker(self, ticker: str) -> str:
        """
        Auto-appends .US suffix in an isolated, clean helper function.
        """
        ticker = ticker.upper()
        if not ticker.endswith(".US"):
            return f"{ticker}.US"
        return ticker

    def fetch_data(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        ticker = ticker.upper()
        stooq_ticker = self._get_stooq_ticker(ticker)
        cache_file = self._get_cache_filepath(ticker)

        # Parse datetime inputs
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)

        # Check if local parquet cache exists
        if os.path.exists(cache_file):
            df_cached = pd.read_parquet(cache_file)

            # Ensure index is datetime
            if not isinstance(df_cached.index, pd.DatetimeIndex):
                df_cached.index = pd.to_datetime(df_cached.index)

            # If the cached range covers the requested start and end, slice and return
            cached_min = df_cached.index.min()
            cached_max = df_cached.index.max()

            if cached_min <= start_ts and cached_max >= end_ts:
                mask = (df_cached.index >= start_ts) & (df_cached.index <= end_ts)
                return df_cached.loc[mask]

        # Otherwise, download from Stooq CSV EOD URL
        url = f"https://stooq.com/q/d/l/?s={stooq_ticker}&i=d"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }

        print(f"Downloading {stooq_ticker} from Stooq: {start_date} to {end_date}...")
        try:
            response = requests.get(url, headers=headers, timeout=15)
        except Exception as e:
            raise DataSourceConnectionError(f"Network error downloading {stooq_ticker} from Stooq: {e}") from e

        if response.status_code != 200:
            raise DataSourceConnectionError(f"Failed to fetch data from Stooq (HTTP {response.status_code}).")

        text = response.text.strip()

        # Check for browser verification or rate-limiting block html
        if "<html" in text.lower() or "<noscript" in text.lower() or "__verify" in text:
            # Stooq served browser verification challenge instead of CSV data
            raise DataSourceConnectionError("Stooq request blocked by anti-scraping browser verification challenge.")

        if not text or text.lower().startswith("not found") or text.lower().startswith("no data") or "close" not in text.lower():
            raise DataSourceNoDataError(f"No EOD data found for ticker {ticker} (Stooq ticker: {stooq_ticker}) from Stooq.")

        try:
            # Parse CSV
            df_stooq = pd.read_csv(io.StringIO(text))
        except Exception as e:
            raise DataSourceNoDataError(f"Failed to parse CSV data from Stooq for {stooq_ticker}: {e}")

        # Normalize column names to lowercase
        df_stooq.columns = [col.lower() for col in df_stooq.columns]

        # Map typical Stooq columns: date, open, high, low, close, volume
        # Ensure we have date or set it as index
        if "date" in df_stooq.columns:
            df_stooq["date"] = pd.to_datetime(df_stooq["date"])
            df_stooq.set_index("date", inplace=True)
        else:
            raise DataSourceNoDataError(f"Missing Date column in Stooq response for {stooq_ticker}.")

        # Rename core columns to be safe
        df_stooq = df_stooq.rename(columns={
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume"
        })

        keep_cols = ["open", "high", "low", "close", "volume"]
        missing_cols = [col for col in keep_cols if col not in df_stooq.columns]
        if missing_cols:
            raise DataSourceNoDataError(f"Missing columns {missing_cols} in Stooq data for {stooq_ticker}.")

        df_stooq = df_stooq[keep_cols].dropna()

        # Sort index
        df_stooq = df_stooq.sort_index()

        # Read existing file to merge or overwrite
        if os.path.exists(cache_file):
            df_old = pd.read_parquet(cache_file)
            df_old.index = pd.to_datetime(df_old.index)
            # Combine without duplicates
            df_combined = pd.concat([df_old, df_stooq]).sort_index()
            df_combined = df_combined[~df_combined.index.duplicated(keep="last")]
        else:
            df_combined = df_stooq.sort_index()

        # Save combination to Parquet cache
        df_combined.to_parquet(cache_file)

        # Return requested range
        mask = (df_combined.index >= start_ts) & (df_combined.index <= end_ts)
        return df_combined.loc[mask]
