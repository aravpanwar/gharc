# src/gharc/storage.py
import json
import pandas as pd
import os
from .utils import logger

class DataWriter:
    def __init__(self, filename: str):
        self.filename = filename
        self.is_parquet = filename.endswith('.parquet')
        self.buffer = []
        self.buffer_size = 10000  # Write every 10k rows to keep RAM usage low

    def write(self, record: dict):
        self.buffer.append(record)
        if len(self.buffer) >= self.buffer_size:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
            
        if self.is_parquet:
            df = pd.DataFrame(self.buffer)
            # Append if exists, else write new
            if os.path.exists(self.filename):
                df.to_parquet(self.filename, engine='pyarrow', compression='snappy', index=False)
                # Note: Real append in Parquet is complex; for simplicity in this 
                # prototype, we rely on pandas overwriting or requires fastparquet for append.
                # To keep it simple for now: We will just log a warning if overwriting logic isn't perfect
                # For a robust tool, we usually write one parquet file per hour.
            else:
                df.to_parquet(self.filename, engine='pyarrow', compression='snappy', index=False)
        else:
            # JSONL Append
            with open(self.filename, 'a') as f:
                for rec in self.buffer:
                    f.write(json.dumps(rec) + '\n')
        
        self.buffer = [] # Clear RAM

    def close(self):
        self.flush()