# Benchmarks

Reproducible runs that back up the performance and correctness claims in
`paper/paper.md`.

Each script writes results to `benchmarks/results/` (gitignored) so the raw
data downloads don't bloat the repo.

## Scripts

- `smoke.py` — pulls one hour of GHArchive filtered to `apache/spark`. Sanity
  check that the pipeline produces well-formed Parquet on real data.
- `throughput.py` — runs gharc with 1 and 4 workers over a 6-hour window.
  Records wall-clock time, peak RAM, output size, and event count to JSON.
- `disk.py` — runs the same 6-hour window with 1 and 4 workers while sampling
  the temp directory, showing how peak on-disk temp usage scales with the
  worker count.

## How to run

```bash
pip install -e ".[test]" psutil
python benchmarks/smoke.py
python benchmarks/throughput.py
python benchmarks/disk.py
```

Results land in `benchmarks/results/` as `<script>_summary.json` plus any
output files the run produced.
