from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("gharc")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

from .filters import passes_filters, fast_string_check
from .storage import DataWriter, jsonl_to_parquet
from .streamer import process_range
from .utils import parse_date, date_range, get_url_for_time, setup_logging

__all__ = [
    "__version__",
    "passes_filters",
    "fast_string_check",
    "DataWriter",
    "jsonl_to_parquet",
    "process_range",
    "parse_date",
    "date_range",
    "get_url_for_time",
    "setup_logging",
]
