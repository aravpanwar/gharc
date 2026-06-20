# src/gharc/streamer.py
import requests
import gzip
import json
import concurrent.futures
import threading
import time
import os
import tempfile
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
from .utils import get_url_for_time, date_range, logger
from .filters import passes_filters, fast_string_check
from .storage import DataWriter

# Use orjson if available for 3-5x faster parsing
try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False

_thread_local = threading.local()

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

def _session_for_thread() -> requests.Session:
    # One session per worker thread so connection pooling actually kicks in.
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = get_robust_session()
        _thread_local.session = session
    return session

def download_resumable(url: str, temp_path: str, session: requests.Session) -> bool:
    """
    Downloads a file with resume capability.
    """
    resume_header = {}
    mode = 'wb'
    if os.path.exists(temp_path):
        current_size = os.path.getsize(temp_path)
        if current_size > 0:
            resume_header = {'Range': f'bytes={current_size}-'}
            mode = 'ab'
            # Only log resume if it's significant to keep bar clean
            if current_size > 1024 * 1024: 
                tqdm.write(f"   Resuming from {current_size/(1024*1024):.1f} MB")

    try:
        with session.get(url, headers=resume_header, stream=True, timeout=(30, 120)) as r:
            if r.status_code == 416: # Range not satisfiable (file done)
                return True
            if r.status_code not in [200, 206]:
                logger.debug(f"HTTP {r.status_code} for {url}")
                return False

            if r.status_code == 200 and mode == 'ab':
                mode = 'wb'

            with open(temp_path, mode) as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception as e:
        logger.debug(f"Download attempt failed for {url}: {e}")
        return False

def process_single_hour(dt: datetime, repos: list, event_types: list) -> list:
    """
    Downloads with resume -> Process -> Delete.
    """
    url = get_url_for_time(dt)
    results = []
    # Convert filters to bytes if using orjson for speed
    if HAS_ORJSON:
        fast_tokens = [t.encode('utf-8') for t in ((repos if repos else []) + (event_types if event_types else []))]
    else:
        fast_tokens = (repos if repos else []) + (event_types if event_types else [])
        
    session = _session_for_thread()

    fd, temp_path = tempfile.mkstemp(suffix=".json.gz")
    os.close(fd)
    
    download_success = False
    
    try:
        for attempt in range(10):
            if download_resumable(url, temp_path, session):
                download_success = True
                break
            time.sleep(2)
            
        if not download_success:
            tqdm.write(f"Failed to download {url} after 10 attempts (run with debug logging for details)")
            return []

        try:
            with gzip.open(temp_path, 'rb') as f:
                for line in f:
                    try:
                        # OPTIMIZATION: Check tokens before full parse
                        # orjson returns bytes, so we don't even need to decode to utf-8 yet
                        if HAS_ORJSON:
                            if fast_tokens:
                                # Simple byte-level check (very fast)
                                if not any(t in line for t in fast_tokens):
                                    continue
                            event = orjson.loads(line)
                        else:
                            # Standard Fallback
                            decoded = line.decode('utf-8')
                            if fast_tokens and not fast_string_check(decoded, fast_tokens):
                                continue
                            event = json.loads(decoded)

                        if passes_filters(event, repos, event_types):
                            results.append(event)
                    except Exception:
                        # GHArchive occasionally has malformed lines; expected at low rates.
                        continue
        except Exception as e:
             tqdm.write(f"Error reading gzip for {url}: {e}")

        return results

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

class _RunState:
    """Tracks which hours have been completed so a crashed run can resume.

    State lives next to the output file as <output>.state.json. The fingerprint
    of the run (window + filters) is stored alongside the done-hour list, so
    re-running with different filters against the same output triggers a clear
    error rather than silently mixing data.
    """

    def __init__(self, output_path, fingerprint):
        self._path = str(output_path) + ".state.json"
        self._fingerprint = fingerprint
        self._done = set()
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.warning(f"State file {self._path} unreadable, starting fresh")
                return
            if payload.get("fingerprint") != fingerprint:
                raise ValueError(
                    f"State file {self._path} was written for a different run "
                    f"(window or filters changed). Remove it or use a new --output."
                )
            self._done = set(payload.get("done_hours", []))

    def __len__(self):
        return len(self._done)

    def is_done(self, ts):
        return ts.isoformat() in self._done

    def mark_done(self, ts):
        self._done.add(ts.isoformat())
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(
                {"fingerprint": self._fingerprint, "done_hours": sorted(self._done)},
                f,
            )

    def clear(self):
        if os.path.exists(self._path):
            os.remove(self._path)


