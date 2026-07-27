import asyncio
import os
import yaml
import json
import threading
import queue
from typing import List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from storage.db import StorageManager, DBRun, DBGeneration, DBStrategy, DBStrategyFold, DBSimulatedTrade
from evolution.loop import EvolutionLoop
from research.extractor import ResearchExtractor

app = FastAPI(title="AthenaCell Research Sandbox Dashboard")

# Ensure static exist
os.makedirs("dashboard/static", exist_ok=True)
os.makedirs("dashboard/frontend", exist_ok=True)

# Mount Static Files
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")

# DB Storage setup
db_url = "sqlite:///data/athenacell.db"
storage = StorageManager(db_url=db_url)
extractor = ResearchExtractor()

# Active runs / WebSocket connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# Global thread-safe queue for background process communication
broadcast_queue = queue.Queue()

async def queue_listener_task():
    while True:
        try:
            while not broadcast_queue.empty():
                msg = broadcast_queue.get_nowait()
                await manager.broadcast(msg)
                broadcast_queue.task_done()
        except Exception as e:
            print(f"Error broadcasting from queue: {e}")
        await asyncio.sleep(0.5)

@app.on_event("startup")
def on_startup_cleanup_and_start_listener():
    # Mark any orphaned running runs as interrupted
    session = storage.get_session()
    try:
        orphaned = session.query(DBRun).filter_by(status="running").all()
        for r in orphaned:
            r.status = "interrupted"
        session.commit()
        if orphaned:
            print(f"Marked {len(orphaned)} orphaned running runs as 'interrupted' on startup.")
    except Exception as e:
        print(f"Error cleaning up orphaned runs: {e}")
    finally:
        session.close()

    # Schedule the asyncio queue listener task
    asyncio.create_task(queue_listener_task())


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("dashboard/frontend/index.html", "r") as f:
        return HTMLResponse(content=f.read(), status_code=200)

# REST endpoints
@app.get("/api/runs")
async def list_runs():
    session = storage.get_session()
    runs = session.query(DBRun).order_by(DBRun.created_at.desc()).all()
    res = []
    for r in runs:
        res.append({
            "id": r.id,
            "name": r.name,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None
        })
    session.close()
    return res

def run_evolution_in_thread(run_id: int):
    # Setup its own EvolutionLoop with separate database session
    loop_runner = EvolutionLoop(run_config_path="config/run_config.yaml", db_url=db_url)
    try:
        loop_runner.run_evolution(run_id=run_id, broadcast_queue=broadcast_queue)
    except Exception as e:
        print(f"Background evolution failed for run_id {run_id}: {e}")

@app.post("/api/runs/start")
async def start_run():
    # Load run config
    with open("config/run_config.yaml", "r") as f:
        run_config = yaml.safe_load(f)

    # 1. Create DBRun synchronously (fast, non-blocking DB write)
    session = storage.get_session()
    db_run = DBRun(
        name=run_config["run"]["name"],
        status="running",
        config=run_config
    )
    session.add(db_run)
    session.commit()
    run_id = db_run.id
    session.close()

    # 2. Spawn the background thread for evolution loop
    t = threading.Thread(target=run_evolution_in_thread, args=(run_id,))
    t.daemon = True
    t.start()

    # 3. Return run_id immediately (Moderate Fix #10)
    return {"run_id": run_id, "message": "Evolution task started in background."}

@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: int):
    session = storage.get_session()
    db_run = session.query(DBRun).filter_by(id=run_id).first()
    if not db_run:
        session.close()
        raise HTTPException(status_code=404, detail="Run not found")

    if db_run.status not in ["running", "failed", "interrupted"]:
        session.close()
        raise HTTPException(status_code=400, detail=f"Cannot resume a run in status {db_run.status}")

    # Set status to running
    db_run.status = "running"
    session.commit()
    session.close()

    # Spawn background thread to resume
    t = threading.Thread(target=run_evolution_in_thread, args=(run_id,))
    t.daemon = True
    t.start()

    return {"run_id": run_id, "message": "Evolution task resumed in background."}

@app.get("/api/runs/{run_id}/generations")
async def list_generations(run_id: int):
    session = storage.get_session()
    gens = session.query(DBGeneration).filter_by(run_id=run_id).order_by(DBGeneration.generation_number.asc()).all()
    res = []
    for g in gens:
        res.append({
            "id": g.id,
            "generation_number": g.generation_number,
            "created_at": g.created_at.isoformat() if g.created_at else None
        })
    session.close()
    return res

