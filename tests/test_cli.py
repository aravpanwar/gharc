from unittest.mock import patch

from click.testing import CliRunner

from gharc import __version__
from gharc.cli import main


def test_version_flag_reports_package_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_debug_flag_is_accepted():
    result = CliRunner().invoke(main, ["--debug", "--help"])
    assert result.exit_code == 0


def test_start_not_before_end_errors():
    result = CliRunner().invoke(main, [
        "download", "--start", "2024-01-02", "--end", "2024-01-01",
        "--output", "x.jsonl",
    ])
    assert result.exit_code == 1


def test_invalid_workers_errors():
    result = CliRunner().invoke(main, [
        "download", "--start", "2024-01-01", "--end", "2024-01-02",
        "--workers", "0", "--output", "x.jsonl",
    ])
    assert result.exit_code == 1


def test_future_start_errors():
    result = CliRunner().invoke(main, [
        "download", "--start", "2999-01-01", "--end", "2999-01-02",
        "--output", "x.jsonl",
    ])
    assert result.exit_code == 1


def test_download_passes_parsed_filters_to_process_range():
    with patch("gharc.cli.process_range") as mock_pr:
        result = CliRunner().invoke(main, [
            "download", "--start", "2024-01-01", "--end", "2024-01-02",
            "--repos", "apache/spark, ,apache/*", "--orgs", "pandas-dev",
            "--actors", "bob", "--event-types", "PushEvent",
            "--output", "out.jsonl", "--workers", "2",
        ])

    assert result.exit_code == 0
    args, kwargs = mock_pr.call_args
    # The blank repo token is dropped so it cannot defeat the pre-filter.
    assert args[2] == ["apache/spark", "apache/*"]
    assert args[3] == ["PushEvent"]
    assert args[4] == "out.jsonl"
    assert args[5] == 2
    assert kwargs["orgs"] == ["pandas-dev"]
    assert kwargs["actors"] == ["bob"]


def test_convert_dispatches_to_jsonl_to_parquet(tmp_path):
    src = tmp_path / "in.jsonl"
    src.write_text('{"id": "1"}\n', encoding="utf-8")
    dst = tmp_path / "out.txt"  # non-parquet suffix should warn but still run

    with patch("gharc.cli.jsonl_to_parquet") as mock_conv:
        result = CliRunner().invoke(main, ["convert", str(src), str(dst)])

    assert result.exit_code == 0
    mock_conv.assert_called_once()