def _run_fingerprint(start, end, repos, event_types):
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "repos": sorted(repos) if repos else None,
        "event_types": sorted(event_types) if event_types else None,
    }


def process_range(start, end, repos, event_types, output, workers):
    """Stream-and-filter GHArchive over [start, end) and write matching events.

    Hours in the range are dispatched to a thread pool. Each worker downloads
    the corresponding GHArchive file, applies the repo and event-type filters,
    and returns matching events. The main thread writes them through a
    DataWriter (Parquet via streaming append, or JSONL).

    Crash safety: a `<output>.state.json` file records which hours have
    finished. Restarting the same command picks up where it left off. The
    state file is removed on clean completion. Resume into an existing
    Parquet output is rejected because Parquet writers cannot append to a
    closed file; use JSONL for runs that may need to be resumed and convert
    afterwards with ``gharc convert``.

    Args:
        start: Inclusive start datetime (rounded to the hour).
        end: Exclusive end datetime (rounded to the hour).
        repos: Optional list of ``owner/name`` repository filters; ``None``
            keeps all repos.
        event_types: Optional list of GHArchive event-type filters
            (e.g. ``["PushEvent", "PullRequestEvent"]``); ``None`` keeps all
            event types.
        output: Path to the output file. Suffix ``.parquet`` or ``.jsonl``
            selects the writer.
        workers: Size of the thread pool. Network-bound on residential
            connections; values above 4 give diminishing returns.
    """
    fingerprint = _run_fingerprint(start, end, repos, event_types)
    state = _RunState(output, fingerprint)

    resuming = len(state) > 0
    writer = DataWriter(output, append=resuming)
    all_timestamps = list(date_range(start, end))
    todo = [t for t in all_timestamps if not state.is_done(t)]
    skipped = len(all_timestamps) - len(todo)
    if skipped:
        logger.info(f"Resuming: skipping {skipped} hours already in state file")

    if not todo:
        writer.close()
        logger.info(f"Nothing to do; output already complete at {output}")
        return

    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_time = {
            executor.submit(process_single_hour, ts, repos, event_types): ts
            for ts in todo
        }

        with tqdm(
            total=len(todo),
            desc="Processing",
            unit="hr",
            smoothing=0,
            dynamic_ncols=True,
        ) as pbar:

            for future in concurrent.futures.as_completed(future_to_time):
                ts = future_to_time[future]
                try:
                    data = future.result()
                    if data:
                        for record in data:
                            writer.write(record)
                    # Flush so this hour is durable on disk before we mark it
                    # done. If the process crashes after mark_done, restart
                    # skips this hour and the data is already written.
                    writer.flush()
                    state.mark_done(ts)
                except Exception as exc:
                    failed.append(ts)
                    tqdm.write(f"Worker exception for {ts}: {exc}")
                finally:
                    pbar.update(1)

    writer.close()

    if failed:
        # Signal the failure rather than reporting a clean finish over partial
        # output. For JSONL we keep the state file so a rerun retries only the
        # failed hours. Parquet cannot be appended to, so a kept state file
        # would only make the rerun dead-end on the existing file; clear it so
        # the rerun starts the window over cleanly.
        if writer.is_parquet:
            state.clear()
            hint = (
                "Rerun to start the window over, or use JSONL output to retry "
                "only the failed hours."
            )
        else:
            hint = "Rerun the same command to retry the failed hours."
        raise RuntimeError(
            f"{len(failed)} of {len(todo)} hours failed; output at {output} is "
            f"incomplete. {hint}"
        )

    state.clear()
    logger.info(f"Done! Data written to {output}")