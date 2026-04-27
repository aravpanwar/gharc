import json
from datetime import datetime
import pytest
from gharc.streamer import _RunState, _run_fingerprint


def make_fp():
    return _run_fingerprint(
        datetime(2024, 1, 1),
        datetime(2024, 1, 2),
        ["apache/spark"],
        None,
    )


def test_fresh_state_has_no_done_hours(tmp_path):
    out = tmp_path / "events.jsonl"
    state = _RunState(str(out), make_fp())
    assert not state.is_done(datetime(2024, 1, 1, 0))


def test_mark_done_persists_across_instances(tmp_path):
    out = tmp_path / "events.jsonl"
    fp = make_fp()

    state1 = _RunState(str(out), fp)
    state1.mark_done(datetime(2024, 1, 1, 5))
    state1.mark_done(datetime(2024, 1, 1, 6))

    state2 = _RunState(str(out), fp)
    assert state2.is_done(datetime(2024, 1, 1, 5))
    assert state2.is_done(datetime(2024, 1, 1, 6))
    assert not state2.is_done(datetime(2024, 1, 1, 7))


def test_fingerprint_mismatch_raises(tmp_path):
    out = tmp_path / "events.jsonl"

    state = _RunState(str(out), make_fp())
    state.mark_done(datetime(2024, 1, 1, 0))

    different_fp = _run_fingerprint(
        datetime(2024, 1, 1),
        datetime(2024, 1, 2),
        ["pandas-dev/pandas"],  # different repos
        None,
    )

    with pytest.raises(ValueError, match="different run"):
        _RunState(str(out), different_fp)


def test_clear_removes_state_file(tmp_path):
    out = tmp_path / "events.jsonl"
    state = _RunState(str(out), make_fp())
    state.mark_done(datetime(2024, 1, 1, 0))

    state.clear()

    state_file = tmp_path / "events.jsonl.state.json"
    assert not state_file.exists()


def test_unreadable_state_file_starts_fresh(tmp_path):
    out = tmp_path / "events.jsonl"
    state_file = tmp_path / "events.jsonl.state.json"
    state_file.write_text("{not valid json")

    state = _RunState(str(out), make_fp())
    assert not state.is_done(datetime(2024, 1, 1, 0))
