import argparse
import uvicorn
import asyncio
import shutil
import os
from dashboard.backend.app import app

def main():
    parser = argparse.ArgumentParser(description="AthenaCell: Local-first stock-trading strategy evolution research sandbox.")
    parser.add_argument("--serve", action="store_true", help="Start the FastAPI local web dashboard server.")
    parser.add_argument("--config", type=str, default="config/run_config.yaml", help="Path to run parameters YAML config file.")
    parser.add_argument("--backup", type=str, default=None, help="Backup the SQLite DB (and optionally the cache directory) to the specified path.")
    parser.add_argument("--restore", type=str, default=None, help="Restore the SQLite DB (and optionally the cache directory) from the specified path.")
    parser.add_argument("--include-cache", action="store_true", help="Include the Parquet market data cache directory in backup/restore operations.")

    args = parser.parse_args()

    if args.backup:
        dest_dir = args.backup
        os.makedirs(dest_dir, exist_ok=True)

        # 1. Back up DB
        db_src = "data/athenacell.db"
        if os.path.exists(db_src):
            db_dest = os.path.join(dest_dir, "athenacell.db")
            shutil.copy2(db_src, db_dest)
            print(f"Database backed up successfully to {db_dest}")
        else:
            print("No database file found at data/athenacell.db to back up.")

        # 2. Back up Cache if requested
        if args.include_cache:
            cache_src = "data/cache"
            if os.path.exists(cache_src) and os.path.isdir(cache_src):
                cache_dest = os.path.join(dest_dir, "cache")
                if os.path.exists(cache_dest):
                    shutil.rmtree(cache_dest)
                shutil.copytree(cache_src, cache_dest)
                print(f"Cache directory backed up successfully to {cache_dest}")
            else:
                print("No cache directory found at data/cache to back up.")
        return

    if args.restore:
        src_dir = args.restore

        # Confirm prompt
        confirm = input("Are you sure you want to restore? This will overwrite your existing database! (y/n): ")
        if confirm.lower() not in ["y", "yes"]:
            print("Restore aborted.")
            return

        # 1. Restore DB
        db_src = os.path.join(src_dir, "athenacell.db")
        if os.path.exists(db_src):
            os.makedirs("data", exist_ok=True)
            db_dest = "data/athenacell.db"
            shutil.copy2(db_src, db_dest)
            print(f"Database restored successfully from {db_src} to {db_dest}")
        else:
            print(f"No database backup found at {db_src} to restore.")

        # 2. Restore Cache if requested
        if args.include_cache:
            cache_src = os.path.join(src_dir, "cache")
            if os.path.exists(cache_src) and os.path.isdir(cache_src):
                cache_dest = "data/cache"
                if os.path.exists(cache_dest):
                    shutil.rmtree(cache_dest)
                shutil.copytree(cache_src, cache_dest)
                print(f"Cache directory restored successfully from {cache_src} to {cache_dest}")
            else:
                print(f"No cache directory backup found at {cache_src} to restore.")
        return

    if args.serve:
        print("Starting AthenaCell Local Dashboard Server on http://localhost:8000 ...")
        # Runs uvicorn server binding strictly to localhost for safety
        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        # Command line entry point: trigger a small walk-forward evolution run immediately
        from evolution.loop import EvolutionLoop
        print(f"Triggering CLI evolution run using config: {args.config}")
        loop = EvolutionLoop(run_config_path=args.config)
        loop.run_evolution()
        print("CLI evolution run completed successfully.")

if __name__ == "__main__":
    main()
