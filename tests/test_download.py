"""Tests for download_resumable's HTTP status and resume handling."""
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


def test_416_reports_done(tmp_path):
    temp = tmp_path / "f.gz"
    session = _FakeSession(_FakeResponse(416))
    assert download_resumable("http://x", str(temp), session) == DOWNLOAD_OK


def test_404_reports_missing(tmp_path):
    temp = tmp_path / "f.gz"
    session = _FakeSession(_FakeResponse(404))
    assert download_resumable("http://x", str(temp), session) == DOWNLOAD_MISSING


def test_410_reports_missing(tmp_path):
    temp = tmp_path / "f.gz"
    session = _FakeSession(_FakeResponse(410))
    assert download_resumable("http://x", str(temp), session) == DOWNLOAD_MISSING


def test_500_reports_retry(tmp_path):
    temp = tmp_path / "f.gz"
    session = _FakeSession(_FakeResponse(500))
    assert download_resumable("http://x", str(temp), session) == DOWNLOAD_RETRY


def test_200_writes_content(tmp_path):
    temp = tmp_path / "f.gz"
    session = _FakeSession(_FakeResponse(200, chunks=[b"hello ", b"world"]))
    assert download_resumable("http://x", str(temp), session) == DOWNLOAD_OK
    assert temp.read_bytes() == b"hello world"


def test_206_appends_to_partial_download(tmp_path):
    temp = tmp_path / "f.gz"
    temp.write_bytes(b"AAAA")  # 4 bytes already on disk
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
