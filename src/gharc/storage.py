# src/gharc/storage.py
import json
import os
import pyarrow as pa
import pyarrow.parquet as pq
from .utils import logger


# GHArchive events (GitHub Events API schema, 2015 onward) share a fixed set of
# top-level fields. The `org` field is only present for org-owned repositories,
# so it is absent from many events. We pin an explicit Parquet schema covering
# all of them rather than inferring one from the first batch written. Without
# this, a run whose first batch lacked `org` would reject every later batch that
# carried it, dropping those events or leaving a half-written file.
#
# Any top-level field outside this set is preserved as JSON in an `other`
# column rather than dropped, mirroring how the GHArchive BigQuery mirror keeps
# unrecognized fields. This keeps the Parquet output lossless and consistent
# with the JSONL output even if GitHub adds a field we do not model.
EVENT_TOP_LEVEL = [
    "id",
    "type",
    "actor",
    "repo",
    "payload",
    "public",
    "created_at",
    "org",
]

EVENT_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("type", pa.string()),
    pa.field("actor", pa.string()),
    pa.field("repo", pa.string()),
    pa.field("payload", pa.string()),
    pa.field("public", pa.bool_()),
    pa.field("created_at", pa.string()),
    pa.field("org", pa.string()),
    pa.field("other", pa.string()),
])


def _events_to_table(events: list) -> pa.Table:
    """Turn a batch of events into a Parquet-ready table with a stable schema.

    Nested fields are JSON-stringified in ``_flatten_event``, and building the
    table against ``EVENT_SCHEMA`` fills any canonical column missing from this
    batch with nulls, so every batch written to a file looks identical.
    """
    rows = [_flatten_event(e) for e in events]
    return pa.Table.from_pylist(rows, schema=EVENT_SCHEMA)


class DataWriter:
    """Buffered writer for filtered GHArchive events.

    Output format is chosen by suffix: ``.parquet`` opens a long-lived
    ``pyarrow.parquet.ParquetWriter`` and writes compressed row groups;
    anything else writes JSON lines. Records are buffered in memory and
    flushed in batches of ``buffer_size`` (default 10,000) or when ``flush()``
    is called explicitly.

    By default, constructing a DataWriter against an existing file truncates
    it. Pass ``append=True`` (used by resumable runs) to keep the existing
    JSONL contents and append to them. Append into an existing Parquet file
    is rejected because ParquetWriter cannot append to a closed file.
    """

    def __init__(self, filename: str, append: bool = False):
        self.filename = filename
        self.is_parquet = filename.endswith('.parquet')
        self.buffer = []
        self.buffer_size = 10000
        self._pq_writer = None

        if not self.is_parquet and not filename.endswith('.jsonl'):
            logger.warning(
                f"Output {filename} has no .parquet or .jsonl suffix; "
                f"writing JSON lines. Use a .parquet suffix for Parquet output."
            )

        if append and self.is_parquet and os.path.exists(self.filename):
            raise ValueError(
                f"Cannot resume into existing Parquet file {filename}. "
                f"Use JSONL output for resumable runs and convert at the end."
            )

        if not append and os.path.exists(self.filename):
            os.remove(self.filename)

    def write(self, record: dict):
        """Buffer one event for later flush."""
        self.buffer.append(record)
        if len(self.buffer) >= self.buffer_size:
            self.flush()

    def flush(self):
        """Write any buffered events to disk and clear the buffer."""
        if not self.buffer:
            return

        if self.is_parquet:
            table = _events_to_table(self.buffer)

            if self._pq_writer is None:
                self._pq_writer = pq.ParquetWriter(
                    self.filename,
                    schema=EVENT_SCHEMA,
                    compression='snappy',
                )

            self._pq_writer.write_table(table)
        else:
            with open(self.filename, 'a', encoding='utf-8') as f:
                for rec in self.buffer:
                    # ensure_ascii=False keeps non-English text readable and
                    # smaller, and matches how nested fields are stored for
                    # Parquet in _flatten_event.
                    f.write(json.dumps(rec, ensure_ascii=False) + '\n')

        self.buffer = []

    def close(self):
        """Flush remaining events and close the underlying writer.

        If nothing matched the filters, still emit a valid empty output so a
        zero-match run leaves a 0-row file rather than nothing at all, which
        previously made a clean run look indistinguishable from a broken one.
        """
        self.flush()
        if self.is_parquet:
            if self._pq_writer is None:
                pq.write_table(
                    EVENT_SCHEMA.empty_table(),
                    self.filename,
                    compression='snappy',
                )
            else:
                self._pq_writer.close()
                self._pq_writer = None
        elif not os.path.exists(self.filename):
            open(self.filename, 'w', encoding='utf-8').close()
        logger.info(f"Wrote output to {self.filename}")


def _flatten_event(event: dict) -> dict:
    # JSON-stringify nested canonical fields so Parquet sees a stable flat
    # schema, and collect any unrecognized top-level fields into `other` so
    # nothing is silently dropped.
    out = {}
    other = {}
    for key, value in event.items():
        if key not in EVENT_TOP_LEVEL:
            other[key] = value
            continue
        if isinstance(value, (dict, list)):
            out[key] = json.dumps(value, ensure_ascii=False)
        else:
            out[key] = value
    out["other"] = json.dumps(other, ensure_ascii=False) if other else None
    return out


def jsonl_to_parquet(input_path: str, output_path: str, batch_size: int = 10000) -> int:
    """Stream a JSONL file into a single Parquet file.

    Reads `input_path` line by line, batches into Parquet row groups of up to
    `batch_size` rows, and writes to `output_path`. Returns the number of rows
    written. Designed to handle multi-GB inputs without loading the whole file
    into memory.
    """
    if os.path.exists(output_path):
        os.remove(output_path)

    writer = None
    buffer = []
    rows_written = 0

    def flush():
        nonlocal writer
        if not buffer:
            return
        table = _events_to_table(buffer)
        if writer is None:
            writer = pq.ParquetWriter(
                output_path,
                schema=EVENT_SCHEMA,
                compression='snappy',
            )
        writer.write_table(table)

    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    buffer.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(f"Skipping malformed JSON line in {input_path}")
                    continue
                if len(buffer) >= batch_size:
                    flush()
                    rows_written += len(buffer)
                    buffer.clear()

        if buffer:
            flush()
            rows_written += len(buffer)
    finally:
        if writer is not None:
            writer.close()

    if writer is None:
        # Input had no usable rows. Still emit a valid empty Parquet file so
        # the output exists and reads back as a 0-row table.
        pq.write_table(EVENT_SCHEMA.empty_table(), output_path, compression='snappy')

    logger.info(f"Converted {rows_written:,} rows from {input_path} to {output_path}")
    return rows_written
