from abc import ABC, abstractmethod
from strategies.schema import StrategyConfig

class MutationOperator(ABC):
    """
    Abstract Base Class for Strategy mutation.
    Allows decoupling of different mutation operators.
    """
    @abstractmethod
    def mutate(self, strategy: StrategyConfig, reason_log: list) -> StrategyConfig:
        """
        Mutates a strategy and appends a reason to reason_log.
        """
        pass

class CrossoverOperator(ABC):
    """
    Abstract Base Class for Strategy Crossover/Recombination.
    """
    @abstractmethod
    def crossover(self, parent_a: StrategyConfig, parent_b: StrategyConfig, reason_log: list) -> StrategyConfig:
        pass

class StrategySeedSource(ABC):
    """
    Abstract Base Class for producing strategy seeds.
    """
    @abstractmethod
    def generate(self) -> StrategyConfig:
        pass
