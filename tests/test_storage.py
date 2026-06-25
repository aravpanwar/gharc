import json
import pyarrow.parquet as pq
import pytest
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
    # Read at the pyarrow level so nulls come back as None across pandas versions.
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
    df = table.to_pandas()
    assert len(df) == 2
    assert set(df["id"].astype(str)) == {"1", "2"}
    payload = json.loads(df.iloc[0]["payload"])
    assert payload["ref"] == "refs/heads/master"


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


def test_jsonl_to_parquet_streams_large_input(tmp_path):
    from gharc.storage import jsonl_to_parquet

    jsonl_path = tmp_path / "many.jsonl"
    parquet_path = tmp_path / "many.parquet"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for i in range(2500):
            f.write(json.dumps({**SAMPLE_EVENTS[0], "id": str(i)}) + "\n")

    rows = jsonl_to_parquet(str(jsonl_path), str(parquet_path), batch_size=500)
    assert rows == 2500
    assert pq.read_table(str(parquet_path)).num_rows == 2500
