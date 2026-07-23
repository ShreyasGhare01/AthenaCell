import os
import pytest
from storage.db import StorageManager, DBRun, DBGeneration, DBStrategy

TEST_DB_URL = "sqlite:///tests/storage/test_athenacell.db"

@pytest.fixture(autouse=True)
def cleanup():
    db_file = "tests/storage/test_athenacell.db"
    if os.path.exists(db_file):
        os.remove(db_file)
    yield
    if os.path.exists(db_file):
        os.remove(db_file)

def test_db_operations():
    manager = StorageManager(db_url=TEST_DB_URL)
    session = manager.get_session()

    # 1. Create a run
    new_run = DBRun(name="Test Run", config={"population_size": 10}, status="idle")
    session.add(new_run)
    session.commit()
    assert new_run.id is not None

    # 2. Add a generation
    gen = DBGeneration(run_id=new_run.id, generation_number=1)
    session.add(gen)
    session.commit()
    assert gen.id is not None

    # 3. Add a strategy
    strat = DBStrategy(
        id="test_strat_1",
        generation_id=gen.id,
        name="Test SMA Crossover",
        config_json={"id": "test_strat_1", "name": "Test SMA Crossover", "universe": ["AAPL"]}
    )
    session.add(strat)
    session.commit()

    # 4. Fetch and verify
    fetched_strat = session.query(DBStrategy).filter_by(id="test_strat_1").first()
    assert fetched_strat is not None
    assert fetched_strat.generation.run.name == "Test Run"

    session.close()
