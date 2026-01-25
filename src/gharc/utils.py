# src/gharc/utils.py
import logging
from datetime import datetime, timedelta
from typing import Iterator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("gharc")

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
    """Yields hourly datetimes from start to end."""
    current = start.replace(minute=0, second=0, microsecond=0)
    end_rounded = end.replace(minute=0, second=0, microsecond=0)
    
    while current < end_rounded + timedelta(hours=1):
        yield current
        current += timedelta(hours=1)

def get_url_for_time(dt: datetime) -> str:
    """
    Constructs the GHArchive URL for a specific hour.
    Example: 2024-01-01 15:00 -> https://data.gharchive.org/2024-01-01-15.json.gz
    """
    # GHArchive uses 24-hour format without leading zeros for hours 0-9? 
    # Actually checking standard GHArchive urls: 2024-01-01-1.json.gz or 01.json.gz?
    # GHArchive documentation says: {year}-{month}-{day}-{hour}.json.gz
    # Hour is usually 0-23 (no leading zero required by spec, but usually provided).
    # Let's use simple integer formatting which works for their redirects.
    return f"https://data.gharchive.org/{dt.year}-{dt.month:02d}-{dt.day:02d}-{dt.hour}.json.gz"