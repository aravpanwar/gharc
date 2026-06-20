"""Run gharc month-by-month over a long date range.

Useful when you're working on a laptop and want one parquet file per month
rather than one giant file. Edit the configuration at the top to fit your
machine, then run: python examples/orchestrator.py
"""
import argparse
import os
import subprocess
from datetime import datetime, timedelta


def get_month_ranges(start, end):
    current = start
    while current < end:
        next_month = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
        chunk_end = min(next_month, end)

        s_str = current.strftime("%Y-%m-%d-%H")
        e_str = chunk_end.strftime("%Y-%m-%d-%H")

        yield current, chunk_end, s_str, e_str
        current = next_month


def main():
    p = argparse.ArgumentParser(description="Run gharc month-by-month.")
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD (exclusive)")
    p.add_argument("--repos", required=True, help="Comma-separated repos")
    p.add_argument("--output-dir", default="./gharc_out", help="Output directory")
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    os.makedirs(args.output_dir, exist_ok=True)
    print(f"Batch run: {start.date()} to {end.date()}")
    print(f"Output: {args.output_dir}")

    for start_dt, _end_dt, s_str, e_str in get_month_ranges(start, end):
        month_name = start_dt.strftime("%Y-%m")
        parquet_file = os.path.join(args.output_dir, f"gharchive_{month_name}.parquet")
        # Download to JSONL first so a crashed month resumes from its state
        # file, then convert to Parquet. A whole-month Parquet download cannot
        # resume, since Parquet writers cannot append to a closed file.
        jsonl_file = os.path.join(args.output_dir, f"gharchive_{month_name}.jsonl")

        if os.path.exists(parquet_file):
            print(f"Skipping {month_name} (file exists)")
            continue

        print(f"\nProcessing {month_name}...")

        download_cmd = [
            "gharc", "download",
            "--start", s_str,
            "--end", e_str,
            "--repos", args.repos,
            "--output", jsonl_file,
            "--workers", str(args.workers),
        ]

        try:
            subprocess.run(download_cmd, check=True)
            subprocess.run(["gharc", "convert", jsonl_file, parquet_file], check=True)
            os.remove(jsonl_file)
            print(f"Finished {month_name}")
        except subprocess.CalledProcessError:
            print(f"Error processing {month_name}, continuing (rerun resumes it)")


if __name__ == "__main__":
    main()
