# src/gharc/cli.py
import click
import logging
import sys
from datetime import datetime
from . import __version__
from .utils import parse_date, logger, setup_logging
from .streamer import process_range
from .storage import jsonl_to_parquet


def _split_csv(raw):
    """Split a comma-separated option into a clean list, dropping blanks.

    Returns None when nothing usable is left. This keeps a value like
    "apache/spark,,foo" from leaving an empty token, which would make the
    byte-level pre-filter match every line and quietly lose the optimization.
    """
    if not raw:
        return None
    items = [part.strip() for part in raw.split(',') if part.strip()]
    return items or None


@click.group()
@click.version_option(version=__version__, prog_name="gharc")
@click.option('--debug', is_flag=True, help='Enable verbose debug logging.')
def main(debug):
    """gharc: Stream-filter GitHub Archive data."""
    setup_logging(logging.DEBUG if debug else logging.INFO)

@main.command()
@click.option('--start', required=True, help='Start date, inclusive (YYYY-MM-DD or YYYY-MM-DD-HH)')
@click.option('--end', required=True, help='End date, exclusive (YYYY-MM-DD or YYYY-MM-DD-HH)')
@click.option('--repos', help='Comma-separated repos; supports owner/* wildcards (e.g. apache/spark, apache/*)')
@click.option('--orgs', help='Comma-separated repository owners to keep (e.g. apache)')
@click.option('--actors', help='Comma-separated actor logins to keep (e.g. dongjoon-hyun)')
@click.option('--event-types', help='Comma-separated events (e.g. PushEvent)')
@click.option('--output', default='filtered.jsonl', help='Output file')
@click.option('--workers', default=4, help='Parallel downloads')
def download(start, end, repos, orgs, actors, event_types, output, workers):
    """Stream GHArchive over a date range and write matching events.

    Filters by repository, owner, actor, and event type, writing Parquet or
    JSONL chosen by the --output suffix. --end is exclusive. Dates are UTC.
    """
    try:
        s_dt = parse_date(start)
        e_dt = parse_date(end)
        if s_dt >= e_dt:
            raise ValueError(
                f"--start ({start}) must be before --end ({end}); "
                f"--end is exclusive."
            )
        if workers < 1:
            raise ValueError(f"--workers must be at least 1 (got {workers}).")
        now = datetime.utcnow()
        if s_dt >= now:
            raise ValueError(
                f"--start ({start}) is in the future; GHArchive has no data for "
                f"that window yet. Dates are UTC."
            )
        if e_dt > now:
            logger.warning(
                "--end is in the future or very recent; GHArchive publishes each "
                "hour a little after it ends, so the latest hours may be missing."
            )
        repo_list = _split_csv(repos)
        type_list = _split_csv(event_types)
        org_list = _split_csv(orgs)
        actor_list = _split_csv(actors)

        if s_dt < datetime(2015, 1, 1) and (repo_list or org_list):
            logger.warning(
                "Window starts before 2015-01-01, where GHArchive uses the older "
                "Timeline schema without repo.name; repository and owner filters "
                "may match nothing for those hours."
            )

        process_range(s_dt, e_dt, repo_list, type_list, output, workers,
                      orgs=org_list, actors=actor_list)

    except Exception as e:
        logger.error(str(e))
        logger.debug("Full traceback:", exc_info=True)
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
        logger.debug("Full traceback:", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()