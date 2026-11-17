import json
import os
import tempfile
import threading
import time

import pytest
from unittest.mock import MagicMock, patch
from gharc.streamer import (
    process_single_hour,
    process_range,
    download_resumable,
    _HourStopped,
    _RunState,
    _run_fingerprint,
    DOWNLOAD_OK,
    DOWNLOAD_MISSING,
    DOWNLOAD_RETRY,
)
from datetime import datetime

@pytest.mark.parametrize("use_orjson", [False, True])
def test_process_single_hour_combined_filter_on_both_parsers(use_orjson):
    if use_orjson:
        pytest.importorskip("orjson")
    lines = [
        b'{"type": "PushEvent", "repo": {"name": "someone/else"}}',
        b'{"type": "WatchEvent", "repo": {"name": "apache/spark"}}',
        b'{"type": "PushEvent", "repo": {"name": "apache/spark"}}',
        b'not json at all',
    ]
    with patch('gharc.streamer.HAS_ORJSON', use_orjson), \
            patch('gharc.streamer.download_resumable', return_value=DOWNLOAD_OK), \
            patch('gzip.open') as mock_gzip:
        mock_file = MagicMock()
        mock_file.__iter__.return_value = lines
        mock_gzip.return_value.__enter__.return_value = mock_file

        results = process_single_hour(
            datetime(2024, 1, 1, 10), repos=["apache/spark"], event_types=["PushEvent"]
        )

    assert results == [{"type": "PushEvent", "repo": {"name": "apache/spark"}}]


@patch('gharc.streamer.time.sleep', lambda *_: None)
@patch('gharc.streamer.download_resumable', return_value=DOWNLOAD_RETRY)
def test_process_single_hour_raises_on_persistent_download_failure(_mock):
    with pytest.raises(RuntimeError, match="failed to download"):
        process_single_hour(datetime(2024, 1, 1, 0), repos=["apache/spark"], event_types=None)


@patch('gharc.streamer.download_resumable', return_value=DOWNLOAD_MISSING)
def test_process_single_hour_returns_none_on_missing_archive(_mock):
    # None (not []) so the caller can tell an absent hour from an empty one.
    result = process_single_hour(datetime(2024, 1, 1, 0), repos=["apache/spark"], event_types=None)
    assert result is None


@patch('gharc.streamer.download_resumable', return_value=DOWNLOAD_OK)
def test_process_single_hour_raises_on_corrupt_archive(_mock):
    # A download that lands but is not valid gzip means the hour is incomplete.
    with patch('gharc.streamer.gzip.open', side_effect=OSError("Not a gzipped file")):
        with pytest.raises(RuntimeError, match="couldn't read archive"):
            process_single_hour(datetime(2024, 1, 1, 0), repos=["apache/spark"], event_types=None)


def test_process_range_raises_when_an_hour_fails(tmp_path):
    out = tmp_path / "out.jsonl"

    # First hour succeeds with no matches, second hour raises.
    def fake_hour(dt, repos, event_types, orgs=None, actors=None, stop=None):
        if dt.hour == 1:
            raise RuntimeError("boom")
        return []

    with patch('gharc.streamer.process_single_hour', side_effect=fake_hour):
        with pytest.raises(RuntimeError, match="failed"):
            process_range(
                start=datetime(2024, 1, 1, 0),
                end=datetime(2024, 1, 1, 2),
                repos=["apache/spark"],
                event_types=None,
                output=str(out),
                workers=1,
            )

    # The completed hour stays in the state file so a rerun retries only the
    # failed hour instead of starting over.
    assert (tmp_path / "out.jsonl.state.json").exists()


def test_process_range_keyboard_interrupt_stops_and_keeps_state(tmp_path):
    out = tmp_path / "out.jsonl"

    # Pre-seed a checkpoint as if an earlier hour had already completed.
    fingerprint = _run_fingerprint(
        datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 3),
        ["apache/spark"], None, None, None,
    )
    seed = _RunState(str(out), fingerprint)
    seed.mark_done(datetime(2024, 1, 1, 0))

    # The remaining hours raise KeyboardInterrupt as if the user hit Ctrl+C.
    # process_range re-raises it (the CLI turns that into a non-zero exit) and
    # leaves the checkpoint intact.
    def fake_hour(dt, repos, event_types, orgs=None, actors=None, stop=None):
        raise KeyboardInterrupt

    with patch('gharc.streamer.process_single_hour', side_effect=fake_hour):
        with pytest.raises(KeyboardInterrupt):
            process_range(
                start=datetime(2024, 1, 1, 0),
                end=datetime(2024, 1, 1, 3),
                repos=["apache/spark"],
                event_types=None,
                output=str(out),
                workers=1,
            )

    assert (tmp_path / "out.jsonl.state.json").exists()


def test_resume_trims_uncommitted_tail(tmp_path):
    out = tmp_path / "out.jsonl"

    # One committed line for hour 0, plus a stale line from an hour that was
    # interrupted before it was checkpointed.
    committed = json.dumps({"id": "committed"}) + "\n"
    out.write_text(committed + json.dumps({"id": "stale"}) + "\n", encoding="utf-8")

    fingerprint = _run_fingerprint(
        datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 2), None, None, None, None
    )
    state = _RunState(str(out), fingerprint)
    state.mark_done(datetime(2024, 1, 1, 0), len(committed.encode("utf-8")))

    def fake_hour(dt, repos, event_types, orgs=None, actors=None, stop=None):
        return [{"id": "hour1"}]

    with patch("gharc.streamer.process_single_hour", side_effect=fake_hour):
        process_range(
            datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 2),
            None, None, str(out), 1,
        )

    ids = [json.loads(line)["id"] for line in out.read_text(encoding="utf-8").splitlines()]
    # The stale line is trimmed and hour 1 is appended once, so no duplication.
    assert ids == ["committed", "hour1"]


