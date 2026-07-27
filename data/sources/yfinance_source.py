import os
import pandas as pd
import yfinance as yf
from data.sources.base import DataSource

class YFinanceSource(DataSource):
    """
    A concrete DataSource using yfinance.
    Saves historical data locally as Parquet files under `data/cache/` to minimize rate-limiting and ensure offline functionality.
    """
    def __init__(self, cache_dir: str = "data/cache"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_filepath(self, ticker: str) -> str:
        return os.path.join(self.cache_dir, f"{ticker.upper()}.parquet")

    def fetch_data(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        ticker = ticker.upper()
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

        # Otherwise, download from yfinance
        # Fetch a bit of extra margin to avoid boundary missing issues
        margin_start = (start_ts - pd.Timedelta(days=100)).strftime("%Y-%m-%d")
        margin_end = (end_ts + pd.Timedelta(days=5)).strftime("%Y-%m-%d")

        print(f"Downloading {ticker} from yfinance: {margin_start} to {margin_end}...")
        df_yf = yf.download(ticker, start=margin_start, end=margin_end, progress=False, auto_adjust=True)

        if df_yf.empty:
            raise ValueError(f"No data returned for ticker {ticker} from yfinance.")

        # Clean columns and index
        # Some yfinance returns MultiIndex if downloaded with a list, but we requested a string.
        # Let's flatten and normalize column names to lowercase.
        if isinstance(df_yf.columns, pd.MultiIndex):
            df_yf.columns = df_yf.columns.get_level_values(0)

        df_yf = df_yf.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        })

        keep_cols = ["open", "high", "low", "close", "volume"]
        df_yf = df_yf[keep_cols].dropna()

        # Ensure index is datetime
        df_yf.index = pd.to_datetime(df_yf.index)

        # Read existing file to merge or overwrite
        if os.path.exists(cache_file):
            df_old = pd.read_parquet(cache_file)
            df_old.index = pd.to_datetime(df_old.index)
            # Combine without duplicates
            df_combined = pd.concat([df_old, df_yf]).sort_index()
            df_combined = df_combined[~df_combined.index.duplicated(keep="last")]
        else:
            df_combined = df_yf.sort_index()

        # Save combination to Parquet cache
        df_combined.to_parquet(cache_file)

        # Return requested range
        mask = (df_combined.index >= start_ts) & (df_combined.index <= end_ts)
        return df_combined.loc[mask]
