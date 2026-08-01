import logging
import random
import pandas as pd
from typing import List, Optional
from data.sources.base import DataSource
from data.sources.exceptions import DataSourceError, AllDataSourcesFailedError

logger = logging.getLogger("athenacell")

class FallbackDataSource(DataSource):
    """
    A DataSource wrapper that holds an ordered list of DataSource instances.
    Attempts to fetch data using each source in order.
    If a source succeeds, optionally validates closing prices against the next priority source.
    """
    def __init__(self, sources: List[DataSource], validate_cross_source: bool = False,
                 validation_threshold: float = 0.01, validation_sample_rate: float = 0.1):
        if not sources:
            raise ValueError("FallbackDataSource must be initialized with at least one DataSource.")
        self.sources = sources
        self.validate_cross_source = validate_cross_source
        self.validation_threshold = validation_threshold
        self.validation_sample_rate = validation_sample_rate
        self.run_id: Optional[int] = None
        self.db_url: Optional[str] = None

    def set_run_context(self, run_id: int, db_url: str):
        self.run_id = run_id
        self.db_url = db_url

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

                    # Trigger cross-source validation if enabled, we have multiple sources, and we sample it
                    if self.validate_cross_source and len(self.sources) > 1:
                        if random.random() < self.validation_sample_rate:
                            self._validate_divergence(ticker, start_date, end_date, df, idx)

                    return df
                else:
                    failures.append((source.__class__.__name__, "Returned empty DataFrame"))
            except DataSourceError as e:
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

    def _validate_divergence(self, ticker: str, start_date: str, end_date: str, primary_df: pd.DataFrame, idx: int):
        """
        Lightweight cross-source validation check on last ~30 days of closing prices.
        Compares against the next priority source (idx + 1) in the sources list.
        """
        if idx + 1 >= len(self.sources):
            # No next source in priority order to compare against, skip
            return

        try:
            # Determine the overlapping window of last ~30 days
            start_ts = pd.to_datetime(start_date)
            end_ts = pd.to_datetime(end_date)
            comp_start = max(start_ts, end_ts - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
            comp_end = end_date

            secondary_source = self.sources[idx + 1]
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
                        if isinstance(max_date, pd.Timestamp):
                            max_date_dt = max_date.to_pydatetime()
                        else:
                            max_date_dt = pd.to_datetime(max_date).to_pydatetime()

                        date_str = max_date_dt.strftime("%Y-%m-%d")
                        source_a_name = self.sources[idx].__class__.__name__
                        source_b_name = secondary_source.__class__.__name__

                        warn_msg = (
                            f"WARNING: Cross-source validation divergence detected for ticker {ticker} "
                            f"between {source_a_name} and {source_b_name}. "
                            f"Max closing price divergence is {max_divergence * 100:.2f}% on {date_str} "
                            f"(threshold: {self.validation_threshold * 100}%)."
                        )
                        logger.warning(warn_msg)
                        print(warn_msg)

                        # Write to DBDataQualityWarning if run_id and db_url are configured
                        if self.run_id is not None and self.db_url:
                            try:
                                from storage.db import StorageManager, DBDataQualityWarning
                                storage = StorageManager(db_url=self.db_url)
                                with storage.get_session() as session:
                                    warning_record = DBDataQualityWarning(
                                        run_id=self.run_id,
                                        ticker=ticker,
                                        date=max_date_dt,
                                        source_a=source_a_name,
                                        source_b=source_b_name,
                                        divergence_pct=float(max_divergence)
                                    )
                                    session.add(warning_record)
                                    session.commit()
                            except Exception as db_err:
                                logger.error(f"Failed to write DBDataQualityWarning: {db_err}")
        except Exception as e:
            # Cross-source validation is nice-to-have, do not let it fail the main execution path
            logger.debug(f"Cross-source validation failed for {ticker}: {e}")
