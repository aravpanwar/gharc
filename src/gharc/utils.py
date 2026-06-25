# src/gharc/utils.py
import logging
from datetime import datetime, timedelta
from typing import Iterator

logger = logging.getLogger("gharc")


def setup_logging(level: int = logging.INFO) -> None:
    """Attach a console handler to the gharc logger. Safe to call twice."""
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
    ))
    logger.addHandler(handler)
    logger.setLevel(level)

def parse_date(date_str: str) -> datetime:
    """Parses YYYY-MM-DD or YYYY-MM-DD-HH"""
    try:
        if len(date_str.split('-')) == 3:
            return datetime.strptime(date_str, "%Y-%m-%d")
        else:
            return datetime.strptime(date_str, "%Y-%m-%d-%H")
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD or YYYY-MM-DD-HH")

def date_range(start: datetime, end: datetime) -> Iterator[datetime]:
    """Yields hourly datetimes in [start, end). End is exclusive.

    Use --end 2024-02-01 to cover all of January 2024.
    """
    current = start.replace(minute=0, second=0, microsecond=0)
    end_rounded = end.replace(minute=0, second=0, microsecond=0)

    while current < end_rounded:
        yield current
        current += timedelta(hours=1)

def get_url_for_time(dt: datetime) -> str:
    """Construct the GHArchive URL for a specific hour.

    GHArchive names files {year}-{month}-{day}-{hour}.json.gz with the hour not
    zero-padded, so 2024-01-01 15:00 maps to
    https://data.gharchive.org/2024-01-01-15.json.gz and the 00:00 hour to
    ...-2024-01-01-0.json.gz.
    """
    return f"https://data.gharchive.org/{dt.year}-{dt.month:02d}-{dt.day:02d}-{dt.hour}.json.gz"