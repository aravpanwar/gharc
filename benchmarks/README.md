# Benchmarks

Reproducible runs that back up the performance and correctness claims in
`paper/paper.md`.

Each script writes results to `benchmarks/results/` (gitignored) so the raw
data downloads don't bloat the repo.

## Scripts

- `smoke.py` — pulls one hour of GHArchive filtered to `apache/spark`. Sanity
  check that the pipeline produces well-formed Parquet on real data.
- `throughput.py` — runs gharc across worker counts (1, 2, 4, 8) on a 24-hour
  window. Records wall-clock time, peak RAM, peak disk, and output size to
  JSON.
- `filter_effectiveness.py` — same 24-hour window with and without a repo
  filter, showing the storage saving from streaming-and-filtering.

## How to run

```bash
pip install -e ".[test]" psutil
python benchmarks/smoke.py
python benchmarks/throughput.py
python benchmarks/filter_effectiveness.py
```

Results land in `benchmarks/results/<script>_<timestamp>.json` and any output
parquet files in `benchmarks/results/`.
