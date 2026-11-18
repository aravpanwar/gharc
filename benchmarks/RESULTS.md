# Benchmark results

All runs done on 2026-11-18 from a typical residential connection, against
the code released as v0.2.0 (commit 76a24a9) and, for comparison, v0.1.5 from
PyPI. The two versions were run back to back on the same night so that
connection changes affect both alike. The README performance figures come
from these numbers, and re-running the scripts in this directory should
reproduce them within reasonable variance.

## Host

- OS: Windows 11 Home
- CPU: 12 logical cores
- RAM: 16 GB installed, 15.3 GB usable by Windows (the rest is reserved for
  hardware); the benchmark scripts record the usable figure
- Python 3.11.9, pyarrow 26.0.1, orjson installed

## Smoke test (`smoke.py`)

Window: 2024-01-01 00:00 to 01:00 UTC (one hour), filtered to `apache/spark`.

| Metric | v0.2.0 | v0.1.5 |
|---|---|---|
| Wall-clock | 14.9 s | 10.1 s |
| Spark events recovered | 7 | 7 |
| Output file size | 26,665 bytes | 26,665 bytes |
| Workers | 1 | 1 |

Event-type breakdown of the 7 events: PullRequestReviewEvent (2),
PullRequestReviewCommentEvent (2), PullRequestEvent (2), IssueCommentEvent (1).
The mix is consistent with the 6-month Spark study finding that ~57% of
activity is code review.

Filter is tight: the only `repo.name` value present in the output is
`apache/spark`. Schema is stable, JSON-stringified `payload` re-parses
cleanly. A single one-hour download is too short for its timing to mean much.

## Throughput (`throughput.py`)

Window: 2024-01-01 00:00 to 06:00 UTC (six hours), filtered to `apache/spark`.
Each version ran twice, interleaved (v0.2.0, v0.1.5, ..., v0.1.5, v0.2.0).

| Version | Workers | Wall-clock (run 1, run 2) | Hours/sec (mean) | Spark events | Peak RSS |
|---|---|---|---|---|---|
| v0.2.0 | 1 | 55.2 s, 50.2 s | 0.114 | 14 | 52.6 MB |
| v0.1.5 | 1 | 63.1 s, 54.3 s | 0.102 | 14 | 52.8 MB |
| v0.2.0 | 4 | 41.6 s, 42.5 s | 0.143 | 14 | 70.2 MB |
| v0.1.5 | 4 | 47.6 s, 45.5 s | 0.129 | 14 | 70.4 MB |

Every run recovered the same 14 events, so neither the version nor the worker
count changes what is written. The Parquet file is 63,620 bytes, or 63,601
when four workers finish the hours in a different order and the rows compress
slightly differently; this happened once for each version.

v0.2.0 was 5 to 15 percent faster in all four pairs. For a repository-only
filter like this one the measured code path is essentially unchanged, and the
connection varied by up to 3x on identical work during the night (see the disk
section), so this is reported as no regression rather than a speedup.

Four workers gave only about 1.3x over one this time, against 2.2x in the
August round: the bottleneck is HTTPS download throughput, and the link was
slower. Peak RSS is about half the August figures (98.7 and 112.6 MB) for both
versions alike, so that change comes from the environment, not from gharc.

## Peak on-disk temp usage (`disk.py`)

gharc creates one temporary `.json.gz` per in-flight hour, so disk scales with
the worker count. Sampling the temp directory every 50 ms over the same 6-hour
window:

| Version | Workers | Peak disk | Concurrent temp files | Wall-clock |
|---|---|---|---|---|
| v0.2.0 | 1 | 84.6 MB | 1 | 68.6 s |
| v0.1.5 | 1 | 84.6 MB | 1 | 218.1 s |
| v0.2.0 | 4 | 250.6 MB | 4 | 50.7 s |
| v0.1.5 | 4 | 226.1 MB | 4 | 40.2 s |

Peak disk is bounded by `workers` times one hourly file. Which hours overlap
varies from run to run, so at the default 4 workers it lands between about
225 and 290 MB (291.7 MB in August). The 218 s single-worker run is the same
work as the others on a slow stretch of the connection, and is the reason the
throughput comparison above is not read as a speedup.

## Storage and disk footprint

For the 6-hour window above (the six hourly files measured 71.1, 84.6, 62.1,
70.9, 65.1, and 62.4 MB compressed):

- Source streamed from GHArchive (gzipped, all events): ~416 MB
- Filtered output for `apache/spark`: ~62 KB

The full source is still transferred, so this is not a bandwidth saving. What
stays bounded is local disk: gharc never holds a full hour on disk after
processing it, so peak disk tracks the in-flight temp files (one per worker,
measured in the section above) rather than the total downloaded volume.

## Four-month re-validation

The download script of the
[Spark reproduction](https://github.com/aravpanwar/Spark_Codebase_Evolution/tree/main/redo)
was re-run unchanged for January to April 2024 (2,904 hourly files) on
v0.2.0 at 4 workers, and compared with that study's published gharc 0.1.4
run of 2026-07-11:

| Month | Events, 0.1.4 | Events, 0.2.0 | Wall clock, 0.1.4 | Wall clock, 0.2.0 | Peak temp disk, 0.2.0 |
|---|---|---|---|---|---|
| 2024-01 | 6,143 | 6,143 | 106 min | 97 min | 538 MB |
| 2024-02 | 5,498 | 5,498 | 109 min | 99 min | 521 MB |
| 2024-03 | 7,577 | 7,577 | 113 min | 104 min | 576 MB |
| 2024-04 | 8,831 | 8,831 | 130 min | 109 min | 548 MB |
| Total | 28,049 | 28,049 | 7 h 38 min | 6 h 49 min | 576 MB (max) |

Every month recovered exactly the same number of events. The run needed no
restarts. Wall clock was 11 percent lower, but the two runs are months apart
on a residential connection, so this too is read as no regression. Parquet
sizes differ by under half a percent in either direction, from encoding rather
than content.
