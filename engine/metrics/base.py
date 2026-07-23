from abc import ABC, abstractmethod
import numpy as np

class ScoringMetric(ABC):
    """
    Abstract Base Class for Scoring Metrics.
    Allows dynamic registration and ranking of strategy performance.
    """
    @abstractmethod
    def calculate(self, daily_returns: np.ndarray, equity_curve: np.ndarray) -> float:
        """
        Calculates the scoring metric.

        Parameters:
            daily_returns: A numpy 1D array of daily pct returns.
            equity_curve: A numpy 1D array of daily absolute equity values.

        Returns:
            The calculated score as a float.
        """
        pass
