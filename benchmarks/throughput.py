"""Throughput benchmark: how fast does gharc chew through hours of GHArchive?

Runs the same 6-hour window twice, once with one worker and once with four,
captures wall-clock time, peak RSS, output size, and event count. Writes a
single JSON result so the paper can cite real numbers.
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil
import pyarrow.parquet as pq

from gharc.streamer import process_range
from gharc.utils import setup_logging


HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

WINDOW_START = datetime(2024, 1, 1, 0)
WINDOW_END = datetime(2024, 1, 1, 6)
REPOS = ["apache/spark"]
WORKER_CONFIGS = [1, 4]


def sample_peak_rss(stop_event, stats, interval=0.25):
    proc = psutil.Process()
    peak = 0
    while not stop_event.is_set():
        rss = proc.memory_info().rss
        if rss > peak:
            peak = rss
        time.sleep(interval)
    stats["peak_rss_bytes"] = peak


def run_one(workers):
    out = RESULTS_DIR / f"throughput_w{workers}.parquet"
    if out.exists():
        out.unlink()

    stop = threading.Event()
    stats = {}
    sampler = threading.Thread(target=sample_peak_rss, args=(stop, stats))
    sampler.start()

    t0 = time.time()
    process_range(
        start=WINDOW_START,
        end=WINDOW_END,
        repos=REPOS,
        event_types=None,
        output=str(out),
        workers=workers,
    )
    elapsed = time.time() - t0

    stop.set()
    sampler.join()

    table = pq.read_table(str(out))
    rows = table.num_rows
    size = out.stat().st_size

    return {
        "workers": workers,
        "elapsed_seconds": round(elapsed, 2),
        "hours_processed": (WINDOW_END - WINDOW_START).total_seconds() / 3600,
        "hours_per_second": round((WINDOW_END - WINDOW_START).total_seconds() / 3600 / elapsed, 4),
        "events_recovered": rows,
        "output_bytes": size,
        "peak_rss_mb": round(stats["peak_rss_bytes"] / (1024 * 1024), 1),
    }


def main():
    setup_logging()
    print(f"Window: {WINDOW_START} to {WINDOW_END} ({(WINDOW_END - WINDOW_START).total_seconds() / 3600:.0f} hours)")
    print(f"Repos: {REPOS}")

    results = []
    for w in WORKER_CONFIGS:
        print(f"\n--- workers={w} ---")
        result = run_one(w)
        print(json.dumps(result, indent=2))
        results.append(result)

    summary = {
        "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "repos": REPOS,
        "machine": {
            "cpu_count": psutil.cpu_count(logical=True),
            "total_ram_gb": round(psutil.virtual_memory().total / (1024 ** 3), 1),
        },
        "runs": results,
    }
    out_path = RESULTS_DIR / "throughput_summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary: {out_path}")


if __name__ == "__main__":
    main()
