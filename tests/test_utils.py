from datetime import datetime
import pytest
from gharc.utils import parse_date, date_range, get_url_for_time


def test_parse_date_accepts_day_format():
    assert parse_date("2024-01-15") == datetime(2024, 1, 15)


def test_parse_date_accepts_hour_format():
    assert parse_date("2024-01-15-07") == datetime(2024, 1, 15, 7)


def test_parse_date_rejects_garbage():
    with pytest.raises(ValueError):
        parse_date("not-a-date")


def test_date_range_is_end_exclusive():
    start = datetime(2024, 1, 1, 0)
    end = datetime(2024, 1, 1, 3)

    hours = list(date_range(start, end))
    assert hours == [
        datetime(2024, 1, 1, 0),
        datetime(2024, 1, 1, 1),
        datetime(2024, 1, 1, 2),
    ]


def test_date_range_full_month():
    # The Spark study had a "7th month bleed-over" with the old inclusive
    # semantics. Under exclusive end, --end 2024-02-01 cleanly stops at
    # 2024-01-31 23:00 with no leakage into February.
    start = datetime(2024, 1, 1, 0)
    end = datetime(2024, 2, 1, 0)

    hours = list(date_range(start, end))
    assert len(hours) == 31 * 24
    assert hours[0] == datetime(2024, 1, 1, 0)
    assert hours[-1] == datetime(2024, 1, 31, 23)


def test_date_range_empty_when_start_equals_end():
    dt = datetime(2024, 1, 1)
    assert list(date_range(dt, dt)) == []


def test_url_format_matches_gharchive():
    dt = datetime(2024, 1, 1, 7)
    assert get_url_for_time(dt) == "https://data.gharchive.org/2024-01-01-7.json.gz"
