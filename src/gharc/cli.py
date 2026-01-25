# src/gharc/cli.py
import click
import sys
from .utils import parse_date, logger
from .streamer import process_range

@click.group()
def main():
    """gharc: Stream-filter GitHub Archive data."""
    pass

@main.command()
@click.option('--start', required=True, help='Start date (YYYY-MM-DD-HH)')
@click.option('--end', required=True, help='End date (YYYY-MM-DD-HH)')
@click.option('--repos', help='Comma-separated repos (e.g. apache/spark)')
@click.option('--event-types', help='Comma-separated events (e.g. PushEvent)')
@click.option('--output', default='filtered.jsonl', help='Output file')
@click.option('--workers', default=4, help='Parallel downloads')
def download(start, end, repos, event_types, output, workers):
    try:
        s_dt = parse_date(start)
        e_dt = parse_date(end)
        repo_list = [r.strip() for r in repos.split(',')] if repos else None
        type_list = [t.strip() for t in event_types.split(',')] if event_types else None
        
        process_range(s_dt, e_dt, repo_list, type_list, output, workers)
        
    except Exception as e:
        logger.error(str(e))
        sys.exit(1)