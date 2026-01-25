---
title: 'gharc: A Stream-Processing Tool for GitHub Archive Data'
tags:
  - Python
  - GitHub
  - mining software repositories
  - big data
  - stream processing
authors:
  - name: Arav Panwar
    orcid: 0009-0009-3013-5970 # Replace with your ORCID if you have one
    affiliation: 1
affiliations:
 - name: Independent Researcher, Hyderabad, India
   index: 1
date: 25 January 2026
bibliography: paper.bib
---

# Summary

`gharc` is a command-line tool and Python library designed to democratize access to the GitHub Archive (GHArchive) dataset. It enables researchers with limited hardware resources (e.g., standard laptops) to filter, process, and analyze multi-terabyte historical datasets without requiring massive local storage or expensive cloud infrastructure. The tool implements a "stream-and-filter" architecture that processes data in-transit, saving only the relevant subset of events to disk in efficient Parquet or JSONL formats.

# Statement of Need

The GitHub Archive (GHArchive) is a critical resource for Software Engineering (SE) research, containing over a decade of granular activity data from open-source repositories. However, the sheer size of the dataset presents a significant barrier to entry. As of 2026, the full dataset exceeds several petabytes uncompressed. 

Traditional approaches to analyzing this data involve:
1.  **Bulk Downloading:** Requires tens of terabytes of local storage, which is inaccessible to many students and independent researchers.
2.  **Cloud Warehousing:** Services like Google BigQuery offer access but incur significant costs for high-volume queries, limiting their use for exploratory or unfunded research.

`gharc` addresses this gap by treating the GHArchive as a data stream rather than a static download. By combining efficient HTTP range requests, in-memory GZIP decompression, and zero-copy string filtering, `gharc` allows a user to extract specific signals (e.g., "all commits to `apache/spark` from 2020-2024") on a consumer-grade laptop with a standard internet connection. This lowers the barrier for "Moonshot" scale analysis in the open-source ecosystem.

# Features

* **Stream-Processing Engine:** Downloads, processes, and discards data chunks in memory, ensuring storage usage never exceeds the buffer size (approx. 100MB).
* **Resilience:** Implements robust retry logic with exponential backoff and resumable downloads to handle unstable network connections typical of residential internet.
* **Format Efficiency:** Direct-to-Parquet writing capability reduces output file size by approximately 90% compared to raw JSON, enabling faster downstream analysis.
* **Research Ready:** Provides a clean Python API for integration into reproducible data pipelines.

# Acknowledgements

We acknowledge the maintainers of the GHArchive project for providing the public dataset that makes this tool necessary.
