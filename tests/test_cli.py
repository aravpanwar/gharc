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
