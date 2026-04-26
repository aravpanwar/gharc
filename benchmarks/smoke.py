"""Smoke test: pull one hour of GHArchive filtered to apache/spark.

Verifies the end-to-end pipeline on real data: download, gzip read, filter,
ParquetWriter, schema stability across event types.
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq

from gharc.streamer import process_range
from gharc.utils import setup_logging


HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def main():
    setup_logging()

    out = RESULTS_DIR / "spark_smoke.parquet"
    if out.exists():
        out.unlink()

    start = datetime(2024, 1, 1, 0)
    end = datetime(2024, 1, 1, 1)

    t0 = time.time()
    process_range(
        start=start,
        end=end,
        repos=["apache/spark"],
        event_types=None,
        output=str(out),
        workers=1,
    )
    elapsed = time.time() - t0

    if not out.exists():
        print("FAIL: no output file produced")
        sys.exit(1)

    table = pq.read_table(str(out))
    df = table.to_pandas()

    print()
    print(f"Output: {out}")
    print(f"Rows: {len(df)}")
    print(f"File size: {out.stat().st_size:,} bytes")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"Columns: {list(df.columns)}")

    if len(df):
        first = df.iloc[0]
        print(f"\nFirst event id: {first['id']}")
        print(f"First event type: {first['type']}")
        repo = json.loads(first["repo"])
        print(f"First event repo: {repo['name']}")

        # Every row should belong to apache/spark; the filter should not leak.
        repos = {json.loads(r)["name"] for r in df["repo"]}
        if repos != {"apache/spark"}:
            print(f"\nFAIL: filter leaked, found repos: {repos}")
            sys.exit(1)

        types = df["type"].value_counts().to_dict()
        print(f"Event-type breakdown: {types}")

    summary = {
        "window": [start.isoformat(), end.isoformat()],
        "rows": len(df),
        "file_size_bytes": out.stat().st_size,
        "elapsed_seconds": round(elapsed, 2),
        "columns": list(df.columns),
    }
    summary_path = RESULTS_DIR / "smoke_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary written to {summary_path}")


if __name__ == "__main__":
    main()
