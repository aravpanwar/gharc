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
from .filters import passes_filters, fast_string_check, prefilter_tokens
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

# Return values for download_resumable: the file is here, the archive does not
# exist (a known GHArchive gap, not worth retrying), or a retryable failure.
DOWNLOAD_OK = "ok"
DOWNLOAD_MISSING = "missing"
DOWNLOAD_RETRY = "retry"


def download_resumable(url: str, temp_path: str, session: requests.Session) -> str:
    """Download a file with resume capability.

    Returns ``DOWNLOAD_OK`` once the file is in place, ``DOWNLOAD_MISSING`` if
    the server says the archive does not exist (HTTP 404 or 410), or
    ``DOWNLOAD_RETRY`` for a transient failure the caller should retry.
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
                return DOWNLOAD_OK
            if r.status_code in (404, 410):
                logger.debug(f"HTTP {r.status_code} for {url} (archive not present)")
                return DOWNLOAD_MISSING
            if r.status_code not in [200, 206]:
                logger.debug(f"HTTP {r.status_code} for {url}")
                return DOWNLOAD_RETRY

            if r.status_code == 200 and mode == 'ab':
                mode = 'wb'

            with open(temp_path, mode) as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        return DOWNLOAD_OK
    except Exception as e:
        logger.debug(f"Download attempt failed for {url}: {e}")
        return DOWNLOAD_RETRY

def process_single_hour(dt: datetime, repos: list, event_types: list,
                        orgs: list = None, actors: list = None):
    """Download one hour, keep matching events, delete the temp file.

    Returns the list of events matching the filters (possibly empty).
    """
    url = get_url_for_time(dt)
    results = []
    tokens = prefilter_tokens(repos, event_types, orgs, actors)
    # Convert filters to bytes if using orjson for speed.
    if HAS_ORJSON:
        fast_tokens = [t.encode('utf-8') for t in tokens]
    else:
        fast_tokens = tokens

    session = _session_for_thread()

    fd, temp_path = tempfile.mkstemp(suffix=".json.gz")
    os.close(fd)
    
    download_success = False

    try:
        for attempt in range(10):
            status = download_resumable(url, temp_path, session)
            if status == DOWNLOAD_OK:
                download_success = True
                break
            if status == DOWNLOAD_MISSING:
                logger.warning(f"No archive available at {url}; treating as zero events")
                return []
            time.sleep(2)

        if not download_success:
            # A persistent download failure is a real failure, not an empty
            # hour. Raise so the run reports it and (for JSONL output) retries
            # this hour on resume, rather than silently dropping it.
            raise RuntimeError(
                f"Failed to download {url} after 10 attempts "
                f"(run with debug logging for details)"
            )

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

                        if passes_filters(event, repos, event_types, orgs, actors):
                            results.append(event)
                    except Exception:
                        # GHArchive occasionally has malformed lines; expected at low rates.
                        continue
        except Exception as e:
            # A gzip-level error means the download is truncated or corrupt, so
            # the events collected so far are an incomplete view of the hour.
            # Raise rather than return a partial result, so the hour is retried
            # on resume instead of being recorded as complete.
            raise RuntimeError(f"Failed to read archive for {url}: {e}")

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
        # Write to a temporary file and rename it into place so a crash mid-write
        # cannot truncate the existing state and lose all completed hours. Called
        # only from the main thread, so there is no concurrent writer.
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(
                {"fingerprint": self._fingerprint, "done_hours": sorted(self._done)},
                f,
            )
        os.replace(tmp_path, self._path)

    def clear(self):
        if os.path.exists(self._path):
            os.remove(self._path)


class _NoState:
    """No-op resume state used for Parquet output.

    A closed Parquet file cannot be appended to, so a Parquet run can never be
    resumed. Tracking completed hours would only add a sidecar file that a
    rerun could never use, and rewriting it every hour is wasted work, so
    Parquet runs use this no-op instead.
    """

    def __len__(self):
        return 0

    def is_done(self, ts):
        return False

    def mark_done(self, ts):
        pass

    def clear(self):
        pass


def _run_fingerprint(start, end, repos, event_types, orgs, actors):
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "repos": sorted(repos) if repos else None,
        "event_types": sorted(event_types) if event_types else None,
        "orgs": sorted(orgs) if orgs else None,
        "actors": sorted(actors) if actors else None,
    }


def process_range(start, end, repos, event_types, output, workers,
                  orgs=None, actors=None):
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
        orgs: Optional list of repository owners to keep (an event passes when
            its owner is listed, or its repo matches ``repos``); ``None`` keeps
            all owners.
        actors: Optional list of actor logins to keep; ``None`` keeps all
            actors.
    """
    fingerprint = _run_fingerprint(start, end, repos, event_types, orgs, actors)
    # Parquet cannot be appended to, so it can never be resumed; skip state
    # tracking for it rather than write a sidecar file no rerun could use.
    if str(output).endswith(".parquet"):
        state = _NoState()
    else:
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
            executor.submit(process_single_hour, ts, repos, event_types, orgs, actors): ts
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
                    # Flush the hour's events before marking it done. For JSONL
                    # this makes the appended lines durable so a restart can skip
                    # the hour and trust what is on disk. For Parquet the row
                    # group is only readable after close(), so Parquet uses no
                    # resume state (see _NoState).
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