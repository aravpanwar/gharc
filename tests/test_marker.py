import json
from datetime import datetime
import pytest
from gharc.streamer import _RunMarker, _run_fingerprint


def make_fp():
    return _run_fingerprint(
        datetime(2024, 1, 1),
        datetime(2024, 1, 2),
        ["apache/spark"],
        None,
        None,
        None,
    )


def test_mark_done_persists_across_instances(tmp_path):
    out = tmp_path / "events.jsonl"
    fp = make_fp()

    marker1 = _RunMarker(str(out), fp)
    marker1.mark_done(datetime(2024, 1, 1, 5))
    marker1.mark_done(datetime(2024, 1, 1, 6))

    marker2 = _RunMarker(str(out), fp)
    assert marker2.is_done(datetime(2024, 1, 1, 5))
    assert marker2.is_done(datetime(2024, 1, 1, 6))
    assert not marker2.is_done(datetime(2024, 1, 1, 7))


def test_fingerprint_mismatch_raises(tmp_path):
    out = tmp_path / "events.jsonl"

    marker = _RunMarker(str(out), make_fp())
    marker.mark_done(datetime(2024, 1, 1, 0))

    different_fp = _run_fingerprint(
        datetime(2024, 1, 1),
        datetime(2024, 1, 2),
        ["pandas-dev/pandas"],
        None,
        None,
        None,
    )

    with pytest.raises(ValueError, match="different run"):
        _RunMarker(str(out), different_fp)


def test_mark_done_writes_atomically_leaving_no_temp(tmp_path):
    out = tmp_path / "events.jsonl"
    marker = _RunMarker(str(out), make_fp())
    marker.mark_done(datetime(2024, 1, 1, 0))

    # The state file is valid JSON and no temporary file is left behind.
    state_file = tmp_path / "events.jsonl.state.json"
    assert state_file.exists()
    assert not (tmp_path / "events.jsonl.state.json.tmp").exists()
    json.loads(state_file.read_text(encoding="utf-8"))


def test_clear_removes_marker_file(tmp_path):
    out = tmp_path / "events.jsonl"
    marker = _RunMarker(str(out), make_fp())
    marker.mark_done(datetime(2024, 1, 1, 0))

    marker.clear()

    state_file = tmp_path / "events.jsonl.state.json"
    assert not state_file.exists()


def test_unreadable_marker_file_starts_fresh(tmp_path):
    out = tmp_path / "events.jsonl"
    state_file = tmp_path / "events.jsonl.state.json"
    state_file.write_text("{not valid json")

    marker = _RunMarker(str(out), make_fp())
    assert not marker.is_done(datetime(2024, 1, 1, 0))
