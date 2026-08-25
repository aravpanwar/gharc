# Benchmark results

All runs done on 2026-08-25 from a typical residential connection. Paper
claims should cite these numbers and re-running the scripts in this
directory should reproduce them within reasonable variance.

## Host

- OS: Windows 11 Home
- CPU: 12 logical cores
- RAM: 15.3 GB total

## Smoke test (`smoke.py`)

Window: 2024-01-01 00:00 to 01:00 UTC (one hour), filtered to `apache/spark`.

| Metric | Value |
|---|---|
| Wall-clock | 9.7 s |
| Spark events recovered | 7 |
| Output file size | 26,665 bytes |
| Workers | 1 |

Event-type breakdown of the 7 events: PullRequestReviewEvent (2),
PullRequestReviewCommentEvent (2), PullRequestEvent (2), IssueCommentEvent (1).
The mix is consistent with the 6-month Spark study finding that ~57% of
activity is code review.

Filter is tight: the only `repo.name` value present in the output is
`apache/spark`. Schema is stable, JSON-stringified `payload` re-parses
cleanly.

## Throughput (`throughput.py`)

Window: 2024-01-01 00:00 to 06:00 UTC (six hours), filtered to `apache/spark`.

| Workers | Wall-clock | Hours/sec | Spark events | Peak RSS |
|---|---|---|---|---|
| 1 | 45.6 s | 0.132 | 14 | 98.7 MB |
| 4 | 21.1 s | 0.285 | 14 | 112.6 MB |

Both runs recovered the same 14 events (correctness preserved across worker
counts). Peak RSS stayed under 115 MB in both configurations, close to the
README claim of a ~100 MB working footprint.

The 4-worker run is 2.16x faster than 1-worker here, a wider gap than the
1.31x measured in the previous round on the same window. Wall-clock for both
worker counts also dropped by roughly half. The bottleneck is still HTTPS
download throughput rather than CPU, so this reflects residential-connection
variance between runs, not a code change; the code path in this area is
unchanged since 0.1.3.

## Peak on-disk temp usage (`disk.py`, measured 2026-08-25)

The throughput run above sampled peak RSS but not peak disk. gharc creates one
temporary `.json.gz` per in-flight hour, so disk scales with the worker count.
Sampling the temp directory every 50 ms over the same 6-hour window:

| Workers | Peak disk | Concurrent temp files |
|---|---|---|
| 1 | 84.6 MB | 1 |
| 4 | 291.7 MB | 4 |

Peak disk is bounded by `workers` times one hourly file, not by a single
in-flight download. With the default 4 workers, expect roughly 290 MB.

## Storage and disk footprint

For the 6-hour window above (the six hourly files measured 71.1, 84.6, 62.1,
70.9, 65.1, and 62.4 MB compressed):

- Source streamed from GHArchive (gzipped, all events): ~416 MB
- Filtered output for `apache/spark`: ~62 KB

The full source is still transferred, so this is not a bandwidth saving. What
stays bounded is local disk: gharc never holds a full hour on disk after
processing it, so peak disk tracks the in-flight temp files (one per worker,
measured in the section above) rather than the total downloaded volume.
