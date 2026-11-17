"""Tests for download_resumable's HTTP status and resume handling."""
import pytest

from gharc.streamer import (
    download_resumable,
    DOWNLOAD_OK,
    DOWNLOAD_MISSING,
    DOWNLOAD_RETRY,
)


class _FakeResponse:
    def __init__(self, status_code, chunks=()):
        self.status_code = status_code
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size=0):
        return iter(self._chunks)


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._response


@pytest.mark.parametrize("status, expected", [
    (416, DOWNLOAD_OK),        # range past the end: the file is already whole
    (404, DOWNLOAD_MISSING),
    (410, DOWNLOAD_MISSING),
    (500, DOWNLOAD_RETRY),
])
def test_status_codes_map_to_results(tmp_path, status, expected):
    session = _FakeSession(_FakeResponse(status))
    assert download_resumable("http://x", str(tmp_path / "f.gz"), session) == expected


def test_200_writes_content(tmp_path):
    temp = tmp_path / "f.gz"
    session = _FakeSession(_FakeResponse(200, chunks=[b"hello ", b"world"]))
    assert download_resumable("http://x", str(temp), session) == DOWNLOAD_OK
    assert temp.read_bytes() == b"hello world"


def test_206_appends_to_partial_download(tmp_path):
    temp = tmp_path / "f.gz"
    temp.write_bytes(b"AAAA")
    session = _FakeSession(_FakeResponse(206, chunks=[b"BBBB"]))

    assert download_resumable("http://x", str(temp), session) == DOWNLOAD_OK
    assert temp.read_bytes() == b"AAAABBBB"
    # The request resumed from the existing byte count.
    _url, kwargs = session.calls[0]
    assert kwargs["headers"] == {"Range": "bytes=4-"}


def test_200_after_partial_overwrites(tmp_path):
    temp = tmp_path / "f.gz"
    temp.write_bytes(b"OLD")
    # A 200 (not 206) means the server ignored the range, so start over.
    session = _FakeSession(_FakeResponse(200, chunks=[b"NEW"]))

    assert download_resumable("http://x", str(temp), session) == DOWNLOAD_OK
    assert temp.read_bytes() == b"NEW"


def test_connection_error_reports_retry(tmp_path):
    temp = tmp_path / "f.gz"

    class _Boom:
        def get(self, *a, **k):
            raise ConnectionError("network down")

    assert download_resumable("http://x", str(temp), _Boom()) == DOWNLOAD_RETRY
