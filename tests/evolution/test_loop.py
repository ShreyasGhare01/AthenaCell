import pytest
import os
import asyncio
from evolution.loop import EvolutionLoop
from storage.db import StorageManager, DBRun, DBStrategy

TEST_DB_URL = "sqlite:///tests/evolution/test_evolution.db"

@pytest.fixture(autouse=True)
def cleanup():
    db_file = "tests/evolution/test_evolution.db"
    if os.path.exists(db_file):
        os.remove(db_file)
    yield
    if os.path.exists(db_file):
        os.remove(db_file)

@pytest.mark.asyncio
async def test_evolution_loop():
    # Make a temporary run config with low population and 2 generations for speed
    import yaml
    with open("config/run_config.yaml", "r") as f:
        cfg = yaml.safe_load(f)

    cfg["run"]["population_size"] = 4
    cfg["run"]["generations"] = 2
    cfg["run"]["universe"] = ["AAPL"]
    cfg["run"]["start_date"] = "2022-01-01"
    cfg["run"]["end_date"] = "2023-06-30"

    # Let's adjust walk forward params to ensure folds are generated properly
    cfg["walk_forward"]["train_months"] = 6
    cfg["walk_forward"]["validate_months"] = 3
    cfg["walk_forward"]["step_months"] = 3

    temp_cfg_path = "tests/evolution/temp_run_config.yaml"
    with open(temp_cfg_path, "w") as f:
        yaml.dump(cfg, f)

    try:
        loop = EvolutionLoop(run_config_path=temp_cfg_path, db_url=TEST_DB_URL)

        broadcasts = []
        async def mock_broadcast(msg):
            broadcasts.append(msg)

        await loop.run_evolution(broadcast_fn=mock_broadcast)

        # Verify run completion
        storage = StorageManager(db_url=TEST_DB_URL)
        session = storage.get_session()

        run = session.query(DBRun).first()
        assert run is not None
        assert run.status == "completed"

        # Verify population was saved
        strats = session.query(DBStrategy).all()
        assert len(strats) > 0

        session.close()
    finally:
        if os.path.exists(temp_cfg_path):
            os.remove(temp_cfg_path)
