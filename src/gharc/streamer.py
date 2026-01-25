# src/gharc/streamer.py
import requests
import gzip
import json
import concurrent.futures
import time
import os
import tempfile
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .utils import get_url_for_time, date_range, logger
from .filters import passes_filters, fast_string_check
from .storage import DataWriter

def get_robust_session():
    """Creates a requests session with retry logic."""
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def download_resumable(url: str, temp_path: str, session: requests.Session) -> bool:
    """
    Downloads a file with resume capability.
    If the file partially exists, it requests only the missing bytes.
    """
    # Check if we have partial data
    resume_header = {}
    mode = 'wb'
    if os.path.exists(temp_path):
        current_size = os.path.getsize(temp_path)
        if current_size > 0:
            resume_header = {'Range': f'bytes={current_size}-'}
            mode = 'ab' # Append mode
            logger.info(f"   ↳ Resuming download from {current_size/(1024*1024):.1f} MB")

    try:
        with session.get(url, headers=resume_header, stream=True, timeout=(30, 120)) as r:
            # 206 = Partial Content (Resume successful)
            # 200 = OK (Server ignored range, sent full file)
            # 416 = Range Not Satisfiable (File already done?)
            
            if r.status_code == 416:
                return True # Assume we have the whole file
                
            if r.status_code not in [200, 206]:
                logger.warning(f"Bad status code {r.status_code} for {url}")
                return False

            # If server sent 200 OK despite our Range request, we must overwrite (not append)
            if r.status_code == 200 and mode == 'ab':
                mode = 'wb'
                
            with open(temp_path, mode) as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk: 
                        f.write(chunk)
        return True
    except Exception as e:
        logger.warning(f"   ↳ Chunk interrupted: {str(e)[:100]}...")
        return False

def process_single_hour(dt: datetime, repos: list, event_types: list) -> list:
    """
    Downloads with resume -> Process -> Delete.
    """
    url = get_url_for_time(dt)
    results = []
    fast_tokens = (repos if repos else []) + (event_types if event_types else [])
    session = get_robust_session()
    
    # Unique temp file
    fd, temp_path = tempfile.mkstemp(suffix=".json.gz")
    os.close(fd)
    
    download_success = False
    
    try:
        # Try up to 10 times because we can resume (cheap retries)
        for attempt in range(10):
            if download_resumable(url, temp_path, session):
                download_success = True
                break
            time.sleep(2) # Brief cooldown
            
        if not download_success:
            logger.error(f"❌ Failed to download {dt} after 10 attempts.")
            return []

        # Process
        try:
            with gzip.open(temp_path, 'rb') as f:
                for line in f:
                    try:
                        decoded = line.decode('utf-8')
                        if fast_tokens and not fast_string_check(decoded, fast_tokens):
                            continue
                        event = json.loads(decoded)
                        if passes_filters(event, repos, event_types):
                            results.append(event)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception as e:
             logger.error(f"Error reading gzip for {dt} (File might be corrupt): {e}")

        logger.info(f"✓ Processed {dt}: Kept {len(results)} records")
        return results

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def process_range(start, end, repos, event_types, output, workers):
    writer = DataWriter(output)
    timestamps = list(date_range(start, end))
    
    logger.info(f"Queueing {len(timestamps)} hours of data...")
    
    # 4 workers is safe now because we handle drops gracefully
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_time = {
            executor.submit(process_single_hour, ts, repos, event_types): ts 
            for ts in timestamps
        }
        
        for future in concurrent.futures.as_completed(future_to_time):
            ts = future_to_time[future]
            data = future.result()
            if data:
                for record in data:
                    writer.write(record)
                
    writer.close()
    logger.info("Done! Data written to " + output)