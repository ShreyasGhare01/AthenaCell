import logging
import pandas as pd
from typing import List
from data.sources.base import DataSource
from data.sources.exceptions import DataSourceError, AllDataSourcesFailedError

logger = logging.getLogger("athenacell")

class FallbackDataSource(DataSource):
    """
    A DataSource wrapper that holds an ordered list of DataSource instances.
    Attempts to fetch data using each source in order.
    If the primary source succeeds, optionally validates closing prices against a secondary source.
    """
    def __init__(self, sources: List[DataSource], validate_cross_source: bool = False, validation_threshold: float = 0.01):
        if not sources:
            raise ValueError("FallbackDataSource must be initialized with at least one DataSource.")
        self.sources = sources
        self.validate_cross_source = validate_cross_source
        self.validation_threshold = validation_threshold

    def fetch_data(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        failures = []
        ticker = ticker.upper()

        for idx, source in enumerate(self.sources):
            try:
                df = source.fetch_data(ticker, start_date, end_date)
                if df is not None and not df.empty:
                    # Log (at info level) which source ultimately served the ticker's data
                    msg = f"Successfully served data for ticker {ticker} from source {source.__class__.__name__}"
                    logger.info(msg)
                    print(msg)

                    # Trigger cross-source validation if enabled, we have multiple sources, and this is the primary source
                    if self.validate_cross_source and len(self.sources) > 1 and idx == 0:
                        self._validate_divergence(ticker, start_date, end_date, df)

                    return df
                else:
                    failures.append((source.__class__.__name__, "Returned empty DataFrame"))
            except Exception as e:
                err_msg = str(e) or e.__class__.__name__
                failures.append((source.__class__.__name__, err_msg))
                # Log warning about the source failure
                warning_log = f"Data source {source.__class__.__name__} failed for ticker {ticker}: {err_msg}"
                logger.warning(warning_log)
                print(warning_log)

        # All sources failed
        err_details = ", ".join(f"[{src}]: {err}" for src, err in failures)
        aggregate_msg = f"All data sources failed to fetch {ticker}. Tried: {err_details}"
        logger.error(aggregate_msg)
        raise AllDataSourcesFailedError(aggregate_msg)

    def _validate_divergence(self, ticker: str, start_date: str, end_date: str, primary_df: pd.DataFrame):
        """
        Lightweight cross-source validation check on last ~30 days of closing prices.
        """
        try:
            # Determine the overlapping window of last ~30 days
            start_ts = pd.to_datetime(start_date)
            end_ts = pd.to_datetime(end_date)
            comp_start = max(start_ts, end_ts - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
            comp_end = end_date

            secondary_source = self.sources[1]
            # Fetch last 30 days from secondary source
            secondary_df = secondary_source.fetch_data(ticker, comp_start, comp_end)

            if secondary_df is not None and not secondary_df.empty:
                # Find overlapping datetime index dates
                overlapping_dates = primary_df.index.intersection(secondary_df.index)
                if not overlapping_dates.empty:
                    # Compare closing prices on overlapping dates
                    p_close = primary_df.loc[overlapping_dates, "close"]
                    s_close = secondary_df.loc[overlapping_dates, "close"]

                    # Percent difference relative to primary closing price
                    divergence = (p_close - s_close).abs() / p_close
                    max_divergence = divergence.max()

                    if max_divergence > self.validation_threshold:
                        max_date = divergence.idxmax()
                        date_str = max_date.strftime("%Y-%m-%d") if isinstance(max_date, pd.Timestamp) else str(max_date)
                        warn_msg = (
                            f"WARNING: Cross-source validation divergence detected for ticker {ticker} "
                            f"between {self.sources[0].__class__.__name__} and {secondary_source.__class__.__name__}. "
                            f"Max closing price divergence is {max_divergence * 100:.2f}% on {date_str} "
                            f"(threshold: {self.validation_threshold * 100}%)."
                        )
                        logger.warning(warn_msg)
                        print(warn_msg)
        except Exception as e:
            # Cross-source validation is nice-to-have, do not let it fail the main execution path
            logger.debug(f"Cross-source validation failed for {ticker}: {e}")
