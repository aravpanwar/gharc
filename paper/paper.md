---
title: 'gharc: A stream-and-filter tool for the GitHub Archive on consumer hardware'
tags:
  - Python
  - GitHub
  - mining software repositories
  - big data
  - stream processing
authors:
  - name: Arav Panwar
    orcid: 0009-0009-3013-5970
    affiliation: 1
affiliations:
 - name: Independent Researcher, Hyderabad, India
   index: 1
date: 26 April 2026
bibliography: paper.bib
---

# Summary

`gharc` is a command-line tool and Python library that filters the GitHub Archive (GHArchive) dataset on consumer hardware. Rather than downloading hours of compressed events to local disk before processing, `gharc` streams each archive file through memory, decompresses it on the fly, applies user-specified repository and event-type filters, and writes only the matching events to Parquet or JSONL. Peak storage stays bounded by a single in-flight download (about 150 MB) regardless of the time range processed. The intended audience is software-engineering researchers, students, and small teams who do not have access to institutional warehouses or commercial cloud quotas but who need event-level GitHub data at multi-year time scales.

# Statement of need

The GitHub Archive [@gharchive] is one of the most widely used data sources in mining software repositories (MSR) research, capturing nearly every public event on GitHub since February 2011. The dataset is published as hourly gzipped JSONL files. Each hour in 2024 averages roughly 90 MB compressed and several hundred megabytes uncompressed; the full archive exceeds several petabytes uncompressed.

This scale poses a practical barrier to anyone without institutional infrastructure. Three traditional approaches each exclude part of the research community:

1. **Bulk local downloads.** Storing even a single year of GHArchive uncompressed exceeds the disk budget of most laptops. Filtering after the fact still requires the full download to be present.
2. **Cloud warehouses.** GHArchive is mirrored on Google BigQuery and Snowflake [@githubarchivebigquery]. Both are excellent for query workloads, but they require a billing account, and exploratory analyses can quickly exceed free quotas.
3. **Hosted research infrastructures.** Tools such as GHTorrent [@gousios2013ghtorrent], Boa [@dyer2013boa], and World of Code [@ma2019worldofcode] have provided shared access to GitHub-derived data, but each carries its own constraints. GHTorrent's project domain has been allowed to expire as of 2026, Boa's hosted endpoint is currently unreachable, and World of Code requires registration and remote access to dedicated servers.

`gharc` fills the laptop-friendly local-first niche. By streaming each hour's compressed archive through a small in-memory buffer and discarding it immediately after filtering, the tool keeps peak storage bounded while preserving the ability to operate on multi-year time ranges with no warehousing dependency. This is the configuration most useful to independent researchers, students, and small teams.

# Architecture

`gharc` is a stream-and-filter pipeline. The user supplies a date range, an optional list of repositories, and an optional list of event types; `gharc` constructs the GHArchive URL for each hour in the range and dispatches them to a worker thread pool.

Each worker downloads the hour's gzipped JSONL file to a temporary location with HTTP range-resume support, then iterates over the file line by line. Lines are first filtered by a fast byte-level token check before any JSON parsing, so `gharc` skips the majority of irrelevant events without paying parser cost. Matching events are JSON-parsed, validated against the full filter, and yielded to the main thread.

The main thread receives matching events from completed futures and writes them to disk through a `DataWriter` that wraps a long-lived `pyarrow.parquet.ParquetWriter` [@apachearrow] for true streaming append. Nested fields (`actor`, `repo`, `payload`, `org`) are JSON-stringified before write so the Parquet schema is stable across heterogeneous event types within the same output file. Each worker maintains its own `requests` session [@reitz2011requests] in thread-local storage so HTTP connection pooling persists across the hours that worker processes.

![Stream-and-filter architecture.\label{fig:arch}](figures/architecture.png){ width=80% }

# Performance

We measured `gharc` on a Windows 11 laptop (12 logical cores, 15 GB RAM) over a residential connection in Hyderabad, India.

