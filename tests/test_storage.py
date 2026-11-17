import json
import pyarrow.parquet as pq
import pytest
from gharc.storage import DataWriter


SAMPLE_EVENTS = [
    {
        "id": "1",
        "type": "PushEvent",
        "actor": {"id": "34-4407", "login": "gustav-victor"},
        "repo": {"id": 1, "name": "apache/spark"},
        "payload": {"size": 1, "ref": "refs/heads/master"},
        "created_at": "2024-01-01T00:00:00Z",
        "public": True,
    },
    {
        "id": "2",
        "type": "WatchEvent",
        "actor": {"id": 200, "login": "bob"},
        "repo": {"id": 1, "name": "apache/spark"},
        "payload": {"action": "started"},
        "created_at": "2024-01-01T00:01:00Z",
        "public": True,
    },
]


def test_jsonl_round_trip(tmp_path):
    out = tmp_path / "events.jsonl"
    writer = DataWriter(str(out))
    for event in SAMPLE_EVENTS:
        writer.write(event)
    writer.close()

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "1"
    assert json.loads(lines[1])["type"] == "WatchEvent"


def test_jsonl_writes_utf8_without_escaping(tmp_path):
    out = tmp_path / "events.jsonl"
    writer = DataWriter(str(out))
    writer.write({"id": "1", "type": "PushEvent", "payload": {"msg": "café 日本語"}})
    writer.close()

    text = out.read_text(encoding="utf-8")
    assert "café 日本語" in text
    assert "\\u" not in text


def test_jsonl_truncates_on_rerun(tmp_path):
    out = tmp_path / "events.jsonl"

    writer = DataWriter(str(out))
    writer.write(SAMPLE_EVENTS[0])
    writer.close()

    writer = DataWriter(str(out))
    writer.write(SAMPLE_EVENTS[1])
    writer.close()

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "2"


def test_parquet_round_trip_streams_all_batches(tmp_path):
    out = tmp_path / "events.parquet"
    writer = DataWriter(str(out))
    writer.buffer_size = 1  # flush per record to exercise streaming append

    for event in SAMPLE_EVENTS:
        writer.write(event)
    writer.close()

    table = pq.read_table(str(out))
    assert table.num_rows == 2
    by_id = dict(zip(table.column("id").to_pylist(), table.column("payload").to_pylist()))
    assert set(by_id) == {"1", "2"}
    assert json.loads(by_id["1"])["ref"] == "refs/heads/master"


# org is only present on events from org-owned repos. A batch without it
# followed by a batch with it (or vice versa) must not drop rows or corrupt
# the file. buffer_size=1 forces each event into its own batch.
EVENT_WITHOUT_ORG = {
    "id": "10",
    "type": "PushEvent",
    "actor": {"id": 1, "login": "carol"},
    "repo": {"id": 9, "name": "carol/dotfiles"},
    "payload": {"size": 1},
    "created_at": "2024-01-01T00:00:00Z",
    "public": True,
}
EVENT_WITH_ORG = {
    "id": "11",
    "type": "MemberEvent",
    "actor": {"id": 2, "login": "dave"},
    "repo": {"id": 1, "name": "apache/spark"},
    "payload": {"action": "added"},
    "created_at": "2024-01-01T00:01:00Z",
    "public": True,
    "org": {"id": 47, "login": "apache"},
}


@pytest.mark.parametrize(
    "order",
    [
        [EVENT_WITHOUT_ORG, EVENT_WITH_ORG],
        [EVENT_WITH_ORG, EVENT_WITHOUT_ORG],
    ],
)
def test_parquet_handles_optional_org_across_batches(tmp_path, order):
    out = tmp_path / "events.parquet"
    writer = DataWriter(str(out))
    writer.buffer_size = 1

    for event in order:
        writer.write(event)
    writer.close()

    table = pq.read_table(str(out))
    assert table.num_rows == 2
    assert table.column("org").null_count == 1


def test_parquet_preserves_unknown_top_level_field(tmp_path):
    out = tmp_path / "events.parquet"
    writer = DataWriter(str(out))
    writer.buffer_size = 1

    writer.write(EVENT_WITHOUT_ORG)
    writer.write({**EVENT_WITHOUT_ORG, "id": "99", "experimental": {"x": 1}})
    writer.close()

    table = pq.read_table(str(out))
    assert "other" in table.schema.names
    others = dict(zip(table.column("id").to_pylist(), table.column("other").to_pylist()))
    # The plain event has no extra fields, the other one keeps them as JSON.
    assert others["10"] is None
    assert json.loads(others["99"]) == {"experimental": {"x": 1}}


def test_parquet_empty_run_writes_zero_row_file(tmp_path):
    out = tmp_path / "events.parquet"
    writer = DataWriter(str(out))
    writer.close()

    assert out.exists()
    assert pq.read_table(str(out)).num_rows == 0


def test_jsonl_empty_run_writes_empty_file(tmp_path):
    out = tmp_path / "events.jsonl"
    writer = DataWriter(str(out))
    writer.close()

    assert out.exists()
    assert out.read_text(encoding="utf-8") == ""


def test_jsonl_to_parquet_handles_optional_org_across_batches(tmp_path):
    from gharc.storage import jsonl_to_parquet

    jsonl_path = tmp_path / "events.jsonl"
    parquet_path = tmp_path / "events.parquet"
    jsonl_path.write_text(
        json.dumps(EVENT_WITHOUT_ORG) + "\n" + json.dumps(EVENT_WITH_ORG) + "\n",
        encoding="utf-8",
    )

    rows = jsonl_to_parquet(str(jsonl_path), str(parquet_path), batch_size=1)
    assert rows == 2
    assert pq.read_table(str(parquet_path)).num_rows == 2


