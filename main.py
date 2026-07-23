import argparse
import uvicorn
import asyncio
from dashboard.backend.app import app

def main():
    parser = argparse.ArgumentParser(description="AthenaCell: Local-first stock-trading strategy evolution research sandbox.")
    parser.add_argument("--serve", action="store_true", help="Start the FastAPI local web dashboard server.")
    parser.add_argument("--config", type=str, default="config/run_config.yaml", help="Path to run parameters YAML config file.")

    args = parser.parse_args()

    if args.serve:
        print("Starting AthenaCell Local Dashboard Server on http://localhost:8000 ...")
        # Runs uvicorn server binding strictly to localhost for safety
        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        # Command line entry point: trigger a small walk-forward evolution run immediately
        from evolution.loop import EvolutionLoop
        print(f"Triggering CLI evolution run using config: {args.config}")
        loop = EvolutionLoop(run_config_path=args.config)
        asyncio.run(loop.run_evolution())
        print("CLI evolution run completed successfully.")

if __name__ == "__main__":
    main()
