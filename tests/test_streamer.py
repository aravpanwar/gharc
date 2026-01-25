import pytest
import os
import tempfile
from unittest.mock import MagicMock, patch
from gharc.streamer import process_single_hour
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