def test_jsonl_append_preserves_existing(tmp_path):
    out = tmp_path / "events.jsonl"

    writer = DataWriter(str(out))
    writer.write(SAMPLE_EVENTS[0])
    writer.close()

    writer = DataWriter(str(out), append=True)
    writer.write(SAMPLE_EVENTS[1])
    writer.close()

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "1"
    assert json.loads(lines[1])["id"] == "2"


def test_parquet_append_into_existing_raises(tmp_path):
    out = tmp_path / "events.parquet"

    writer = DataWriter(str(out))
    writer.write(SAMPLE_EVENTS[0])
    writer.close()

    with pytest.raises(ValueError, match="JSONL"):
        DataWriter(str(out), append=True)


def test_jsonl_to_parquet_round_trip(tmp_path):
    from gharc.storage import jsonl_to_parquet

    jsonl_path = tmp_path / "events.jsonl"
    parquet_path = tmp_path / "events.parquet"

    writer = DataWriter(str(jsonl_path))
    for event in SAMPLE_EVENTS:
        writer.write(event)
    writer.close()

    rows = jsonl_to_parquet(str(jsonl_path), str(parquet_path))
    assert rows == 2

    table = pq.read_table(str(parquet_path))
    assert table.num_rows == 2
    by_id = dict(zip(table.column("id").to_pylist(), table.column("payload").to_pylist()))
    assert set(by_id) == {"1", "2"}
    assert json.loads(by_id["1"])["ref"] == "refs/heads/master"


def test_jsonl_to_parquet_skips_blank_and_malformed_lines(tmp_path):
    from gharc.storage import jsonl_to_parquet

    jsonl_path = tmp_path / "messy.jsonl"
    parquet_path = tmp_path / "events.parquet"

    jsonl_path.write_text(
        json.dumps(SAMPLE_EVENTS[0]) + "\n"
        + "\n"
        + "{ this is not valid json\n"
        + json.dumps(SAMPLE_EVENTS[1]) + "\n",
        encoding="utf-8",
    )

    rows = jsonl_to_parquet(str(jsonl_path), str(parquet_path))
    assert rows == 2


def test_jsonl_to_parquet_empty_input_writes_empty_file(tmp_path):
    from gharc.storage import jsonl_to_parquet

    jsonl_path = tmp_path / "empty.jsonl"
    parquet_path = tmp_path / "empty.parquet"
    jsonl_path.write_text("", encoding="utf-8")

    rows = jsonl_to_parquet(str(jsonl_path), str(parquet_path))
    assert rows == 0
    assert parquet_path.exists()
    assert pq.read_table(str(parquet_path)).num_rows == 0


def test_jsonl_to_parquet_refuses_same_path(tmp_path):
    from gharc.storage import jsonl_to_parquet

    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(SAMPLE_EVENTS[0]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="onto itself"):
        jsonl_to_parquet(str(path), str(path))
    # The input must survive the refused conversion.
    assert json.loads(path.read_text(encoding="utf-8"))["id"] == "1"


def test_jsonl_to_parquet_failure_keeps_previous_output(tmp_path, monkeypatch):
    from gharc import storage

    jsonl_path = tmp_path / "events.jsonl"
    parquet_path = tmp_path / "events.parquet"
    jsonl_path.write_text(json.dumps(SAMPLE_EVENTS[0]) + "\n", encoding="utf-8")
    storage.jsonl_to_parquet(str(jsonl_path), str(parquet_path))
    before = parquet_path.read_bytes()

    def boom(_events):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "_events_to_table", boom)
    with pytest.raises(OSError, match="disk full"):
        storage.jsonl_to_parquet(str(jsonl_path), str(parquet_path))

    assert parquet_path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_jsonl_to_parquet_rejects_non_positive_batch_size(tmp_path):
    from gharc.storage import jsonl_to_parquet

    jsonl_path = tmp_path / "events.jsonl"
    jsonl_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="at least 1"):
        jsonl_to_parquet(str(jsonl_path), str(tmp_path / "out.parquet"), batch_size=0)


def test_jsonl_to_parquet_keeps_an_input_named_like_a_temp_file(tmp_path):
    from gharc.storage import jsonl_to_parquet

    # Earlier builds wrote to <output>.tmp, which destroyed an input with
    # exactly that name partway through the conversion.
    jsonl_path = tmp_path / "events.parquet.tmp"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for i in range(500):
            f.write(json.dumps({**SAMPLE_EVENTS[0], "id": str(i)}) + "\n")

    rows = jsonl_to_parquet(str(jsonl_path), str(tmp_path / "events.parquet"), batch_size=100)

    assert rows == 500
    assert jsonl_path.exists()
    assert pq.read_table(str(tmp_path / "events.parquet")).num_rows == 500


def test_jsonl_to_parquet_failed_replace_leaves_no_temp_file(tmp_path, monkeypatch):
    from gharc import storage

    jsonl_path = tmp_path / "events.jsonl"
    parquet_path = tmp_path / "events.parquet"
    jsonl_path.write_text(json.dumps(SAMPLE_EVENTS[0]) + "\n", encoding="utf-8")
    storage.jsonl_to_parquet(str(jsonl_path), str(parquet_path))
    before = parquet_path.read_bytes()

    def locked(_src, _dst):
        raise PermissionError("destination is open in another program")

    monkeypatch.setattr(storage.os, "replace", locked)
    with pytest.raises(PermissionError):
        storage.jsonl_to_parquet(str(jsonl_path), str(parquet_path))

    assert parquet_path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))
