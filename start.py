"""Start or stop this checkout's local JobAgent server."""

import argparse
import json
import os
import runpy
from pathlib import Path

try:
    import psutil
except ModuleNotFoundError as exc:
    if exc.name != "psutil":
        raise
    raise SystemExit("Install dependencies: python -m pip install -r backend/requirements.txt") from None


ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / "data" / "local-server.pid.json"


def remove_record(record: dict) -> None:
    try:
        if json.loads(PID_FILE.read_text(encoding="utf-8")) == record:
            PID_FILE.unlink(missing_ok=True)
    except FileNotFoundError:
        pass


def stop() -> None:
    try:
        record = json.loads(PID_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print("No managed JobAgent process is recorded.")
        return
    try:
        process = psutil.Process(record["pid"])
        if process.create_time() != record["started"]:
            print("The recorded JobAgent process has already exited.")
        else:
            process.terminate()
            process.wait(timeout=15)
            print("JobAgent stopped.")
    except psutil.NoSuchProcess:
        print("The recorded JobAgent process has already exited.")
    except psutil.TimeoutExpired:
        raise SystemExit("JobAgent has not stopped yet. Retry in a moment.") from None
    except psutil.AccessDenied:
        raise SystemExit("Permission denied. Use the account that started JobAgent.") from None
    remove_record(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop"), nargs="?", default="start")
    if parser.parse_args().action == "stop":
        stop()
        return

    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise SystemExit("Frontend build missing. Run: npm --prefix frontend run build")
    record = {"pid": os.getpid(), "started": psutil.Process().create_time()}
    PID_FILE.parent.mkdir(exist_ok=True)
    try:
        with PID_FILE.open("x", encoding="utf-8") as handle:
            json.dump(record, handle)
    except FileExistsError:
        raise SystemExit("A JobAgent process is already recorded. Run: python start.py stop") from None
    try:
        os.chdir(ROOT)
        runpy.run_path(str(ROOT / "backend" / "main.py"), run_name="__main__")
    finally:
        remove_record(record)


if __name__ == "__main__":
    main()
