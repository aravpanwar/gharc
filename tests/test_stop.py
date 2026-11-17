"""Stopping a run must reach hours that are blocked in the network layer."""
import http.server
import threading
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from gharc.streamer import (
    DOWNLOAD_RETRY,
    _HourStopped,
    _RunStop,
    _StoppableRetry,
    _thread_local,
    download_resumable,
    get_robust_session,
    process_single_hour,
)


class _StallingHandler(http.server.BaseHTTPRequestHandler):
    """Sends the headers and a little data, then goes silent like a dead link."""

    release = None

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(10_000_000))
        self.end_headers()
        self.wfile.write(b"x" * 70_000)
        self.wfile.flush()
        self.release.wait(30)

    def log_message(self, *args):
        pass


class _UnavailableHandler(http.server.BaseHTTPRequestHandler):
    """Answers every request with 503 so urllib3 keeps backing off."""

    def do_GET(self):
        self.send_response(503)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def serve():
    servers = []
    release = threading.Event()

    def start(handler):
        handler.release = release
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}/hour.json.gz"

    yield start
    release.set()
    for server in servers:
        server.shutdown()
        server.server_close()


def _run_in_thread(target):
    outcome = {}

    def runner():
        try:
            outcome["value"] = target()
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread, outcome


@pytest.mark.parametrize("protocol", ["HTTP/1.0", "HTTP/1.1"])
def test_stop_wakes_a_download_stalled_mid_transfer(serve, tmp_path, protocol):
    # HTTP/1.1 keeps the connection alive like GHArchive; HTTP/1.0 closes it
    # after the response, which moves the socket to a different place.
    handler = type("Handler", (_StallingHandler,), {"protocol_version": protocol})
    url = serve(handler)
    temp = tmp_path / "hour.json.gz"
    stop = _RunStop()

    thread, outcome = _run_in_thread(
        lambda: download_resumable(url, str(temp), get_robust_session(), stop)
    )
    # Wait for the download to register its socket with the stop signal, then
    # give it a moment to drain the data and block. The file size is no use as
    # a signal: Python 3.14's larger write buffer keeps the first chunk in
    # memory, so the file stays empty on disk.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not stop._sockets:
        time.sleep(0.02)
    assert stop._sockets, "the download never started"
    time.sleep(0.3)

    stopped_at = time.monotonic()
    stop.set()
    thread.join(5)

    assert not thread.is_alive()
    assert time.monotonic() - stopped_at < 3
    assert outcome == {"value": DOWNLOAD_RETRY}


def test_stop_cuts_short_a_retry_backoff(serve):
    url = serve(_UnavailableHandler)
    stop = _RunStop()

    with patch("gharc.streamer.get_url_for_time", return_value=url):
        thread, outcome = _run_in_thread(
            lambda: process_single_hour(datetime(2024, 1, 1), None, None, stop=stop)
        )
        # Let urllib3 get through its first quick retries into a real backoff.
        time.sleep(1.0)
        stopped_at = time.monotonic()
        stop.set()
        thread.join(5)

    assert not thread.is_alive()
    assert time.monotonic() - stopped_at < 3
    assert isinstance(outcome.get("error"), _HourStopped)


def test_retry_sleep_raises_once_the_worker_is_stopped():
    stop = threading.Event()
    stop.set()
    _thread_local.stop = stop
    try:
        with pytest.raises(_HourStopped):
            _StoppableRetry(total=3, backoff_factor=1).sleep()
    finally:
        _thread_local.stop = None


def test_retry_sleep_without_a_run_falls_back_to_urllib3():
    _thread_local.stop = None
    # No stop signal on this thread: the stock urllib3 sleep runs (no backoff yet).
    _StoppableRetry(total=3, backoff_factor=1).sleep()


def test_run_stop_shuts_a_socket_watched_after_it_was_set():
    stop = _RunStop()
    stop.set()
    shut = []

    class _Sock:
        def shutdown(self, how):
            shut.append("shutdown")

        def close(self):
            shut.append("close")

    class _Raw:
        connection = type("C", (), {"sock": _Sock()})()

    class _Response:
        raw = _Raw()

    # A download that registers after the stop must not be left blocking.
    assert stop.watch(_Response()) is None
    assert shut == ["shutdown", "close"]
