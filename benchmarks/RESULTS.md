# Benchmark results

All runs done on 2026-04-26 from a residential connection in Hyderabad,
India. Paper claims should cite these numbers and re-running the scripts in
this directory should reproduce them within reasonable variance.

## Host

- OS: Windows 11 Home
- CPU: 12 logical cores
- RAM: 15.3 GB total

## Smoke test (`smoke.py`)

Window: 2024-01-01 00:00 to 01:00 UTC (one hour), filtered to `apache/spark`.

| Metric | Value |
|---|---|
| Wall-clock | 18.2 s |
| Spark events recovered | 7 |
| Output file size | 28,963 bytes |
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
| 1 | 76.0 s | 0.079 | 14 | 94.2 MB |
| 4 | 58.1 s | 0.103 | 14 | 106.7 MB |

Both runs recovered the same 14 events (correctness preserved across worker
counts). Peak RSS stayed under 110 MB in both configurations, which matches
the README claim of a ~100 MB working footprint.

The 4-worker run is 1.31x faster than 1-worker. The bottleneck is HTTPS
download throughput, not CPU; on a residential link the parallelism saturates
quickly. On hardware with a faster uplink the scaling would be steeper.

## Storage saving from filtering

For the 6-hour window above:

- Approximate raw GHArchive download (gzipped, all events): ~1.2 GB
- Filtered output for `apache/spark`: 53 KB
- Storage ratio: roughly 22,000x

This is the core "stream and filter" claim: gharc never holds the full hour
on disk after processing it, so peak disk stays bounded by the largest
in-flight temp file rather than by the total downloaded volume.
