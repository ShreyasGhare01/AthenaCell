class DataSourceError(Exception):
    """Base exception class for all data source errors."""
    pass

class DataSourceUnavailableError(DataSourceError):
    """Raised when a data source is misconfigured or unavailable (e.g., missing API key)."""
    pass

class DataSourceNoDataError(DataSourceError):
    """Raised when a data source returns no data for the requested ticker/range."""
    pass

class DataSourceConnectionError(DataSourceError):
    """Raised when a network or connection error occurs while fetching data."""
    pass

class DataSourceRateLimitError(DataSourceError):
    """Raised when a data source's rate limit is exceeded."""
    pass

class AllDataSourcesFailedError(DataSourceError):
    """Raised when all configured data sources fail to fetch data."""
    pass
