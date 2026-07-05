import pytest
from unittest.mock import MagicMock, patch
from gharc.streamer import (
    process_single_hour,
    process_range,
    download_resumable,
    _RunState,
    _run_fingerprint,
    DOWNLOAD_OK,
    DOWNLOAD_MISSING,
    DOWNLOAD_RETRY,
)
from datetime import datetime

def test_process_single_hour_success():
    """Process an hour without touching the network, by mocking the download
    and the gzip read so a single known line flows through the filter."""
    with patch('gharc.streamer.download_resumable', return_value=DOWNLOAD_OK):
        with patch('gzip.open') as mock_gzip:
            mock_file = MagicMock()
            mock_file.__iter__.return_value = [
                b'{"repo": {"name": "apache/spark"}, "type": "PushEvent"}'
            ]
            mock_gzip.return_value.__enter__.return_value = mock_file

            results = process_single_hour(
                datetime(2024, 1, 1, 10), repos=["apache/spark"], event_types=None
            )

    assert len(results) == 1
    assert results[0]['repo']['name'] == "apache/spark"


@patch('gharc.streamer.time.sleep', lambda *_: None)
@patch('gharc.streamer.download_resumable', return_value=DOWNLOAD_RETRY)
def test_process_single_hour_raises_on_persistent_download_failure(_mock):
    with pytest.raises(RuntimeError, match="Failed to download"):
        process_single_hour(datetime(2024, 1, 1, 0), repos=["apache/spark"], event_types=None)


@patch('gharc.streamer.download_resumable', return_value=DOWNLOAD_MISSING)
def test_process_single_hour_returns_empty_on_missing_archive(_mock):
    result = process_single_hour(datetime(2024, 1, 1, 0), repos=["apache/spark"], event_types=None)
    assert result == []


@patch('gharc.streamer.download_resumable', return_value=DOWNLOAD_OK)
def test_process_single_hour_raises_on_corrupt_archive(_mock):
    # A download that lands but is not valid gzip means the hour is incomplete.
    with patch('gharc.streamer.gzip.open', side_effect=OSError("Not a gzipped file")):
        with pytest.raises(RuntimeError, match="Failed to read archive"):
            process_single_hour(datetime(2024, 1, 1, 0), repos=["apache/spark"], event_types=None)


def test_process_range_raises_when_an_hour_fails(tmp_path):
    out = tmp_path / "out.jsonl"

    # First hour succeeds with no matches, second hour raises.
    def fake_hour(dt, repos, event_types, orgs=None, actors=None):
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
    # The run should stop with a non-zero exit and leave the checkpoint intact.
    def fake_hour(dt, repos, event_types, orgs=None, actors=None):
        raise KeyboardInterrupt

    with patch('gharc.streamer.process_single_hour', side_effect=fake_hour):
        with pytest.raises(SystemExit):
            process_range(
                start=datetime(2024, 1, 1, 0),
                end=datetime(2024, 1, 1, 3),
                repos=["apache/spark"],
                event_types=None,
                output=str(out),
                workers=1,
            )

    assert (tmp_path / "out.jsonl.state.json").exists()


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

    def fake_hour(dt, repos, event_types, orgs=None, actors=None):
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
