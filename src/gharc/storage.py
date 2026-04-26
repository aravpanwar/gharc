# src/gharc/storage.py
import json
import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from .utils import logger


class DataWriter:
    def __init__(self, filename: str):
        self.filename = filename
        self.is_parquet = filename.endswith('.parquet')
        self.buffer = []
        self.buffer_size = 10000
        self._pq_writer = None

        if os.path.exists(self.filename):
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
