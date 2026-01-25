# gharc: GitHub Archive Stream-Processor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/YOUR_USERNAME/gharc/actions/workflows/test.yml/badge.svg)](https://github.com/YOUR_USERNAME/gharc/actions)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**Process 10TB of GitHub history on a standard laptop.**

`gharc` is a command-line tool and Python library that allows researchers to filter, process, and analyze the massive [GitHub Archive](https://www.gharchive.org/) dataset without requiring terabytes of local storage. It streams data directly from the source, filters it in-memory, and saves only the signal you care about.

---

## Why gharc?

The full GitHub Archive dataset exceeds petabytes in size. Traditional analysis requires either massive local storage or expensive cloud warehousing (BigQuery).

`gharc` solves this by implementing a **Stream-and-Filter** architecture:
1.  **Streaming:** Downloads compressed chunks to a temporary buffer (~50MB).
2.  **Filtering:** Extracts only events matching your criteria (e.g., specific repos or users).
3.  **Indexing:** writes highly compressed **Parquet** or **JSONL** files.
4.  **Cleanup:** Immediately deletes the raw chunk, ensuring disk usage never spikes.

**Ideal for:**
- Academic research on Open Source Software (OSS).
- Large scale data mining on consumer hardware.
- Creating custom datasets for specific organizations or ecosystems.

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

## Installation

### Prerequisites
- Python 3.8 or higher
- `pip`

### Install from Source
```bash
git clone [https://github.com/YOUR_USERNAME/gharc.git](https://github.com/YOUR_USERNAME/gharc.git)
cd gharc
python3 -m venv venv
source venv/bin/activate
pip install -e .

```

### Optional Performance Boost

For maximum speed, install `orjson`. `gharc` will automatically detect and use it.

```bash
pip install orjson

```

---

## Usage

### Basic Command

Download all activity for a specific repository during a specific time range.

```bash
gharc download \
    --start 2024-01-01-00 \
    --end 2024-01-01-23 \
    --repos "apache/spark" \
    --output spark_data.parquet

```

### Advanced Filtering

Filter for multiple repositories and specific event types (e.g., only Pull Requests and Pushes).

```bash
gharc download \
    --start 2023-06-01 \
    --end 2023-06-30 \
    --repos "apache/spark, pandas-dev/pandas, pytorch/pytorch" \
    --event-types "PullRequestEvent, PushEvent" \
    --output oss_summer_2023.parquet \
    --workers 4

```

### Arguments

| Argument | Description | Example |
| --- | --- | --- |
| `--start` | Start date (YYYY-MM-DD or YYYY-MM-DD-HH) | `2024-01-01` |
| `--end` | End date (YYYY-MM-DD or YYYY-MM-DD-HH) | `2024-01-31` |
| `--repos` | Comma-separated list of repositories to keep | `apache/spark,tensorflow/tensorflow` |
| `--event-types` | Comma-separated list of GHArchive event types | `WatchEvent,ForkEvent` |
| `--output` | Output filename (`.parquet` or `.jsonl`) | `data.parquet` |
| `--workers` | Number of parallel download threads (default: 4) | `8` |

---

##  Automating Bulk Downloads

For "Moonshot" datasets spanning years, use the Python API or the included orchestrator script to handle month-by-month processing.

**Example `orchestrator.py` snippet:**

```python
import subprocess
# Loop through months and process one by one to keep file sizes manageable
cmd = [
    "gharc", "download",
    "--start", "2020-01-01",
    "--end", "2020-02-01",
    "--repos", "kubernetes/kubernetes",
    "--output", "k8s_2020_01.parquet"
]
subprocess.run(cmd)

```

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](https://www.google.com/search?q=CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

**Running Tests:**

```bash
pip install pytest mock
pytest tests/

```

---

## Citation

If you use `gharc` in your research, please cite it using the metadata in `CITATION.cff` or as follows:

```bibtex
@software{gharc2026,
  author = {Panwar, Arav},
  title = {gharc: A Stream-Processing Tool for GitHub Archive Data},
  year = {2026},
  url = {[https://github.com/aravpanwar/gharc](https://github.com/aravpanwar/gharc)}
}

```

---

## License

This project is licensed under the MIT License - see the [LICENSE](https://www.google.com/search?q=LICENSE) file for details.