def test_resume_errors_when_output_shorter_than_checkpoint(tmp_path):
    out = tmp_path / "out.jsonl"

    fingerprint = _run_fingerprint(
        datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 2), None, None, None, None
    )
    state = _RunState(str(out), fingerprint)
    # Checkpoint claims committed bytes, but the output file is gone.
    state.mark_done(datetime(2024, 1, 1, 0), 500)

    def fake_hour(dt, repos, event_types, orgs=None, actors=None, stop=None):
        return []

    with patch("gharc.streamer.process_single_hour", side_effect=fake_hour):
        with pytest.raises(ValueError, match="shorter than its resume checkpoint"):
            process_range(
                datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 2),
                None, None, str(out), 1,
            )


def test_process_range_parquet_uses_no_state_file(tmp_path):
    out = tmp_path / "out.parquet"

    # Parquet cannot resume, so no sidecar state file should be created.
    with patch('gharc.streamer.process_single_hour', return_value=[]):
        process_range(
            start=datetime(2024, 1, 1, 0),
            end=datetime(2024, 1, 1, 3),
            repos=["apache/spark"],
            event_types=None,
            output=str(out),
            workers=1,
        )

    assert not (tmp_path / "out.parquet.state.json").exists()
    assert out.exists()


def test_process_range_parquet_failure_clears_state(tmp_path):
    out = tmp_path / "out.parquet"

    def fake_hour(dt, repos, event_types, orgs=None, actors=None, stop=None):
        if dt.hour == 1:
            raise RuntimeError("boom")
        return []

    with patch('gharc.streamer.process_single_hour', side_effect=fake_hour):
        with pytest.raises(RuntimeError, match="failed"):
            process_range(
                start=datetime(2024, 1, 1, 0),
                end=datetime(2024, 1, 1, 2),
                repos=["apache/spark"],
                event_types=None,
                output=str(out),
                workers=1,
            )

    # Parquet cannot resume, so the state file is cleared rather than left to
    # dead-end the next run on the existing Parquet file.
    assert not (tmp_path / "out.parquet.state.json").exists()


def test_keyboard_interrupt_stops_in_flight_hours_promptly(tmp_path):
    out = tmp_path / "out.jsonl"
    second_started = threading.Event()
    second_saw_stop = []

    # Hour 1 is already running when hour 0 raises KeyboardInterrupt. It
    # stands in for a long download and should be released by the stop event
    # rather than holding up the shutdown for its full duration.
    def fake_hour(dt, repos, event_types, orgs=None, actors=None, stop=None):
        if dt.hour == 0:
            second_started.wait(5)
            raise KeyboardInterrupt
        second_started.set()
        second_saw_stop.append(stop.wait(30))
        return []

    began = time.monotonic()
    with patch("gharc.streamer.process_single_hour", side_effect=fake_hour):
        with pytest.raises(KeyboardInterrupt):
            process_range(
                datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 2),
                None, None, str(out), 2,
            )

    assert second_saw_stop == [True]
    assert time.monotonic() - began < 10


def test_download_resumable_abandons_transfer_when_stopped(tmp_path):
    temp = tmp_path / "f.gz"
    stop = threading.Event()

    def chunks():
        yield b"first"
        stop.set()
        yield b"second"

    response = MagicMock()
    response.status_code = 200
    response.iter_content.return_value = chunks()
    response.__enter__.return_value = response
    session = MagicMock()
    session.get.return_value = response

    assert download_resumable("http://x", str(temp), session, stop) == DOWNLOAD_RETRY
    assert temp.read_bytes() == b"first"


def test_process_single_hour_raises_when_stopped_and_cleans_up(tmp_path):
    stop = threading.Event()
    stop.set()
    made = []
    real_mkstemp = tempfile.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, path = real_mkstemp(*args, dir=str(tmp_path), **kwargs)
        made.append(path)
        return fd, path

    with patch("gharc.streamer.tempfile.mkstemp", side_effect=tracking_mkstemp), \
            patch("gharc.streamer.download_resumable") as mock_dl:
        with pytest.raises(_HourStopped):
            process_single_hour(
                datetime(2024, 1, 1, 0), repos=None, event_types=None, stop=stop
            )

    mock_dl.assert_not_called()
    assert made and not any(os.path.exists(p) for p in made)


def test_sweep_hours_runs_every_hour_once_with_a_bounded_queue():
    from concurrent.futures import ThreadPoolExecutor
    from gharc.streamer import _sweep_hours

    class CountingExecutor:
        """Records the most unfinished hours ever queued at once."""

        def __init__(self, inner):
            self.inner = inner
            self.futures = []
            self.most = 0

        def submit(self, fn, *args):
            future = self.inner.submit(fn, *args)
            self.futures.append(future)
            unfinished = sum(1 for f in self.futures if not f.done())
            self.most = max(self.most, unfinished)
            return future

    def run_hour(hour):
        # Every fifth hour outlasts several polling intervals.
        time.sleep(0.06 if hour % 5 == 0 else 0)
        return hour * 10

    with ThreadPoolExecutor(max_workers=2) as pool:
        executor = CountingExecutor(pool)
        seen = []
        for hour, future in _sweep_hours(executor, run_hour, range(40), depth=4,
                                         interval=0.02):
            seen.append((hour, future.result()))

    assert sorted(seen) == [(h, h * 10) for h in range(40)]
    assert executor.most <= 4
