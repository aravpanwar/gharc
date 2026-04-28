# gharc: GitHub Archive Stream-Processor

[![PyPI](https://img.shields.io/pypi/v/gharc.svg)](https://pypi.org/project/gharc/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/aravpanwar/gharc/actions/workflows/test.yml/badge.svg)](https://github.com/aravpanwar/gharc/actions)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![DOI](https://zenodo.org/badge/1112791047.svg)](https://doi.org/10.5281/zenodo.19814232)

**Mine the GitHub Archive on a standard laptop.**

`gharc` is a command-line tool and Python library that filters the [GitHub Archive](https://www.gharchive.org/) dataset on consumer hardware. Each hourly archive is streamed through memory, filtered against your criteria, and written out as Parquet or JSONL. Peak local storage stays bounded by a single in-flight download (about 150 MB) regardless of how long a window you process.

---

## Why gharc?

The full GitHub Archive dataset exceeds petabytes in size. Traditional analysis requires either massive local storage or expensive cloud warehousing (BigQuery).

`gharc` solves this by implementing a **Stream-and-Filter** architecture:
1.  **Streaming:** Downloads each hourly archive (~60 to 150 MB compressed in 2024) to a temporary file.
2.  **Filtering:** Extracts only events matching your criteria (e.g., specific repos or event types).
3.  **Writing:** Streams matching events into a single **Parquet** or **JSONL** file via `pyarrow.ParquetWriter` for true append.
4.  **Cleanup:** Deletes the temporary download immediately after, so disk usage never accumulates.

**Ideal for:**
- Academic research on Open Source Software (OSS).
- Large scale data mining on consumer hardware.
- Creating custom datasets for specific organizations or ecosystems.

![Architecture: GHArchive HTTPS to thread pool to resumable download to temp file to streaming decode and filter to DataWriter to output file.](paper/figures/architecture.png)

---

## Key Features

* **Zero-Storage Overhead:** Processes terabytes of data with a constant disk footprint of <100MB.
* **Resumable Downloads:** Smart handling of network interruptions (common with residential internet) using HTTP Range requests.
* **High Performance:**
    * Parallel processing with thread pools.
    * Optimized "Fast String Check" (zero-copy filtering) to skip irrelevant data.
    * Optional `orjson` support for 3-5x faster parsing.
* **Parquet Native:** Outputs columnar data ready for Pandas, Spark, or Polars, often reducing file size by 90% compared to JSON.

---

## Performance

Measured on a Windows 11 laptop (12 logical cores, 15 GB RAM) over a typical residential connection. Reproducible scripts in [`benchmarks/`](benchmarks/).

A six-hour window of GHArchive (2024-01-01 00:00 to 06:00 UTC), filtered to `apache/spark`:

| Workers | Wall-clock | Hours/sec | Spark events | Peak RSS |
|---|---|---|---|---|
| 1 | 76.0 s | 0.079 | 14 | 94.2 MB |
| 4 | 58.1 s | 0.103 | 14 | 106.7 MB |

Both runs recovered the same events, so concurrency does not affect output. Peak RSS stays below 110 MB. The bottleneck on residential links is HTTPS download throughput rather than CPU; additional workers help up to a point and then saturate the connection.

The same six-hour window comprises about 1.2 GB of compressed source on the GHArchive side, while the filtered Parquet output is 53 KB. That is a storage saving of roughly 22,000 to 1, and at no point does peak local disk exceed the size of a single in-flight temporary file (about 150 MB).

---

## Installation

### Prerequisites
- Python 3.8 or higher
- `pip`

### Install from PyPI

```bash
pip install gharc
```

### Install from Source

```bash
git clone https://github.com/aravpanwar/gharc.git
cd gharc
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### Optional Performance Boost

For maximum speed, install with the `fast` extra. `gharc` detects and uses `orjson` automatically when available.

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
| `--start` | Start date, inclusive (YYYY-MM-DD or YYYY-MM-DD-HH) | `2024-01-01` |
| `--end` | End date, exclusive (YYYY-MM-DD or YYYY-MM-DD-HH) | `2024-02-01` |
| `--repos` | Comma-separated list of repositories to keep | `apache/spark,tensorflow/tensorflow` |
| `--event-types` | Comma-separated list of GHArchive event types | `WatchEvent,ForkEvent` |
| `--output` | Output filename (`.parquet` or `.jsonl`) | `data.parquet` |
| `--workers` | Number of parallel download threads (default: 4) | `8` |

---

## Resumable runs

For long jobs, `gharc` keeps a small `<output>.state.json` next to the output file listing which hours it has already processed. If the run crashes, restarting the same command picks up where it left off rather than redoing completed hours. The state file is removed automatically when the run finishes cleanly.

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

`__all__` in `gharc/__init__.py` lists the public surface (`process_range`, `jsonl_to_parquet`, `DataWriter`, `parse_date`, `date_range`, `get_url_for_time`, `setup_logging`, plus the filter helpers).

---

##  Automating Bulk Downloads

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
├── paper/            # paper.md, paper.bib, figures (the JOSS submission)
└── CITATION.cff      # GitHub-detectable citation metadata
```

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on the process for submitting pull requests.

**Running Tests:**

```bash
pip install -e ".[test]"
pytest tests/
```

---

## Citation

The accompanying paper is at [`paper/paper.pdf`](paper/paper.pdf) and is rebuilt automatically on every push by the [Paper CI workflow](.github/workflows/paper.yml).

If you use `gharc` in your research, please cite it using the metadata in `CITATION.cff` or as follows:

```bibtex
@software{gharc2026,
  author = {Panwar, Arav},
  title = {gharc: A stream-and-filter tool for the GitHub Archive on consumer hardware},
  year = {2026},
  url = {https://github.com/aravpanwar/gharc}
}

```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

Created by Arav Panwar
[aravpanwar.com](https://www.aravpanwar.com)

