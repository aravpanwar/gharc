# gharc: GitHub Archive Stream-Processor

[![PyPI](https://img.shields.io/pypi/v/gharc.svg)](https://pypi.org/project/gharc/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/aravpanwar/gharc/actions/workflows/test.yml/badge.svg)](https://github.com/aravpanwar/gharc/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![DOI](https://zenodo.org/badge/1112791047.svg)](https://doi.org/10.5281/zenodo.19814232)

**Pull filtered slices of the GitHub Archive on a laptop, without holding raw hours on disk.**

`gharc` is a command-line tool and Python library that filters the [GitHub Archive](https://www.gharchive.org/) dataset. Each hourly archive is streamed through memory, filtered against your criteria, and written out as Parquet or JSONL. Peak local storage stays bounded by the downloads in flight at once, one temporary file per worker (each hourly archive is roughly 60 to 150 MB in 2024), so disk use scales with `--workers` rather than with how long a window you process.

---

## Why gharc?

The full GitHub Archive spans every public event since 2011: tens of terabytes compressed, and several petabytes uncompressed. Most studies need only a small slice of it, but the archive has no server-side filtering, so the usual options are downloading whole hours to local disk or querying a cloud-warehouse mirror (BigQuery, Snowflake).

`gharc` takes a third route and filters during the download:
1.  **Streaming:** Downloads each hourly archive (~60 to 150 MB compressed in 2024) to a temporary file.
2.  **Filtering:** Keeps only the events matching your filters (repositories, owners, actors, event types).
3.  **Writing:** Appends the matches to a single **Parquet** file (through `pyarrow.ParquetWriter`) or **JSONL** file.
4.  **Cleanup:** Deletes the temporary download before moving to the next hour, so disk usage never accumulates.

It is meant for researchers and students who need event-level GitHub data over long windows but do not have a warehouse account or the disk to hold raw months.

![Architecture: GHArchive HTTPS to thread pool to resumable download to temp file to streaming decode and filter to DataWriter to output file.](docs/architecture.png)

---

## Key Features

* **Bounded disk:** Peak local storage is the downloads in flight, one temporary file per worker (roughly 225 to 290 MB at the default 4 workers, about 85 MB with a single worker), and it does not grow with the length of the window. For selective filters the working memory stays under about 100 MB (52 to 70 MB in the latest benchmarks); a very wide or empty filter buffers more of each hour and uses more.
* **Resumable downloads:** Recovers from network interruptions (common on residential connections) using HTTP Range requests.
* **Parallel processing:** Hours in the range are downloaded and filtered across a thread pool.
* **Filtering before parsing:** A byte-level token check rejects lines that cannot match before any JSON parsing. A line has to contain a token from each kind of filter you set (repositories and owners count as one), so pairing a repository with a common event type stays selective. With a selective filter most lines never reach the parser; a wide or empty filter gains nothing from this.
* **Optional orjson:** Uses `orjson` for JSON parsing when it is installed, which is faster than the standard library parser.
* **Parquet output:** Writes columnar data that loads directly into pandas, Polars, or Spark. JSONL output is available for resumable runs and line-oriented tools.

---

## Performance

Measured on 2026-11-18 at v0.2.0 on a Windows 11 laptop (12 logical cores, 16 GB RAM) over a typical residential connection. Reproducible scripts and the full results, including a same-night comparison with v0.1.5, are in [`benchmarks/`](benchmarks/RESULTS.md).

A six-hour window of GHArchive (2024-01-01 00:00 to 06:00 UTC), filtered to `apache/spark` (mean of two runs):

| Workers | Wall-clock | Hours/sec | Spark events | Peak RSS |
|---|---|---|---|---|
| 1 | 52.7 s | 0.114 | 14 | 52.6 MB |
| 4 | 42.1 s | 0.143 | 14 | 70.2 MB |

Every run recovered the same events, so concurrency does not affect output. Peak RSS stays well under 100 MB. The bottleneck on residential links is HTTPS download throughput rather than CPU; additional workers help up to a point and then saturate the connection, which on a slow night (as here) leaves four workers only about 1.3x ahead of one.

Across the same six-hour window gharc streams about 416 MB of compressed source from GHArchive (six hourly files of roughly 60 to 85 MB each) but never retains it. The full source is still transferred, so this is not a bandwidth saving; what stays bounded is local disk. Peak disk is held to the temporary files in flight, one per worker: about 85 MB with a single worker and roughly 225 to 290 MB at the default four workers, depending on which hours overlap. The filtered Parquet output for `apache/spark` over that window is 62 KB, and local disk does not grow with the length of the window processed.

At full scale: a six-month window (January to June 2024, 4,368 hourly files, roughly 350 GB of compressed source) filtered to `apache/spark` completed in 11 h 16 min on the same laptop over a residential connection with gharc 0.1.4, with peak temporary disk of 565 MB and a 112 MB Parquet output. Peak in-flight disk runs higher than the six-hour benchmark suggests because hourly file sizes vary widely by time of day. The full reproduction, including a comparison against the study it reproduces, is at [Spark_Codebase_Evolution](https://github.com/aravpanwar/Spark_Codebase_Evolution/tree/main/redo).

Re-running the first four months of that window (2,904 hourly files) at v0.2.0 recovered exactly the same number of events in every month, 28,049 in total, in 6 h 49 min with peak temporary disk of 576 MB. The month-by-month comparison is in [`benchmarks/RESULTS.md`](benchmarks/RESULTS.md#four-month-re-validation).

---

## Installation

### Prerequisites
- Python 3.10 or higher
- `pip`

### Install from PyPI

```bash
pip install gharc
```

### Install from Source

```bash
git clone https://github.com/aravpanwar/gharc.git
cd gharc
python -m venv venv
# macOS / Linux:
source venv/bin/activate
# Windows PowerShell:
#   .\venv\Scripts\Activate.ps1
pip install -e .
```

### Optional: faster JSON parsing

`gharc` uses `orjson` instead of the standard library parser when it is installed. The `fast` extra pulls it in:

```bash
pip install "gharc[fast]"
```

---

## Usage

### Basic Command

Download all activity for a specific repository over a one-day window.
Note that `--end` is exclusive, so this covers all 24 hours of 2024-01-01.

```bash
gharc download \
    --start 2024-01-01 \
    --end 2024-01-02 \
    --repos "apache/spark" \
    --output spark_data.parquet

```

For multi-hour or multi-day runs, prefer `--output run.jsonl` so the run can resume from where it left off if it crashes; convert to Parquet at the end with `gharc convert run.jsonl run.parquet`. See [Resumable runs](#resumable-runs) below for details.

A three-hour run with JSONL output, then the conversion to Parquet:

![Terminal capture: gharc download of three hours of apache/spark pull request and comment events with three workers, a progress bar reaching 3 of 3 hours, then gharc convert reporting 13 rows written to spark.parquet.](docs/cli-download.svg)

### Advanced Filtering

Filter for multiple repositories and specific event types (e.g., only Pull Requests and Pushes).
This covers all of June 2023 (June 1 inclusive through July 1 exclusive).

```bash
gharc download \
    --start 2023-06-01 \
    --end 2023-07-01 \
    --repos "apache/spark, pandas-dev/pandas, pytorch/pytorch" \
    --event-types "PullRequestEvent, PushEvent" \
    --output oss_summer_2023.parquet \
    --workers 4

```

### Arguments

| Argument | Description | Example |
| --- | --- | --- |
| `--start` | Start date in UTC, inclusive (YYYY-MM-DD or YYYY-MM-DD-HH) | `2024-01-01` |
| `--end` | End date in UTC, exclusive (YYYY-MM-DD or YYYY-MM-DD-HH) | `2024-02-01` |
| `--repos` | Comma-separated repositories to keep; supports `owner/*` wildcards | `apache/spark,apache/*` |
| `--orgs` | Comma-separated repository owners to keep | `apache,pandas-dev` |
| `--actors` | Comma-separated actor logins to keep | `gustav-victor,mira-holt` |
| `--event-types` | Comma-separated list of GHArchive event types | `WatchEvent,ForkEvent` |
| `--output` | Output filename (`.parquet` or `.jsonl`) | `data.parquet` |
| `--workers` | Number of parallel download threads (default: 4) | `8` |

Dates are interpreted as UTC, matching GHArchive's hourly file naming.

Repository names are matched exactly and are case-sensitive, so pass the canonical `owner/name` as it appears on GitHub (for example `apache/spark`). Use `apache/*` or `--orgs apache` to keep every repository under an owner. `--repos` and `--orgs` are combined (an event is kept if it matches either), while `--event-types` and `--actors` further narrow the result.

Invalid arguments stop the run before anything is downloaded, with a message that says what was expected:

![Terminal capture: gharc rejecting a start date after the end date, a worker count of zero, and a convert whose input and output are the same file, each with a one-line error.](docs/cli-errors.svg)

---

## Resumable runs

For long jobs, `gharc` keeps a small `<output>.state.json` next to the output file listing which hours it has already processed. If the run crashes, restarting the same command picks up where it left off rather than redoing completed hours. The state file is written atomically (a temporary file renamed into place) so a crash mid-write cannot corrupt it, and it is removed automatically when the run finishes cleanly. Note that `gharc` relies on the operating system to flush writes to disk rather than forcing an `fsync` after each hour, so an abrupt power loss (as opposed to a process crash) could in rare cases leave an hour marked done whose data had not yet reached disk.

Resume support requires JSONL output. Parquet writers cannot append to a closed file, so for multi-hour runs use `--output run.jsonl` and convert to Parquet at the end:

```bash
gharc convert run.jsonl run.parquet
```

---

## Python API

The CLI is a thin wrapper around `gharc.process_range`, which you can call directly:

```python
from datetime import datetime
import gharc

gharc.setup_logging()
gharc.process_range(
    start=datetime(2024, 1, 1),
    end=datetime(2024, 1, 2),
    repos=["apache/spark"],
    event_types=None,
    output="spark_one_day.jsonl",
    workers=4,
)

gharc.jsonl_to_parquet("spark_one_day.jsonl", "spark_one_day.parquet")
```

`process_range` also accepts `orgs` and `actors` keyword arguments mirroring the `--orgs` and `--actors` CLI flags, and entries in `repos` may use `owner/*` wildcards, so `repos=["apache/*"]` keeps every repository under an owner.

`__all__` in `gharc/__init__.py` lists the public surface (`process_range`, `jsonl_to_parquet`, `DataWriter`, `parse_date`, `date_range`, `get_url_for_time`, `setup_logging`, plus the filter helpers).

The nested event fields (`actor`, `repo`, `payload`, `org`) are stored as JSON strings, so the output loads directly into pandas, Polars or Spark and the nested parts parse with `json.loads`:

![Terminal capture: a short pandas script reading spark.parquet, pulling the action out of each payload, and printing the first six events and a count of 13 events by type.](docs/cli-pandas.svg)

---

## Automating Bulk Downloads

For long date ranges, the included [`examples/orchestrator.py`](examples/orchestrator.py) script runs `gharc` month by month so each year produces one Parquet file per month rather than one giant output:

```bash
python examples/orchestrator.py \
    --start 2023-01-01 \
    --end 2024-01-01 \
    --repos "apache/spark,pandas-dev/pandas" \
    --output-dir ./gharc_out \
    --workers 4
```

---

## Repository Layout

```
gharc/
├── src/gharc/        # Library + CLI entry point
├── tests/            # pytest test suite
├── benchmarks/       # Reproducible runs that back the performance claims
├── examples/         # Driver scripts (e.g. month-by-month orchestrator)
├── docs/             # Architecture figure and the README's terminal captures
└── CITATION.cff      # GitHub-detectable citation metadata
```

---

## Support and maintenance

`gharc` is maintained by one person, Arav Panwar. Questions and bug reports go to the [issue tracker](https://github.com/aravpanwar/gharc/issues); for a bug, include the command you ran and the output with `--debug`, which prints the full traceback. Problems that could leave downloaded data wrong or incomplete are fixed first.

Releases follow [Semantic Versioning](https://semver.org/). Every release is listed in the [changelog](CHANGELOG.md), published to PyPI, and archived on Zenodo with its own DOI.

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on the process for submitting pull requests.

**Running Tests:**

```bash
pip install -e ".[test,fast]"
pytest tests/
```

---

## Citation

If you use `gharc` in your research, please cite it using the metadata in `CITATION.cff` or as follows:

```bibtex
@software{gharc2026,
  author = {Panwar, Arav},
  title = {gharc: A stream-and-filter tool for the GitHub Archive},
  year = {2026},
  url = {https://github.com/aravpanwar/gharc}
}

```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

