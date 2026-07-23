from abc import ABC, abstractmethod
import pandas as pd

class DataSource(ABC):
    """
    Abstract Base Class for Data Sources.
    Allows decoupling of different market data providers (yfinance, Alpaca, etc.).
    """
    @abstractmethod
    def fetch_data(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetches historical daily market data for the given ticker and date range.

        Parameters:
            ticker: The stock ticker string (e.g. 'AAPL')
            start_date: Start date string 'YYYY-MM-DD'
            end_date: End date string 'YYYY-MM-DD'

        Returns:
            A Pandas DataFrame with columns: ['open', 'high', 'low', 'close', 'volume']
            indexed by datetime (as Timestamp or string).
        """
        pass
