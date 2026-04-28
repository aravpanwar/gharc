# src/gharc/storage.py
import json
import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from .utils import logger


class DataWriter:
    def __init__(self, filename: str, append: bool = False):
        self.filename = filename
        self.is_parquet = filename.endswith('.parquet')
        self.buffer = []
        self.buffer_size = 10000
        self._pq_writer = None

        if append and self.is_parquet and os.path.exists(self.filename):
            # ParquetWriter cannot append to a closed Parquet file. For long
            # crash-safe runs use JSONL; convert to Parquet at the end.
            raise ValueError(
                f"Cannot resume into existing Parquet file {filename}. "
                f"Use JSONL output for resumable runs and convert at the end."
            )

        if not append and os.path.exists(self.filename):
            os.remove(self.filename)

    def write(self, record: dict):
        self.buffer.append(record)
        if len(self.buffer) >= self.buffer_size:
            self.flush()

    def flush(self):
        if not self.buffer:
            return

        if self.is_parquet:
            rows = [_flatten_event(e) for e in self.buffer]
            df = pd.DataFrame(rows)
            table = pa.Table.from_pandas(df, preserve_index=False)

            if self._pq_writer is None:
                self._pq_writer = pq.ParquetWriter(
                    self.filename,
                    schema=table.schema,
                    compression='snappy',
                )
            else:
                # Cast to the schema we opened with; event payloads vary in shape.
                table = table.cast(self._pq_writer.schema, safe=False)

            self._pq_writer.write_table(table)
        else:
            with open(self.filename, 'a', encoding='utf-8') as f:
                for rec in self.buffer:
                    f.write(json.dumps(rec) + '\n')

        self.buffer = []

    def close(self):
        self.flush()
        if self._pq_writer is not None:
            self._pq_writer.close()
            self._pq_writer = None
        logger.info(f"Wrote output to {self.filename}")


def _flatten_event(event: dict) -> dict:
    # JSON-stringify nested fields so Parquet sees a stable flat schema.
    out = {}
    for key, value in event.items():
        if isinstance(value, (dict, list)):
            out[key] = json.dumps(value, ensure_ascii=False)
        else:
            out[key] = value
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
        rows = [_flatten_event(e) for e in buffer]
        df = pd.DataFrame(rows)
        table = pa.Table.from_pandas(df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(
                output_path,
                schema=table.schema,
                compression='snappy',
            )
        else:
            table = table.cast(writer.schema, safe=False)
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

    logger.info(f"Converted {rows_written:,} rows from {input_path} to {output_path}")
    return rows_written
