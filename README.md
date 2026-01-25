# gharc

A high-performance stream-processing tool for GitHub Archive (GHArchive) data. 

## Features
- **Stream-and-Filter**: Processes data in-memory without downloading full archives.
- **Storage Efficient**: Writes directly to Parquet or filtered JSONL.
- **Research Ready**: Easy to reproduce datasets for academic papers.

## Installation
```bash
pip install -e .
```

## Usage
```bash
gharc download --start 2024-01-01 --end 2024-01-31 --filter "repo=apache/spark"
```
