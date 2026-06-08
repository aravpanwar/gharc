"""Disk benchmark: measure peak on-disk temp usage during a real run.

gharc creates one tempfile.mkstemp(suffix='.json.gz') per in-flight hour, so
peak local disk scales with the worker count rather than staying at a single
file. This samples the temp directory while running the same 6-hour window
once with one worker and once with four, and records peak total temp-file size
alongside peak RSS for comparison.
"""
import glob
import json
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil

from gharc.streamer import process_range
from gharc.utils import setup_logging


HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

TMP = tempfile.gettempdir()
WINDOW_START = datetime(2024, 1, 1, 0)
WINDOW_END = datetime(2024, 1, 1, 6)
REPOS = ["apache/spark"]
WORKER_CONFIGS = [1, 4]


def sample_peaks(stop_event, stats, interval=0.05):
    """Track peak temp-file disk usage and peak RSS until told to stop."""
    proc = psutil.Process()
    peak_disk = 0
    peak_files = 0
    peak_rss = 0
    while not stop_event.is_set():
        total = 0
        files = glob.glob(os.path.join(TMP, "*.json.gz"))
        for path in files:
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        peak_disk = max(peak_disk, total)
        peak_files = max(peak_files, len(files))
        peak_rss = max(peak_rss, proc.memory_info().rss)
        time.sleep(interval)
    stats["peak_disk_mb"] = round(peak_disk / (1024 * 1024), 1)
    stats["peak_concurrent_files"] = peak_files
    stats["peak_rss_mb"] = round(peak_rss / (1024 * 1024), 1)


def run_one(workers):
    out = RESULTS_DIR / f"disk_w{workers}.jsonl"
    for path in (out, Path(str(out) + ".state.json")):
        if path.exists():
            path.unlink()

    stop = threading.Event()
    stats = {}
    sampler = threading.Thread(target=sample_peaks, args=(stop, stats))
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

    events = sum(1 for _ in out.open(encoding="utf-8"))
    out.unlink()

    return {
        "workers": workers,
        "elapsed_seconds": round(elapsed, 2),
        "events_recovered": events,
        **stats,
    }


def main():
    setup_logging()
    print(f"Window: {WINDOW_START} to {WINDOW_END}")
    print(f"Repos: {REPOS}")
    print(f"Temp dir sampled: {TMP}")

    results = []
    for workers in WORKER_CONFIGS:
        print(f"\n--- workers={workers} ---")
        result = run_one(workers)
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
    out_path = RESULTS_DIR / "disk_summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary: {out_path}")


if __name__ == "__main__":
    main()
