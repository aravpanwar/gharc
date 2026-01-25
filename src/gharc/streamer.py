# src/gharc/streamer.py
import requests
import gzip
import json
import concurrent.futures
from datetime import datetime
from .utils import get_url_for_time, date_range, logger
from .filters import passes_filters, fast_string_check
from .storage import DataWriter

def process_single_hour(dt: datetime, repos: list, event_types: list) -> list:
    """Streams one hour of data and returns filtered records."""
    url = f"https://data.gharchive.org/{dt.year}-{dt.month:02d}-{dt.day:02d}-{dt.hour}.json.gz"
    results = []
    
    # Optimization tokens for fast string check
    fast_tokens = (repos if repos else []) + (event_types if event_types else [])
    
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            if r.status_code != 200:
                logger.warning(f"Skipping {url} (Status: {r.status_code})")
                return []
                
            with gzip.GzipFile(fileobj=r.raw) as f:
                for line in f:
                    try:
                        decoded = line.decode('utf-8')
                        
                        # Fast fail
                        if fast_tokens and not fast_string_check(decoded, fast_tokens):
                            continue
                            
                        # Parse
                        event = json.loads(decoded)
                        
                        # Logic check
                        if passes_filters(event, repos, event_types):
                            results.append(event)
                            
                    except (json.JSONDecodeError, Exception):
                        continue
                        
        logger.info(f"✓ Processed {dt}: Kept {len(results)} records")
        return results
        
    except Exception as e:
        logger.error(f"Failed to process {dt}: {e}")
        return []

def process_range(start, end, repos, event_types, output, workers):
    writer = DataWriter(output)
    timestamps = list(date_range(start, end))
    
    logger.info(f"Queueing {len(timestamps)} hours of data...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_time = {
            executor.submit(process_single_hour, ts, repos, event_types): ts 
            for ts in timestamps
        }
        
        for future in concurrent.futures.as_completed(future_to_time):
            data = future.result()
            for record in data:
                writer.write(record)
                
    writer.close()
    logger.info("Done! Data written to " + output)