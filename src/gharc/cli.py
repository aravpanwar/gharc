# src/gharc/cli.py
import click
import sys
from .utils import parse_date, logger, setup_logging
from .streamer import process_range
from .storage import jsonl_to_parquet

@click.group()
def main():
    """gharc: Stream-filter GitHub Archive data."""
    setup_logging()

@main.command()
@click.option('--start', required=True, help='Start date, inclusive (YYYY-MM-DD or YYYY-MM-DD-HH)')
@click.option('--end', required=True, help='End date, exclusive (YYYY-MM-DD or YYYY-MM-DD-HH)')
@click.option('--repos', help='Comma-separated repos (e.g. apache/spark)')
@click.option('--event-types', help='Comma-separated events (e.g. PushEvent)')
@click.option('--output', default='filtered.jsonl', help='Output file')
@click.option('--workers', default=4, help='Parallel downloads')
def download(start, end, repos, event_types, output, workers):
    """Stream GHArchive over a date range and write matching events.

    Filters by repository and event type, writing Parquet or JSONL chosen by
    the --output suffix. --end is exclusive.
    """
    try:
        s_dt = parse_date(start)
        e_dt = parse_date(end)
        if s_dt >= e_dt:
            raise ValueError(
                f"--start ({start}) must be before --end ({end}); "
                f"--end is exclusive."
            )
        repo_list = [r.strip() for r in repos.split(',')] if repos else None
        type_list = [t.strip() for t in event_types.split(',')] if event_types else None
        
        process_range(s_dt, e_dt, repo_list, type_list, output, workers)
        
    except Exception as e:
        logger.error(str(e))
        sys.exit(1)


@main.command()
@click.argument('input_path', type=click.Path(exists=True, dir_okay=False))
@click.argument('output_path', type=click.Path(dir_okay=False))
@click.option('--batch-size', default=10000, help='Rows per Parquet row group')
def convert(input_path, output_path, batch_size):
    """Convert a JSONL output from `gharc download` into a single Parquet file."""
    try:
        if not output_path.endswith('.parquet'):
            logger.warning(
                f"convert always writes Parquet, but {output_path} does not end "
                f"in .parquet."
            )
        jsonl_to_parquet(input_path, output_path, batch_size=batch_size)
    except Exception as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()