# Changelog

All notable changes to gharc are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- README claims are scoped to what has been measured. The intro describes
  the stream-and-filter route and its intended users instead of a marketing
  pitch, the bounded-disk bullet no longer implies terabyte-scale runs have
  been performed, and the unmeasured Parquet size comparison is gone.

## [0.1.4] - 2026-06-28

### Added
- Owner wildcards in `--repos` (for example `apache/*`), plus `--orgs` and
  `--actors` filters. `--repos` and `--orgs` are combined, and `--event-types`
  and `--actors` further narrow the result.
- `--version` prints the installed version, and `--debug` turns on verbose
  logging (including a full traceback on error).

### Changed
- Ctrl+C now stops a run promptly by cancelling the hours that have not
  started, instead of draining the whole queue first. The checkpoint is kept
  so a rerun resumes.
- JSONL resume is now exactly-once: each completed hour records the output
  byte offset, and a resume trims any rows left by an interrupted hour rather
  than appending them again. A resume also stops with an error if the output
  is shorter than its checkpoint (truncated or deleted).
- JSONL output is written as UTF-8 without escaping non-ASCII characters,
  matching the Parquet output and keeping non-English text readable.
- `download` rejects a `--start` in the future and warns when `--end` is very
  recent, and it reports how many hours in the window had no published archive.
- `download` warns when a window starts before 2015-01-01 and a repository or
  owner filter is set, since GHArchive uses the older Timeline schema there.
- Empty filter tokens (as in `apache/spark,,foo`) are dropped, and `--workers`
  must be at least 1.
- The package no longer depends on pandas; Parquet tables are built directly
  with pyarrow.

## [0.1.3] - 2026-06-27

### Fixed
- Parquet output no longer drops events or leaves a half-written file when
  a run mixes events with and without the optional top-level `org` field
  (events from org-owned versus user-owned repos). The writer and the
  JSONL converter now pin an explicit schema covering the canonical
  GHArchive top-level fields instead of inferring one from the first batch.
  This corrects the 0.1.2 note, which described the old first-batch
  behaviour as safe; in multi-hour runs it was not.
- A run that errors on one or more hours now exits non-zero and keeps its
  state file, so the failure is visible and a rerun retries only the
  failed hours. Previously such a run still reported a clean finish.
- A run that matches no events writes a valid empty output (a 0-row
  Parquet file or an empty JSONL file) rather than no file at all.
- `download` rejects a `--start` that is not before `--end` instead of
  silently doing nothing.

### Changed
- The bundled `examples/orchestrator.py` downloads JSONL per month and
  converts to Parquet, so a crashed month can resume.

## [0.1.2] - 2026-04-28

### Changed
- Minimum supported Python is now 3.10. The 3.8 and 3.9 series are both
  upstream EOL. CI runs on 3.10, 3.11, and 3.12.
- `_RunState` no longer requires callers to reach into a private attribute
  to check for resume state. `len(state)` returns the number of completed
  hours.
- CLI help strings for `--start` and `--end` now mention both
  `YYYY-MM-DD` and `YYYY-MM-DD-HH` formats and that `--end` is exclusive,
  matching the README.
- The schema-drift comment in `DataWriter.flush` describes
  `cast(safe=False)` behavior accurately: it allows lossy type coercions
  on shared columns, does not drop rows, and raises if a later batch
  introduces a column the first batch's schema lacks.
- Cloud-warehouse framing in the paper and README no longer makes
  unprovable cost claims; the relevant friction is the cloud billing
  account requirement.
- Paper's case study trimmed to a motivating-use-case paragraph; the
  quantitative findings of the prior Spark study live in that study,
  not here.
- Paper's Performance section notes that throughput numbers depend on
  filter selectivity (tight filter rejects most lines before JSON parse;
  wider filters shift the bottleneck toward parsing).

### Added
- Limitations paragraph in the paper covering network bound, scope
  (filter not query), pre-2015 schema break, and JSONL-only resume.
- Windows PowerShell venv activation in the README's source install
  section.
- A pointer under the basic usage example noting that long runs should
  use JSONL for crash-safe resume.

### Documentation
- Public API now has docstrings: `process_range`, `DataWriter` (class plus
  `write`, `flush`, `close`).
- This file (`CHANGELOG.md`) added.

## [0.1.1] - 2026-04-28

### Added
- `_RunState`: hour-level checkpoint that lets a crashed run resume by
  reading `<output>.state.json` next to the output file. The state file
  records a fingerprint of the run (window plus filters) and is removed
  on clean completion.
- `gharc.jsonl_to_parquet` and `gharc convert <jsonl> <parquet>` CLI
  subcommand for converting a JSONL output to a single Parquet file.
- Python API example in the README.
- `setuptools-scm` derives the package version from the git tag, so the
  installed `gharc.__version__` matches the release.
- `Release` GitHub Actions workflow that builds and publishes to PyPI on
  every published GitHub release via OIDC trusted publishing.

### Changed
- `process_range` flushes the writer after each completed hour, so the
  data for that hour is durable on disk before the hour is marked done in
  the state file.
- `DataWriter` accepts an `append` flag; combined with the resume path,
  this preserves prior JSONL content on restart.
- Improved error logging in `streamer.py`: download failures and HTTP
  status codes are logged at debug level rather than swallowed silently;
  the user-visible failure message includes the URL.

## [0.1.0] - 2026-04-26

### Added
- Initial release.
- `gharc download` CLI that streams hourly GHArchive files, applies
  repository and event-type filters, and writes Parquet or JSONL.
- Per-thread `requests` session for connection pooling across hours.
- Fast byte-level token check before JSON parsing to skip irrelevant
  lines.
- ParquetWriter-based streaming append with JSON-stringified nested
  fields for stable schema across heterogeneous event types.
- Reproducible benchmarks under `benchmarks/`.
- JOSS-style paper draft under `paper/`.
- MIT license, CITATION.cff, Zenodo deposit.

[0.1.4]: https://github.com/aravpanwar/gharc/releases/tag/v0.1.4
[0.1.3]: https://github.com/aravpanwar/gharc/releases/tag/v0.1.3
[0.1.2]: https://github.com/aravpanwar/gharc/releases/tag/v0.1.2
[0.1.1]: https://github.com/aravpanwar/gharc/releases/tag/v0.1.1
[0.1.0]: https://github.com/aravpanwar/gharc/releases/tag/v0.1.0