A six-hour window of GHArchive (2024-01-01 00:00 to 06:00 UTC), filtered to `apache/spark`, completed in 76 seconds with a single worker and 58 seconds with four workers. Both runs recovered the same 14 events, so concurrency does not affect output correctness. Peak resident set size stayed under 110 MB in both configurations. The limiting factor on residential links is HTTPS download throughput rather than CPU; additional workers beyond a small number add little once the connection saturates.

The same six-hour window comprises approximately 1.2 GB of compressed source data on the GHArchive side; the filtered Parquet output for `apache/spark` is 53 KB. That ratio of roughly 22,000 to 1 quantifies the storage saving from streaming-and-filtering. At no point did peak local disk exceed the size of a single in-flight temporary file (about 150 MB).

Extrapolating from these numbers, a full January to June 2024 fetch (4,380 hours of source data at about 90 MB per hour) is approximately 395 GB streamed, which is achievable in three to four evening sessions on the same hardware. The reproducible benchmark scripts are included in the repository under `benchmarks/`.

# Case study: Apache Spark, January to June 2024

The motivation for `gharc` came from a six-month analysis of Apache Spark contributor activity originally conducted as an undergraduate course mini-project [@panwar2025sparkcodebase]. That earlier study downloaded GHArchive month by month, ran a separate filter script over each month, and ultimately recovered 40,237 events from 2,384 unique contributors across the six months. Of those, nine "core" contributors accounted for 53 percent of total activity, and 57 percent of all events were code review (`PullRequestReviewEvent` and `PullRequestReviewCommentEvent`), consistent with prior characterizations of large Apache projects as review-heavy.

That month-by-month pipeline was prone to off-by-one errors in date ranges (notably a "seventh-month bleed" caused by an inclusive end bound), and it required around 100 GB of intermediate local disk during processing. `gharc` reproduces the same analysis on the same laptop with no intermediate disk pressure and a single command. A full re-fetch using `gharc` is currently in progress and will be reported in future work, alongside a comparative case study across six high-volume projects (`microsoft/vscode`, `golang/go`, `facebook/react`, `kubernetes/kubernetes`, `apache/spark`, `rust-lang/rust`) for the period 2019 to 2024.

# Related work

Several tools have addressed the GHArchive analysis problem, each with different trade-offs.

GHTorrent [@gousios2013ghtorrent] historically served as the default GitHub-mining database for MSR research and offered both periodic data dumps and a SQL-queryable mirror. As of 2026 the project's primary domain redirects to an unrelated commercial site, illustrating the maintenance fragility of long-running shared services.

PyDriller [@spadini2018pydriller] mines git repositories directly via the local git history of cloned projects. It operates at a different layer to `gharc`: PyDriller exposes commits, file diffs, and developer information from a checked-out repository, whereas `gharc` operates on the GitHub event stream (issues, pull requests, reviews, watch events, and so on). The two are complementary; an MSR study often needs both.

World of Code [@ma2019worldofcode] provides shared access to a curated cross-reference of millions of git repositories. Researchers obtain accounts and submit jobs to dedicated servers. The infrastructure is excellent for very large cross-project queries but introduces an institutional dependency.

Boa [@dyer2013boa] offers a domain-specific language for ultra-large-scale repository queries against curated datasets, again served from a hosted endpoint. At the time of writing the public endpoint at `boa.cs.iastate.edu` is unreachable.

Cloud-warehouse mirrors of GHArchive on Google BigQuery and Snowflake [@githubarchivebigquery] are highly performant but require a billing account and quota management.

`gharc` occupies the local-first, laptop-friendly niche: no shared infrastructure, no billing account, no schema-bound DSL, just the original GHArchive files streamed and filtered on demand.

# Acknowledgements

The author thanks Ilya Grigorik and the GHArchive maintainers for the public dataset on which this tool depends, and the maintainers of the `requests` [@reitz2011requests], `pandas` [@mckinney2010data], `pyarrow` [@apachearrow], `tqdm`, and `orjson` libraries that `gharc` builds on.

# References
