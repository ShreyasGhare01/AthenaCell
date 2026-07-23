import os
import shutil
import pytest
from research.extractor import ResearchExtractor
from strategies.schema import StrategyConfig

TEMP_SEED_DIR = "tests/research/temp_seed_library"

@pytest.fixture(autouse=True)
def cleanup():
    if os.path.exists(TEMP_SEED_DIR):
        shutil.rmtree(TEMP_SEED_DIR)
    yield
    if os.path.exists(TEMP_SEED_DIR):
        shutil.rmtree(TEMP_SEED_DIR)

def test_mock_fallback_extraction():
    extractor = ResearchExtractor(seed_library_dir=TEMP_SEED_DIR)

    paper_text = "This paper details a momentum strategy that buys AAPL and MSFT when 50-day SMA is crossed upwards."
    strategy = extractor.extract_strategy_from_text(paper_text)

    assert isinstance(strategy, StrategyConfig)
    assert strategy.id.startswith("seed_")

    # Confirm cached file was saved
    cached_files = os.listdir(TEMP_SEED_DIR)
    assert len(cached_files) == 1
    assert cached_files[0].endswith(".json")