@app.get("/api/generations/{gen_id}/strategies")
async def list_strategies(gen_id: int):
    session = storage.get_session()
    strats = session.query(DBStrategy).filter_by(generation_id=gen_id).order_by(DBStrategy.agg_validation_sharpe.desc()).all()
    res = []
    for s in strats:
        res.append({
            "id": s.id,
            "name": s.name,
            "parent_id": s.parent_id,
            "mutation_type": s.mutation_type,
            "mutation_reason": s.mutation_reason,
            "agg_validation_sharpe": s.agg_validation_sharpe,
            "agg_validation_drawdown": s.agg_validation_drawdown,
            "agg_validation_win_rate": s.agg_validation_win_rate,
            "agg_train_validation_gap": s.agg_train_validation_gap,
            "risk_cap_applied": s.risk_cap_applied
        })
    session.close()
    return res

@app.get("/api/strategies/{strat_id}")
async def get_strategy(strat_id: str):
    session = storage.get_session()
    strat = session.query(DBStrategy).filter_by(id=strat_id).first()
    if not strat:
        session.close()
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Get fold details
    folds = session.query(DBStrategyFold).filter_by(strategy_id=strat_id).order_by(DBStrategyFold.fold_index.asc()).all()
    folds_res = []
    for f in folds:
        folds_res.append({
            "fold_index": f.fold_index,
            "train_start": f.train_start.isoformat() if f.train_start else None,
            "train_end": f.train_end.isoformat() if f.train_end else None,
            "val_start": f.val_start.isoformat() if f.val_start else None,
            "val_end": f.val_end.isoformat() if f.val_end else None,
            "train_sharpe": f.train_sharpe,
            "train_drawdown": f.train_drawdown,
            "train_win_rate": f.train_win_rate,
            "val_sharpe": f.val_sharpe,
            "val_drawdown": f.val_drawdown,
            "val_win_rate": f.val_win_rate,
            "train_equity_curve": f.train_equity_curve,
            "val_equity_curve": f.val_equity_curve
        })

    # Get trade logs
    trades = session.query(DBSimulatedTrade).filter_by(strategy_id=strat_id).order_by(DBSimulatedTrade.entry_date.asc()).all()
    trades_res = []
    for t in trades:
        trades_res.append({
            "fold_index": t.fold_index,
            "ticker": t.ticker,
            "entry_date": t.entry_date.isoformat() if t.entry_date else None,
            "entry_price": t.entry_price,
            "exit_date": t.exit_date.isoformat() if t.exit_date else None,
            "exit_price": t.exit_price,
            "size": t.size,
            "profit_pct": t.profit_pct,
            "exit_reason": t.exit_reason
        })

    res = {
        "id": strat.id,
        "name": strat.name,
        "parent_id": strat.parent_id,
        "mutation_type": strat.mutation_type,
        "mutation_reason": strat.mutation_reason,
        "agg_validation_sharpe": strat.agg_validation_sharpe,
        "agg_validation_drawdown": strat.agg_validation_drawdown,
        "agg_validation_win_rate": strat.agg_validation_win_rate,
        "agg_train_validation_gap": strat.agg_train_validation_gap,
        "risk_cap_applied": strat.risk_cap_applied,
        "config": strat.config_json,
        "folds": folds_res,
        "trades": trades_res
    }
    session.close()
    return res

@app.post("/api/research/upload")
async def upload_paper(file: UploadFile = File(...)):
    temp_path = f"data/cache/{file.filename}"
    with open(temp_path, "wb") as f:
        f.write(await file.read())

    try:
        # Extract strategy configuration
        if file.filename.lower().endswith(".pdf"):
            text = extractor.extract_text_from_pdf(temp_path)
        else:
            with open(temp_path, "r", encoding="utf-8") as f:
                text = f.read()

        strategy = extractor.extract_strategy_from_text(text)
        return {
            "message": "Strategy extracted successfully.",
            "strategy": strategy.model_dump()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.get("/api/research/library")
async def list_extracted_strategies():
    res = []
    seed_dir = "research/seed_library"
    if os.path.exists(seed_dir):
        for fn in os.listdir(seed_dir):
            if fn.endswith(".json"):
                with open(os.path.join(seed_dir, fn), "r") as f:
                    try:
                        res.append(json.load(f))
                    except Exception:
                        pass
    return res


# WebSockets Streaming API
@app.websocket("/ws/evolution")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Just keep the connection alive
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
