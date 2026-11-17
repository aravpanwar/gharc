# src/gharc/streamer.py
import requests
import gzip
import json
import concurrent.futures
import threading
import time
import os
import socket
import tempfile
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
from .utils import get_url_for_time, date_range, logger
from .filters import passes_filters, passes_prefilter, prefilter_groups
from .storage import DataWriter

try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False

_thread_local = threading.local()


class _StoppableRetry(Retry):
    """urllib3 retry policy whose backoff sleep gives way to a stopped run.

    urllib3 sleeps inside the request call between retries, up to about half
    a minute through a burst of 503s, where the run's stop signal cannot
    otherwise reach it. Waiting on the worker's stop event instead lets Ctrl+C
    cut the backoff short.
    """

    def sleep(self, response=None):
        stop = getattr(_thread_local, "stop", None)
        if stop is None:
            return super().sleep(response)
        delay = None
        if self.respect_retry_after_header and response is not None:
            delay = self.get_retry_after(response)
        if delay is None:
            delay = self.get_backoff_time()
        if stop.wait(delay):
            raise _HourStopped("stopped during a retry backoff")


def get_robust_session():
    """Creates a requests session with retry logic."""
    session = requests.Session()
    retry_strategy = _StoppableRetry(
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

# How many times one hour's download is attempted before the hour fails.
DOWNLOAD_ATTEMPTS = 14


class _HourStopped(RuntimeError):
    """Raised inside a worker when the run asked in-flight hours to give up."""


def _raise_if_stopped(stop, url):
    if stop is not None and stop.is_set():
        raise _HourStopped(f"stopped before {url} finished")


def _response_socket(response):
    # The socket is the only handle another thread can use to wake a read that
    # is blocked on a stalled link. On a kept-alive connection it stays on the
    # urllib3 connection; when the server will close the connection after the
    # response, http.client moves it onto the response's file instead.
    connection = getattr(response.raw, "connection", None)
    sock = getattr(connection, "sock", None)
    if sock is None:
        fp = getattr(getattr(response.raw, "_fp", None), "fp", None)
        sock = getattr(getattr(fp, "raw", None), "_sock", None)
    return sock


def _shut(sock):
    # shutdown wakes a blocked read on Linux and macOS but not on Windows, where
    # only closing the handle does. A plain close() is deferred while the HTTP
    # response's file still holds the socket, so the socket's real close is
    # used when it exists.
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        getattr(sock, "_real_close", sock.close)()
    except OSError:
        pass


class _RunStop(threading.Event):
    """Stop signal shared by a run's workers.

    Setting it also shuts down the socket of every download in progress. A
    worker blocked reading from a stalled connection would otherwise notice
    the stop only when the read timeout expired, more than two minutes later.
    """

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._sockets = set()

    def watch(self, response):
        """Track a streaming response's socket; returns a handle for unwatch."""
        sock = _response_socket(response)
        if sock is None:
            return None
        with self._lock:
            if not self.is_set():
                self._sockets.add(sock)
                return sock
        _shut(sock)
        return None

    def unwatch(self, sock):
        if sock is not None:
            with self._lock:
                self._sockets.discard(sock)

    def set(self):
        with self._lock:
            super().set()
            sockets = list(self._sockets)
            self._sockets.clear()
        for sock in sockets:
            _shut(sock)


def download_resumable(url: str, temp_path: str, session: requests.Session,
                       stop: threading.Event = None) -> str:
    """Download a file with resume capability.

    Returns ``DOWNLOAD_OK`` once the file is in place, ``DOWNLOAD_MISSING`` if
    the server says the archive does not exist (HTTP 404 or 410), or
    ``DOWNLOAD_RETRY`` for a transient failure the caller should retry. If
    ``stop`` is set mid-transfer the download is abandoned and reported as
    ``DOWNLOAD_RETRY``; the caller checks ``stop`` before retrying.
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
        with session.get(url, headers=resume_header, stream=True, timeout=(34, 134)) as r:
            watched = stop.watch(r) if isinstance(stop, _RunStop) else None
            try:
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
                        if stop is not None and stop.is_set():
                            return DOWNLOAD_RETRY
                        if chunk:
                            f.write(chunk)
            finally:
                if watched is not None:
                    stop.unwatch(watched)
        return DOWNLOAD_OK
    except Exception as e:
        logger.debug(f"Download attempt failed for {url}: {e}")
        return DOWNLOAD_RETRY

def _sweep_archive(path, url, groups, repos, event_types, orgs, actors, stop):
    """Read one downloaded hour and return the events that pass the filters."""
    results = []
    try:
        with gzip.open(path, 'rb') as f:
            for line in f:
                _raise_if_stopped(stop, url)
                try:
                    if HAS_ORJSON:
                        if not passes_prefilter(line, groups):
                            continue
                        event = orjson.loads(line)
                    else:
                        decoded = line.decode('utf-8')
                        if not passes_prefilter(decoded, groups):
                            continue
                        event = json.loads(decoded)

                    if passes_filters(event, repos, event_types, orgs, actors):
                        results.append(event)
                except Exception:
                    # GHArchive occasionally has malformed lines; expected at low rates.
                    continue
    except _HourStopped:
        raise
    except Exception as e:
        # A gzip-level error means the download is truncated or corrupt, so
        # the events collected so far are an incomplete view of the hour.
        # Raise rather than return a partial result, so the hour is retried
        # on resume instead of being recorded as complete.
        raise RuntimeError(f"couldn't read archive {url}: {e}") from e
    return results


def process_single_hour(dt: datetime, repos: list, event_types: list,
                        orgs: list = None, actors: list = None,
                        stop: threading.Event = None):
    """Download one hour, keep matching events, delete the temp file.

    Returns the list of events matching the filters (possibly empty), or None if
    GHArchive has no archive for that hour (a known gap), so the caller can tell
    an absent hour apart from an hour that simply had no matches. Setting
    ``stop`` from another thread makes the hour raise at its next downloaded
    chunk, retry, backoff or archive line; a run's ``_RunStop`` also wakes a
    read that is blocked on a stalled connection.
    """
    url = get_url_for_time(dt)
    groups = prefilter_groups(repos, event_types, orgs, actors)
    # orjson parses bytes directly, so matching the tokens as bytes lets a
    # rejected line skip UTF-8 decoding as well as parsing.
    if HAS_ORJSON:
        groups = [[t.encode('utf-8') for t in tokens] for tokens in groups]

    session = _session_for_thread()
    fd, temp_path = tempfile.mkstemp(suffix=".json.gz")
    os.close(fd)
    # The retry policy's backoff sleep runs deep inside requests, so it finds
    # this hour's stop signal through the worker thread instead.
    _thread_local.stop = stop

    try:
        for _ in range(DOWNLOAD_ATTEMPTS):
            _raise_if_stopped(stop, url)
            status = download_resumable(url, temp_path, session, stop)
            if status == DOWNLOAD_OK:
                break
            if status == DOWNLOAD_MISSING:
                logger.debug(f"No archive available at {url}")
                return None
            _raise_if_stopped(stop, url)
            if stop is not None:
                stop.wait(2)
            else:
                time.sleep(2)
        else:
            # A persistent download failure is a real failure, not an empty
            # hour. Raise so the run reports it and (for JSONL output) retries
            # this hour on resume, rather than silently dropping it.
            raise RuntimeError(
                f"failed to download {url} after {DOWNLOAD_ATTEMPTS} attempts "
                f"(run with --debug for details)"
            )

        return _sweep_archive(temp_path, url, groups, repos, event_types,
                              orgs, actors, stop)
    finally:
        _thread_local.stop = None
        if os.path.exists(temp_path):
            os.remove(temp_path)


class _RunMarker:
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
        # Byte length of the JSONL output at the last completed hour. Rows
        # written past this offset belong to an hour that was interrupted
        # before it was marked done, so a resume trims back to here.
        self._marker_offset = 0
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.warning(f"State file {self._path} unreadable, starting fresh")
                return
            if payload.get("fingerprint") != fingerprint:
                raise ValueError(
                    f"state file {self._path} belongs to a different run "
                    f"(window or filters changed); remove it or use a new --output"
                )
            self._done = set(payload.get("done_hours", []))
            self._marker_offset = payload.get("committed_offset", 0)

    def __len__(self):
        return len(self._done)

    @property
    def marker_offset(self):
        return self._marker_offset

    def is_done(self, ts):
        return ts.isoformat() in self._done

    def mark_done(self, ts, offset=0):
        self._done.add(ts.isoformat())
        self._marker_offset = offset
        # Write to a temporary file and rename it into place so a crash mid-write
        # cannot truncate the existing state and lose all completed hours. Called
        # only from the main thread, so there is no concurrent writer.
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "fingerprint": self._fingerprint,
                    "done_hours": sorted(self._done),
                    "committed_offset": self._marker_offset,
                },
                f,
            )
        os.replace(tmp_path, self._path)

    def clear(self):
        if os.path.exists(self._path):
            os.remove(self._path)


class _NoMarker:
    """No-op resume state used for Parquet output.

    A closed Parquet file cannot be appended to, so a Parquet run can never be
    resumed. Tracking completed hours would only add a sidecar file that a
    rerun could never use, and rewriting it every hour is wasted work, so
    Parquet runs use this no-op instead.
    """

    marker_offset = 0

    def __len__(self):
        return 0

    def is_done(self, ts):
        return False

    def mark_done(self, ts, offset=0):
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


def _sweep_hours(executor, run_hour, hours, depth, interval=0.5):
    """Run hours on the executor and yield ``(hour, future)`` as each finishes.

    Only ``depth`` hours are queued at a time, and the next one is submitted as
    each finishes. Submitting a whole window up front made every wait below
    rescan all of its queued futures, a cost that grew with the window (over a
    third of a core for ten years of hours), and held them all in memory.

    The wait wakes at least every ``interval`` seconds because otherwise it
    blocks on a lock that Ctrl+C cannot break on Windows, so an interrupt would
    only land when the next hour happened to finish. Waking up regularly
    returns control to the interpreter, which raises KeyboardInterrupt at once.
    """
    hours = iter(hours)
    pending = {}

    def submit_next():
        hour = next(hours, None)
        if hour is not None:
            pending[executor.submit(run_hour, hour)] = hour

    for _ in range(depth):
        submit_next()
    while pending:
        done, _ = concurrent.futures.wait(
            pending, timeout=interval,
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        for future in done:
            submit_next()
            yield pending.pop(future), future


def _reconcile_jsonl_marker(output, marker_offset):
    """Line up a JSONL output with its resume checkpoint before appending.

    Rows past ``committed_offset`` belong to an hour that was interrupted
    before it was marked done, so they are trimmed to keep resume exactly-once.
    An output shorter than the checkpoint means it was truncated or deleted, so
    the checkpoint can no longer be trusted and the run stops with an error.
    """
    size = os.path.getsize(output) if os.path.exists(output) else 0
    if size < marker_offset:
        raise ValueError(
            f"output {output} is shorter than its resume checkpoint "
            f"({size} < {marker_offset} bytes); it looks truncated or "
            f"deleted, so remove {output}.state.json to start the window over"
        )
    if size > marker_offset:
        with open(output, "r+b") as f:
            f.truncate(marker_offset)


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
        marker = _NoMarker()
    else:
        marker = _RunMarker(output, fingerprint)

    resuming = len(marker) > 0
    writer = DataWriter(output, append=resuming)
    if resuming and not writer.is_parquet:
        _reconcile_jsonl_marker(output, marker.marker_offset)
    all_timestamps = list(date_range(start, end))
    todo = [t for t in all_timestamps if not marker.is_done(t)]
    skipped = len(all_timestamps) - len(todo)
    if skipped:
        logger.info(f"Resuming: skipping {skipped} hours already in state file")

    if not todo:
        writer.close()
        logger.info(f"Nothing to do; output already complete at {output}")
        return

    failed = []
    missing = 0
    # Own the executor explicitly rather than through a `with` block: on
    # Ctrl+C we want to cancel the hours that have not started yet, but a
    # `with` block's exit calls shutdown(wait=True), which drains the whole
    # queue instead. On a long run that means Ctrl+C would keep downloading
    # for a long time before stopping.
    #
    # Cancelling only covers hours still queued. The hours already running are
    # told to give up through `stop`, because otherwise the final
    # shutdown(wait=True) would sit until each in-flight download and parse
    # finished on its own.
    stop = _RunStop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)

    def run_hour(ts):
        return process_single_hour(ts, repos, event_types, orgs, actors, stop=stop)

    try:
        with tqdm(
            total=len(todo),
            desc="Processing",
            unit="hr",
            smoothing=0,
            dynamic_ncols=True,
        ) as pbar:

            for ts, future in _sweep_hours(executor, run_hour, todo, depth=workers * 2):
                try:
                    data = future.result()
                    if data is None:
                        # No archive published for this hour (a known gap).
                        missing += 1
                    elif data:
                        for record in data:
                            writer.write(record)
                    # Flush the hour's events before marking it done. For JSONL
                    # this makes the appended lines durable so a restart can skip
                    # the hour and trust what is on disk. For Parquet the row
                    # group is only readable after close(), so Parquet uses no
                    # resume state (see _NoMarker). The committed byte offset is
                    # recorded with the hour so a resume can trim a partially
                    # written hour and stay exactly-once.
                    writer.flush()
                    offset = os.path.getsize(output) if os.path.exists(output) else 0
                    marker.mark_done(ts, offset)
                except Exception as exc:
                    failed.append(ts)
                    tqdm.write(f"Worker exception for {ts}: {exc}")
                finally:
                    pbar.update(1)
    except KeyboardInterrupt:
        # Cancel the hours still queued so we stop soon rather than draining
        # the pool. Any rows buffered for an hour that was not marked done are
        # dropped. KeyboardInterrupt is re-raised so an API caller sees the
        # normal interrupt; the CLI turns it into a non-zero exit.
        stop.set()
        executor.shutdown(wait=False, cancel_futures=True)
        writer.buffer.clear()
        writer.close()
        if writer.is_parquet:
            logger.warning(
                "Interrupted; stopping. Parquet output cannot resume, so rerun "
                "to start the window over."
            )
        else:
            logger.warning("Interrupted; stopping. Rerun the same command to resume.")
        raise
    finally:
        executor.shutdown(wait=True)

    writer.close()

    if missing:
        logger.info(
            f"{missing} of {len(todo)} hours had no published archive and were "
            f"counted as zero events."
        )

    if failed:
        # Signal the failure rather than reporting a clean finish over partial
        # output. For JSONL we keep the state file so a rerun retries only the
        # failed hours. Parquet cannot be appended to, so a kept state file
        # would only make the rerun dead-end on the existing file; clear it so
        # the rerun starts the window over cleanly.
        if writer.is_parquet:
            marker.clear()
            hint = (
                "rerun to start the window over, or use JSONL output to retry "
                "only the failed hours"
            )
        else:
            hint = "rerun the same command to retry the failed hours"
        raise RuntimeError(
            f"failed {len(failed)} of {len(todo)} hours, so {output} is "
            f"incomplete; {hint}"
        )

    marker.clear()
    logger.info(f"Done! Data written to {output}")