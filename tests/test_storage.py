import json
import pyarrow.parquet as pq
from gharc.storage import DataWriter


SAMPLE_EVENTS = [
    {
        "id": "1",
        "type": "PushEvent",
        "actor": {"id": 100, "login": "alice"},
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
    df = table.to_pandas()
    assert len(df) == 2
    assert set(df["id"].astype(str)) == {"1", "2"}

    payload = json.loads(df.iloc[0]["payload"])
    assert payload["ref"] == "refs/heads/master"


def test_parquet_handles_heterogeneous_event_types(tmp_path):
    out = tmp_path / "events.parquet"
    writer = DataWriter(str(out))
    writer.buffer_size = 1

    for event in SAMPLE_EVENTS:
        writer.write(event)
    writer.close()

    table = pq.read_table(str(out))
    assert table.num_rows == 2
