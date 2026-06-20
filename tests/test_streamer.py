import pytest
import os
import tempfile
from unittest.mock import MagicMock, patch
from gharc.streamer import process_single_hour, process_range
from datetime import datetime

# A tiny fake GZIP content for testing
FAKE_GZIP_DATA = (
    b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03\xabV*J-H\x07\xb2\x8a\x12s\x12\x8b'
    b'\x12\x8b\x4b\xaa\x05\x00\xd8\xaf\x9b\xba\x0e\x00\x00\x00'
) 
# Decodes to: {"repo": "test/repo"}

@patch('gharc.streamer.requests.Session')
def test_process_single_hour_success(mock_session_cls):
    """Test that we can process a file without hitting the real internet"""
    
    # 1. Setup the Mock Network Response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.iter_content.return_value = [FAKE_GZIP_DATA]
    
    mock_session = mock_session_cls.return_value
    mock_session.get.return_value.__enter__.return_value = mock_response
    
    # 2. Setup the "Fake" Logic to match our fake data
    # Note: Our FAKE_GZIP_DATA implies a json `{"repo": "test/repo"}`
    # The real code expects a slightly more complex structure, so let's mock the 
    # file reading part instead to avoid complex gzip bytes construction.
    
    with patch('gharc.streamer.download_resumable') as mock_download:
        mock_download.return_value = True
        
        # We also need to mock gzip.open to read from a string we control
        with patch('gzip.open') as mock_gzip:
            # We simulate a file handle that yields one line of JSON
            mock_file = MagicMock()
            mock_file.__iter__.return_value = [b'{"repo": {"name": "apache/spark"}, "type": "PushEvent"}']
            mock_gzip.return_value.__enter__.return_value = mock_file
            
            # 3. Run the Function
            dt = datetime(2024, 1, 1, 10)
            results = process_single_hour(dt, repos=["apache/spark"], event_types=None)
            
            # 4. Verify Results
            assert len(results) == 1
            assert results[0]['repo']['name'] == "apache/spark"


def test_process_range_raises_when_an_hour_fails(tmp_path):
    out = tmp_path / "out.jsonl"

    # First hour succeeds with no matches, second hour raises.
    def fake_hour(dt, repos, event_types):
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


def test_process_range_parquet_failure_clears_state(tmp_path):
    out = tmp_path / "out.parquet"

    def fake_hour(dt, repos, event_types):
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
