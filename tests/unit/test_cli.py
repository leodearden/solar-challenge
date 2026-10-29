"""Tests for the CLI module."""

import io
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn
from unittest.mock import Mock

import pandas as pd
import pytest
import typer
import yaml
from rich.console import Console
from rich.progress import Progress
from rich.style import Style
from typer.testing import CliRunner, Result

import solar_challenge.cli.home as _cli_home_module
import solar_challenge.home as _home_module
from solar_challenge.cli.config import HOME_TEMPLATE
from solar_challenge.cli.main import app
from solar_challenge.cli.utils import (
    console,
    create_fleet_progress,
    create_progress,
    create_summary_table,
    error_console,
    handle_errors,
    print_error,
    print_info,
    print_report,
    print_success,
    print_warning,
    status_console,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.location import parse_location
from solar_challenge.seg import SEG_PRESETS
from solar_challenge.weather import WeatherCache, WeatherDataError
from tests._cli_fleet_simulator import invoke_cli
from tests._cli_table_text import table_text
from tests._seeded_tmy import ClearJuneDays

runner = CliRunner()

_DAY = "2024-06-21"

_JUNE_DAYS = ClearJuneDays(first_day=pd.Timestamp(_DAY), count=1)
bristol_june_tmy = _JUNE_DAYS.bristol_tmy_fixture()

_TEXT_RICH_WOULD_PARSE = "columns [ghi, dni] missing, no tag [/b] open, the :sun: set, in C:\\data\\"

_TEXT_WIDER_THAN_ANY_CONSOLE = " ".join(["Bristol"] * 60)


class TestMainCLI:
    """Tests for main CLI commands."""

    def test_help(self) -> None:
        """Test --help shows usage."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Solar Challenge" in result.stdout
        assert "home" in result.stdout
        assert "fleet" in result.stdout
        assert "validate" in result.stdout
        assert "config" in result.stdout

    def test_version(self) -> None:
        """Test --version shows version."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "solar-challenge version" in result.stdout

    def test_no_args_shows_help(self) -> None:
        """Test running with no args shows help (exit code 0 or 2 depending on Typer version)."""
        result = runner.invoke(app, [])
        # Typer's no_args_is_help can return 0 or 2 depending on version
        assert result.exit_code in (0, 2)
        assert "Usage" in result.stdout or "Solar Challenge" in result.stdout

    def test_verbose_is_refused_as_an_unknown_option(self) -> None:
        """--verbose never changed any output, so the CLI has no such option. It refuses it with a usage error, exit 2, and runs no command: config locations would otherwise print its table on stdout."""
        result = runner.invoke(app, ["--verbose", "config", "locations"])

        assert result.exit_code == 2
        assert result.stdout == ""
        assert "No such option: --verbose" in " ".join(result.stderr.split())


def _usage_line(result: Result) -> str:
    """Return the line of a --help *result*'s stdout that holds "Usage:", failing the test with the whole stdout if none does.

    The usage line names the command's positional arguments, which typer 0.26
    renders upper-case (PV_KW) and typer 0.27 lower-case in braces ({pv_kw}).
    """
    for line in result.stdout.splitlines():
        if "Usage:" in line:
            return line
    pytest.fail(f"the --help output has no Usage: line:\n{result.stdout}")


class TestHomeCLI:
    """Tests for home subcommands."""

    def test_home_help(self) -> None:
        """Test home --help."""
        result = runner.invoke(app, ["home", "--help"])
        assert result.exit_code == 0
        assert "run" in result.stdout
        assert "quick" in result.stdout

    def test_home_run_help(self) -> None:
        """Test home run --help."""
        result = runner.invoke(app, ["home", "run", "--help"])
        assert result.exit_code == 0
        assert "--start" in result.stdout
        assert "--end" in result.stdout
        assert "--output" in result.stdout
        assert "--pv-kw" in result.stdout
        assert "--battery-kwh" in result.stdout

    def test_home_quick_help(self) -> None:
        """Test home quick --help."""
        result = runner.invoke(app, ["home", "quick", "--help"])
        assert result.exit_code == 0
        assert "pv_kw" in _usage_line(result).lower()
        assert "--days" in result.stdout


class TestFleetCLI:
    """Tests for fleet subcommands."""

    def test_fleet_help(self) -> None:
        """Test fleet --help."""
        result = runner.invoke(app, ["fleet", "--help"])
        assert result.exit_code == 0
        assert "run" in result.stdout

    def test_fleet_run_help(self) -> None:
        """Test fleet run --help."""
        result = runner.invoke(app, ["fleet", "run", "--help"])
        assert result.exit_code == 0
        assert "config" in _usage_line(result).lower()
        assert "--start" in result.stdout
        assert "--output" in result.stdout


class TestConfigCLI:
    """Tests for config subcommands."""

    def test_config_help(self) -> None:
        """Test config --help."""
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0
        assert "show" in result.stdout
        assert "template" in result.stdout
        assert "locations" in result.stdout

    def test_config_template_help(self) -> None:
        """Test config template --help."""
        result = runner.invoke(app, ["config", "template", "--help"])
        assert result.exit_code == 0
        assert "home" in result.stdout.lower()
        assert "fleet" in result.stdout.lower()
        assert "scenario" in result.stdout.lower()

    def test_config_template_home(self) -> None:
        """Test config template home outputs YAML."""
        result = runner.invoke(app, ["config", "template", "home"])
        assert result.exit_code == 0
        # Check for key elements in the template
        assert "location:" in result.stdout or "latitude" in result.stdout

    def test_config_template_fleet(self) -> None:
        """Test config template fleet outputs YAML."""
        result = runner.invoke(app, ["config", "template", "fleet"])
        assert result.exit_code == 0
        assert "homes:" in result.stdout or "homes" in result.stdout

    def test_config_template_scenario(self) -> None:
        """Test config template scenario outputs YAML."""
        result = runner.invoke(app, ["config", "template", "scenario"])
        assert result.exit_code == 0
        assert "period:" in result.stdout or "period" in result.stdout

    def test_config_template_to_file(self) -> None:
        """Test config template writes to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test-config.yaml"
            result = runner.invoke(
                app, ["config", "template", "home", "-o", str(output_path)]
            )
            assert result.exit_code == 0
            assert output_path.exists()
            content = output_path.read_text()
            assert "location" in content or "pv" in content

    def test_config_template_reports_its_output_path_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An output path Rich would read as markup ([draft]) or an emoji code (:sun:) is reported as the user typed it, on stderr. The template went to the file, so stdout stays empty."""
        monkeypatch.chdir(tmp_path)
        output = "[draft] :sun:.yaml"

        result = runner.invoke(app, ["config", "template", "home", "--output", output], catch_exceptions=False)

        assert result.exit_code == 0
        assert result.stdout == ""
        assert " ".join(result.stderr.split()) == f"Template written to {output}"

    def test_config_template_invalid_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unknown template type exits 1, naming the type in red on stderr and printing nothing on stdout; recorded, because a test run is no colour terminal."""
        monkeypatch.setattr(error_console, "record", True)

        result = runner.invoke(app, ["config", "template", "invalid"])
        recorded = error_console.export_text(styles=True)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert Style.parse("red").render("Unknown template type: invalid") in recorded

    def test_an_unknown_template_type_is_reported_verbatim(self) -> None:
        """A type Rich would read as markup ([ghi, dni], [/b]) or an emoji code (:sun:), or that ends in a backslash, is reported on stderr as the user typed it."""
        result = runner.invoke(app, ["config", "template", _TEXT_RICH_WOULD_PARSE], catch_exceptions=False)

        assert result.exit_code == 1
        assert " ".join(result.stderr.split()) == (
            f"Unknown template type: {_TEXT_RICH_WOULD_PARSE} Available: home, fleet, scenario"
        )

    def test_config_show_valid_yaml(self) -> None:
        """Test config show with valid YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"
            config_path.write_text(
                """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400.0
"""
            )
            result = runner.invoke(app, ["config", "show", str(config_path)])
            assert result.exit_code == 0
            assert "4.0" in result.stdout or "capacity_kw" in result.stdout

    def test_config_show_nonexistent_file(self) -> None:
        """Test config show with nonexistent file."""
        result = runner.invoke(app, ["config", "show", "/nonexistent/file.yaml"])
        assert result.exit_code != 0

    def test_config_show_prints_its_path_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A config path Rich would read as markup ([draft]) or an emoji code (:sun:) is shown as the user typed it, after a bold label."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(console, "record", True)
        config_file = "[draft] :sun:.yaml"
        Path(config_file).write_text("home:\n  pv:\n    capacity_kw: 4.0\n")

        result = runner.invoke(app, ["config", "show", config_file], catch_exceptions=False)
        recorded = console.export_text(styles=True)

        assert result.exit_code == 0
        assert f"Configuration: {config_file}" in " ".join(result.stdout.split())
        assert Style.parse("bold").render("Configuration:") + f" {config_file}" in recorded

    def test_config_show_prints_each_parsed_key_and_value_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Keys and values Rich would read as markup ([ghi, dni], [/b]) or an emoji code (:sun:), or that end in a backslash, are summarised as written; a list as its item count."""
        monkeypatch.chdir(tmp_path)
        Path("config.yaml").write_text(
            yaml.safe_dump({"home": {"name": _TEXT_RICH_WOULD_PARSE, "[ghi, dni]": "[/b]", "panels": [1, 2, 3]}})
        )

        result = runner.invoke(app, ["config", "show", "config.yaml"], catch_exceptions=False)

        assert result.exit_code == 0
        rows = table_text(result.stdout)
        assert f"home.name {_TEXT_RICH_WOULD_PARSE}" in rows
        assert "home.[ghi, dni] [/b]" in rows
        assert "home.panels [3 items]" in rows


def _simulate_raising_a_plain_value_error(fleet_config: object, start: object, end: object) -> NoReturn:
    """A fleet simulator that raises a ValueError that is not a ConfigurationError, as a defect would."""
    raise ValueError("a plain ValueError raised while the fleet simulates")


class TestErrorHandling:
    """Tests for CLI error handling."""

    def test_missing_config_file(self) -> None:
        """Test error when config file doesn't exist."""
        result = runner.invoke(app, ["home", "run", "/nonexistent/config.yaml"])
        # Typer handles file existence check
        assert result.exit_code != 0

    def test_invalid_yaml_syntax(self) -> None:
        """Test error with invalid YAML syntax."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "invalid.yaml"
            config_path.write_text("invalid: yaml: syntax: [")
            result = runner.invoke(app, ["config", "show", str(config_path)])
            assert result.exit_code != 0

    def test_a_pvgis_failure_is_reported_in_one_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A command whose weather PVGIS cannot supply exits 1 and prints nothing on stdout. Its stderr ends, after the status line and spinner frame, with one error line naming why. It raises nothing."""
        monkeypatch.setattr(
            "solar_challenge.weather.get_pvgis_tmy", Mock(side_effect=ConnectionError("PVGIS is unreachable"))
        )

        result = runner.invoke(
            app, ["home", "run", "--start", "2024-06-21", "--end", "2024-06-21"], catch_exceptions=False
        )

        assert result.exit_code == 1
        assert result.stdout == ""
        assert " ".join(result.stderr.split()).endswith(
            "Weather data unavailable: Failed to retrieve TMY data from PVGIS: PVGIS is unreachable"
        )

    @staticmethod
    def _write_one_home_scenario(**blocks: object) -> None:
        """Write scenario.yaml in the working directory: a scenario named Bristol whose one home has 4 kW of PV and a deterministic 3400 kWh a year of load, with blocks as its other top-level blocks."""
        Path("scenario.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "Bristol",
                    "homes": [
                        {
                            "pv": {"capacity_kw": 4.0},
                            "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
                        }
                    ],
                    **blocks,
                }
            )
        )

    @pytest.mark.parametrize(
        ("finance", "refusal"),
        [
            pytest.param(
                {"loan_term_years": float("inf")},
                "loan_term_years must be a finite number, got inf",
                id="infinite-loan-term",
            ),
            pytest.param(
                {
                    "grid_services_events": {
                        "event_windows": [
                            {"months": [13], "weekdays": [0], "hours": [17], "events_per_year": 1, "event_hours": 1.0}
                        ]
                    }
                },
                "months[0] must be between 1 and 12, got 13",
                id="event-window-month-13",
            ),
            pytest.param(
                {
                    "grid_services_events": {
                        "event_windows": [
                            {
                                "months": [11],
                                "weekdays": [0],
                                "hours": [17],
                                "events_per_year": 1,
                                "event_hours": float("inf"),
                            }
                        ]
                    }
                },
                "event_hours must be a finite number, got inf",
                id="event-window-infinite-event-hours",
            ),
        ],
    )
    @pytest.mark.parametrize(
        "command",
        [
            pytest.param(("finance", "run"), id="finance-run"),
            pytest.param(("optimize", "configs"), id="optimize-configs"),
        ],
    )
    def test_a_finance_command_reports_a_refused_finance_block_as_one_configuration_error_line(
        self,
        command: tuple[str, str],
        finance: dict[str, object],
        refusal: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A finance command on a scenario whose finance block a type refuses exits 1, printing nothing on stdout and one configuration-error line on stderr: the refusal as the refusing type words it. It raises nothing."""
        monkeypatch.chdir(tmp_path)
        self._write_one_home_scenario(finance={"standing_charge_pence_per_day": 28.0, **finance})

        result = runner.invoke(app, [*command, "scenario.yaml"], catch_exceptions=False)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert " ".join(result.stderr.split()) == f"Configuration error: {refusal}"

    @pytest.mark.parametrize(
        ("blocks", "error_line"),
        [
            pytest.param(
                {},
                "Configuration error: No 'finance:' block found in the scenario file. "
                "Add a finance: block with at least standing_charge_pence_per_day.",
                id="configuration-error",
            ),
            pytest.param(
                {"finance": {"standing_charge_pence_per_day": 28.0}},
                "Invalid value: a plain ValueError raised while the fleet simulates",
                id="other-value-error",
            ),
        ],
    )
    def test_a_refusal_and_any_other_value_error_print_different_labels(
        self, blocks: dict[str, object], error_line: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`finance run` on a one-home scenario, its fleet simulated by _simulate_raising_a_plain_value_error. With no finance: block, the command refuses with a ConfigurationError before it simulates; with one, the simulator's plain ValueError reaches the command. Each exits 1 with nothing on stdout, and stderr ends with the error under its own label."""
        monkeypatch.chdir(tmp_path)
        self._write_one_home_scenario(**blocks)

        result = invoke_cli(["finance", "run", "scenario.yaml"], _simulate_raising_a_plain_value_error)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert " ".join(result.stderr.split()).endswith(error_line)

    @pytest.mark.parametrize(
        ("error_type", "label"),
        [
            pytest.param(ConfigurationError, "Configuration error", id="ConfigurationError"),
            pytest.param(FileNotFoundError, "File not found", id="FileNotFoundError"),
            pytest.param(ValueError, "Invalid value", id="ValueError"),
            pytest.param(WeatherDataError, "Weather data unavailable", id="WeatherDataError"),
        ],
    )
    def test_an_errors_text_is_printed_verbatim(
        self, capsys: pytest.CaptureFixture[str], error_type: type[Exception], label: str
    ) -> None:
        """Text Rich would read as markup ([ghi, dni], [/b]) or an emoji code (:sun:), or that ends in a backslash, prints as the error has it."""

        @handle_errors
        def fail() -> None:
            raise error_type(_TEXT_RICH_WOULD_PARSE)

        with pytest.raises(typer.Exit) as exit_:
            fail()

        assert exit_.value.exit_code == 1
        assert " ".join(capsys.readouterr().err.split()) == f"{label}: {_TEXT_RICH_WOULD_PARSE}"


class TestPrintHelpers:
    """Tests for the print_* message helpers."""

    @pytest.mark.parametrize(
        "print_message",
        [
            pytest.param(print_success, id="print_success"),
            pytest.param(print_warning, id="print_warning"),
            pytest.param(print_info, id="print_info"),
            pytest.param(print_error, id="print_error"),
        ],
    )
    def test_a_message_is_printed_verbatim_on_stderr(
        self, capsys: pytest.CaptureFixture[str], print_message: Callable[[str], None]
    ) -> None:
        """Nothing reaches stdout, which carries only a command's product. Text Rich would read as markup ([ghi, dni], [/b]) or an emoji code (:sun:), or that ends in a backslash, prints on stderr as the caller gave it."""
        print_message(_TEXT_RICH_WOULD_PARSE)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert " ".join(captured.err.split()) == _TEXT_RICH_WOULD_PARSE

    @pytest.mark.parametrize(
        ("print_message", "target", "colour"),
        [
            pytest.param(print_success, status_console, "green", id="print_success"),
            pytest.param(print_warning, error_console, "yellow", id="print_warning"),
            pytest.param(print_info, status_console, "blue", id="print_info"),
            pytest.param(print_error, error_console, "red", id="print_error"),
        ],
    )
    def test_a_message_is_printed_in_its_colour_on_its_console(
        self, monkeypatch: pytest.MonkeyPatch, print_message: Callable[[str], None], target: Console, colour: str
    ) -> None:
        """Success prints green and info blue on the status console, and warning yellow and error red on the error console, all on stderr; recorded, because a test run is no colour terminal."""
        monkeypatch.setattr(target, "record", True)

        print_message("saved")

        assert target.export_text(styles=True) == Style.parse(colour).render("saved") + "\n"


class TestProgress:
    """Tests for the progress displays a command shows while it simulates."""

    @pytest.mark.parametrize(
        "create",
        [
            pytest.param(create_progress, id="create_progress"),
            pytest.param(create_fleet_progress, id="create_fleet_progress"),
        ],
    )
    def test_progress_is_printed_on_stderr(
        self, capsys: pytest.CaptureFixture[str], create: Callable[[], Progress]
    ) -> None:
        """Progress prints on stderr, so stdout carries only a command's product."""
        with create() as progress:
            progress.add_task("Simulating 2 homes...", total=2)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Simulating 2 homes..." in captured.err

    @pytest.mark.parametrize(
        "create",
        [
            pytest.param(create_progress, id="create_progress"),
            pytest.param(create_fleet_progress, id="create_fleet_progress"),
        ],
    )
    def test_a_display_on_the_quiet_status_console_leaves_other_stderr_output_alone_on_a_terminal(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, create: Callable[[], Progress]
    ) -> None:
        """Text written on stderr while a display on the quiet status console runs still prints, even on a terminal. TTY_COMPATIBLE=1 makes Rich treat the captured stderr as a terminal."""
        monkeypatch.setenv("TTY_COMPATIBLE", "1")
        monkeypatch.setattr(status_console, "quiet", True)

        with create() as progress:
            progress.add_task("Simulating 2 homes...", total=2)
            print("richardsonpy fell back to the Elexon profile", file=sys.stderr)

        assert capsys.readouterr().err == "richardsonpy fell back to the Elexon profile\n"


class TestPrintReport:
    """Tests that print_report prints a report on stdout exactly as it is."""

    def test_a_report_is_printed_on_stdout_exactly_as_it_is(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Every line prints whole, however much wider than the console: a spaced table row is not wrapped and a separator is not folded mid-word. Text Rich would read as markup or an emoji code prints verbatim, and print_report adds only the final newline."""
        report = (
            f"# {_TEXT_RICH_WOULD_PARSE}\n"
            "\n"
            f"| {_TEXT_WIDER_THAN_ANY_CONSOLE} |\n"
            f"|{'-' * len(_TEXT_WIDER_THAN_ANY_CONSOLE)}|\n"
        )

        print_report(report)

        assert capsys.readouterr().out == report + "\n"


class TestCLIOutputFormats:
    """Tests for CLI output generation."""

    def test_template_generates_valid_yaml(self) -> None:
        """Test that generated templates are valid YAML."""
        for template_type in ["home", "fleet", "scenario"]:
            result = runner.invoke(app, ["config", "template", template_type])
            assert result.exit_code == 0

            # Extract YAML content (may have ANSI codes from Rich)
            # The actual content is in the output
            # For CLI output, we need to write to file to get clean YAML
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / f"{template_type}.yaml"
                result = runner.invoke(
                    app, ["config", "template", template_type, "-o", str(output_path)]
                )
                assert result.exit_code == 0

                content = output_path.read_text()
                # Should be valid YAML
                parsed = yaml.safe_load(content)
                assert parsed is not None
                assert isinstance(parsed, dict)


class TestCreateSummaryTableTitle:
    """Tests that create_summary_table prints its title exactly as given, in Rich's table-title style."""

    def _rows(self) -> tuple[tuple[str, str], ...]:
        """The rows of a home's five energy totals."""
        return (
            ("Total Generation", "10.0 kWh"),
            ("Total Demand", "8.0 kWh"),
            ("Self-Consumption", "6.0 kWh"),
            ("Grid Import", "2.0 kWh"),
            ("Grid Export", "4.0 kWh"),
        )

    def test_a_title_is_printed_verbatim(self) -> None:
        """A title Rich would read as markup ([ghi, dni], [/b]) or an emoji code (:sun:), or that ends in a backslash, prints as the caller gave it.

        The title wraps over several centred lines at the table's width; folding whitespace rejoins it.
        """
        buffer = io.StringIO()

        Console(file=buffer, width=80).print(create_summary_table(self._rows(), title=_TEXT_RICH_WOULD_PARSE))

        assert _TEXT_RICH_WOULD_PARSE in " ".join(buffer.getvalue().split())

    def test_a_title_is_printed_in_the_table_title_style(self) -> None:
        """The title is italic, as Rich styles a table's title; centring pads it inside the same span, so the segment's style is compared."""
        segments = Console(width=80).render(create_summary_table(self._rows(), title="Results"))

        assert any("Results" in s.text and s.style is not None and s.style.italic for s in segments)


@pytest.mark.usefixtures("bristol_june_tmy")
class TestHomeRunFullConfigParity:
    """Tests that `home run` threads tariff + SEG via canonical parser (step-3/step-4)."""

    def _write_home_config(self, tmp_dir: Path, seg_yaml: str) -> Path:
        """Write a temp YAML config with tariff, followed by *seg_yaml*.

        Uses economy_7 (not flat_rate) because flat_rate has a known gap at 23:59
        that causes a simulation error on a full-day run; economy_7 fully covers
        all 24 hours via a midnight-crossing peak period.
        """
        cfg_path = tmp_dir / "home_seg.yaml"
        cfg_path.write_text(
            """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 3400
    use_stochastic: false
  tariff:
    type: economy_7

"""
            + seg_yaml
        )
        return cfg_path

    def _run_home(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        seg_yaml: str,
        *extra_args: str,
    ) -> tuple[Result, dict[str, HomeConfig]]:
        """Run `home run --report` for _DAY on a config ending in *seg_yaml*.

        *extra_args* are appended to the command line after ``--report``.
        Returns the CLI result and the spy's capture; ``captured["home_config"]``
        is the HomeConfig passed to simulate_home, absent if it was never called.
        """
        # Capture the home_config passed to simulate_home by wrapping the real function
        captured: dict[str, HomeConfig] = {}
        real_simulate_home = _home_module.simulate_home

        def spy_simulate_home(home_config, *args, **kwargs):  # type: ignore[no-untyped-def]
            captured["home_config"] = home_config
            return real_simulate_home(home_config, *args, **kwargs)

        # Patch simulate_home in the CLI module (local binding)
        monkeypatch.setattr(_cli_home_module, "simulate_home", spy_simulate_home)

        cfg_path = self._write_home_config(tmp_path, seg_yaml)
        result = runner.invoke(
            app,
            [
                "home", "run", str(cfg_path),
                "--start", _DAY,
                "--end", _DAY,
                "--report",
                *extra_args,
            ],
            catch_exceptions=False,
        )
        return result, captured

    def test_home_run_threads_tariff_and_seg(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """home run passes tariff + seg to simulate_home and reports SEG Revenue."""
        result, captured = self._run_home(
            monkeypatch, tmp_path, "seg:\n  rate_pence_per_kwh: 15.0\n"
        )

        assert result.exit_code == 0, f"CLI failed: {result.stdout}"

        # Tariff must be honoured by the canonical parser
        home_cfg = captured.get("home_config")
        assert home_cfg is not None, "spy was not called"
        assert home_cfg.tariff_config is not None, (
            "tariff_config should not be None — canonical parser must pick it up"
        )

        # SEG must be threaded onto the HomeConfig
        assert home_cfg.seg_tariff is not None, (
            "seg_tariff should not be None — SEG must be threaded from top-level seg block"
        )
        assert home_cfg.seg_tariff.rate_pence_per_kwh == 15.0

        # SEG Revenue section must appear in the --report output
        assert "SEG Revenue" in result.stdout, (
            "generate_summary_report must include a SEG Revenue section"
        )

    def test_home_run_resolves_seg_preset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A top-level ``seg: {preset: Octopus}`` block prices exports at Octopus's rate."""
        result, captured = self._run_home(monkeypatch, tmp_path, "seg:\n  preset: Octopus\n")

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        seg_tariff = captured["home_config"].seg_tariff
        assert seg_tariff is not None
        assert seg_tariff.rate_pence_per_kwh == SEG_PRESETS["Octopus"].rate_pence_per_kwh
        assert "SEG Revenue" in result.stdout

    def test_home_run_rejects_unknown_seg_preset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An unknown SEG preset is refused with exit 1 before anything is simulated."""
        result, captured = self._run_home(monkeypatch, tmp_path, "seg:\n  preset: Nonexistent\n")

        assert result.exit_code == 1
        assert "Nonexistent" in result.output
        assert "home_config" not in captured

    def test_home_run_location_option_reaches_home_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, weather_cache: WeatherCache
    ) -> None:
        """``--location`` places the simulated home where location.parse_location puts it."""
        edinburgh = parse_location("55.95,-3.19")
        weather_cache.put(_JUNE_DAYS.hourly_weather(), "tmy", edinburgh)

        result, captured = self._run_home(
            monkeypatch,
            tmp_path,
            "seg:\n  rate_pence_per_kwh: 15.0\n",
            "--location",
            "55.95,-3.19",
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert captured["home_config"].location == edinburgh


@pytest.fixture
def clear_june_in_tmp_path(
    bristol_june_tmy: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Work in tmp_path, where each test writes its config."""
    monkeypatch.chdir(tmp_path)


def _run_home_named(home_name: str, *options: str) -> Result:
    """Run `home run` with options for _DAY on home.yaml, written in the working directory: a home named home_name with 4 kW of PV and a deterministic 3400 kWh a year of load."""
    Path("home.yaml").write_text(
        yaml.safe_dump(
            {
                "home": {
                    "name": home_name,
                    "pv": {"capacity_kw": 4.0},
                    "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
                }
            }
        )
    )

    return runner.invoke(
        app,
        ["home", "run", "home.yaml", "--start", _DAY, "--end", _DAY, *options],
        catch_exceptions=False,
    )


def _write_scenario(scenario_name: str) -> None:
    """Write scenario.yaml in the working directory: a scenario named scenario_name whose one home has 4 kW of PV, a 5 kWh battery and a deterministic 3400 kWh a year of load, with a finance block charging 28p a day."""
    Path("scenario.yaml").write_text(
        yaml.safe_dump(
            {
                "name": scenario_name,
                "homes": [
                    {
                        "pv": {"capacity_kw": 4.0},
                        "battery": {"capacity_kwh": 5.0},
                        "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
                    }
                ],
                "finance": {"standing_charge_pence_per_day": 28.0},
            }
        )
    )


def _run_finance(scenario_name: str) -> Result:
    """Run `finance run` for _DAY on the scenario _write_scenario writes, named scenario_name."""
    _write_scenario(scenario_name)

    return runner.invoke(
        app,
        ["finance", "run", "scenario.yaml", "--start", _DAY, "--end", _DAY],
        catch_exceptions=False,
    )


def _run_optimize_configs() -> Result:
    """Run `optimize configs` for _DAY on the scenario _write_scenario writes, named Bristol: a sweep of the one config with 4 kW of PV, no battery and a 5 kW inverter, and no sensitivity panel."""
    _write_scenario("Bristol")

    return runner.invoke(
        app,
        [
            "optimize", "configs", "scenario.yaml",
            "--pv", "4", "--battery", "0", "--inverter", "5", "--sensitivity", "",
            "--start", _DAY, "--end", _DAY,
        ],
        catch_exceptions=False,
    )


@pytest.mark.usefixtures("clear_june_in_tmp_path")
class TestReportsPrintNamesVerbatim:
    """Tests that the report commands print the names a config gives exactly as written."""

    @pytest.mark.parametrize(
        ("options", "title"),
        [
            pytest.param((), "Simulation Results:", id="summary-table"),
            pytest.param(("--report",), "# Simulation Report:", id="report"),
        ],
    )
    def test_home_run_prints_the_homes_name_verbatim(self, options: tuple[str, ...], title: str) -> None:
        """A home name Rich would read as markup ([ghi, dni], [/b]) or an emoji code (:sun:), or that ends in a backslash, titles the summary table, or with --report the report, as written."""
        result = _run_home_named(_TEXT_RICH_WOULD_PARSE, *options)

        assert result.exit_code == 0
        assert f"{title} {_TEXT_RICH_WOULD_PARSE}" in " ".join(result.stdout.split())

    def test_finance_run_prints_the_scenarios_name_verbatim(self) -> None:
        """A scenario name Rich would read as markup ([ghi, dni], [/b]) or an emoji code (:sun:), or that ends in a backslash, titles the report as written."""
        result = _run_finance(_TEXT_RICH_WOULD_PARSE)

        assert result.exit_code == 0
        assert f"# Finance Report: {_TEXT_RICH_WOULD_PARSE}" in " ".join(result.stdout.split())


@pytest.mark.usefixtures("clear_june_in_tmp_path")
class TestReportsPrintEachLineWhole:
    """Tests that the report commands print each line of their markdown report whole, however much wider than the console."""

    def test_home_run_prints_a_report_title_wider_than_the_console_on_one_line(self) -> None:
        """A home name wider than any console titles the report on one printed line, not wrapped across several."""
        result = _run_home_named(_TEXT_WIDER_THAN_ANY_CONSOLE, "--report")

        assert result.exit_code == 0
        assert f"# Simulation Report: {_TEXT_WIDER_THAN_ANY_CONSOLE}" in result.stdout.splitlines()

    def test_finance_run_prints_a_report_title_wider_than_the_console_on_one_line(self) -> None:
        """A scenario name wider than any console titles the report on one printed line, not wrapped across several."""
        result = _run_finance(_TEXT_WIDER_THAN_ANY_CONSOLE)

        assert result.exit_code == 0
        assert f"# Finance Report: {_TEXT_WIDER_THAN_ANY_CONSOLE}" in result.stdout.splitlines()

    def test_optimize_configs_prints_each_table_row_on_one_line(self) -> None:
        """Each markdown table row closes on the line it opens on, the Cost-Recovery Rank rows included, though they are about twice as wide as the 80 columns Rich gives a console with no terminal."""
        result = _run_optimize_configs()

        assert result.exit_code == 0
        table_rows = [line for line in result.stdout.splitlines() if line.startswith("|")]
        assert [row for row in table_rows if not row.endswith("|")] == []
        assert max(map(len, table_rows), default=0) > 80


@pytest.mark.usefixtures("clear_june_in_tmp_path")
class TestCommandsPrintOnlyTheirProductOnStdout:
    """Tests that a command prints its product alone on stdout, and its status lines and progress on stderr, so redirecting stdout to a file captures the product alone."""

    def test_home_run_prints_its_summary_table_alone_on_stdout(self) -> None:
        """The summary table, whose title Rich centres above it, opens stdout. The status line and the spinner print on stderr."""
        result = _run_home_named("Bristol")

        assert result.exit_code == 0
        assert result.stdout.splitlines()[0].strip() == "Simulation Results: Bristol"
        status = " ".join(result.stderr.split())
        assert f"Simulating 1 days from {_DAY} to {_DAY}" in status
        assert "Running simulation..." in status

    def test_home_run_report_prints_the_report_in_place_of_the_summary_table(self) -> None:
        """The report opens stdout, and the summary table is printed on neither stream, since the report carries every one of its figures."""
        result = _run_home_named("Bristol", "--report")

        assert result.exit_code == 0
        assert result.stdout.startswith("# Simulation Report: Bristol\n")
        assert "Simulation Results" not in result.output

    def test_fleet_run_prints_its_results_table_alone_on_stdout(self) -> None:
        """The fleet results table, whose title Rich centres above it, opens stdout. The status line and the progress bar print on stderr."""
        _write_scenario("Bristol")

        result = runner.invoke(
            app,
            ["fleet", "run", "scenario.yaml", "--start", _DAY, "--end", _DAY],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert result.stdout.splitlines()[0].strip() == "Fleet Results: Bristol"
        status = " ".join(result.stderr.split())
        assert "Simulating fleet of 1 homes for 1 days" in status
        assert "Simulating 1 homes..." in status

    def test_finance_run_prints_its_report_alone_on_stdout(self) -> None:
        """The finance report opens stdout. The status lines print on stderr."""
        result = _run_finance("Bristol")

        assert result.exit_code == 0
        assert result.stdout.startswith("# Finance Report: Bristol\n")
        assert "Simulating fleet of 1 homes for 1 days…" in " ".join(result.stderr.split())

    def test_optimize_configs_prints_its_report_alone_on_stdout(self) -> None:
        """The ranking report opens stdout. The status lines print on stderr."""
        result = _run_optimize_configs()

        assert result.exit_code == 0
        assert result.stdout.startswith("## Cost-Recovery Rank\n")
        assert "Sweep complete: 1 feasible config(s), 0 infeasible config(s)." in " ".join(result.stderr.split())


_ECONOMY_7_TARIFF = {
    "type": "economy_7",
    "off_peak_rate": 0.09,
    "peak_rate": 0.25,
    "off_peak_start": "00:30",
    "off_peak_end": "07:30",
}

# Each way `fleet sweep` sweeps a fleet file's battery capacity: the file's capacity_kwh,
# the options that sweep it, and the file its 5 kWh point is exported to.
_SWEEP_PATHS = (
    pytest.param(
        {
            "type": "proportional_to",
            "source": "pv.capacity_kw",
            "multiplier": {"type": "sweep", "min": 1.25, "max": 2.5, "steps": 2, "mode": "linear"},
        },
        (),
        "multiplier_1.2500.csv",
        id="yaml-sweep",
    ),
    pytest.param(
        "${CAP}",
        ("--param", "CAP", "--min", "5", "--max", "10", "--steps", "2", "--mode", "linear"),
        "CAP_5.0000.csv",
        id="param-sweep",
    ),
)


def _write_fleet_file(file_name: str, capacity_kwh: object, tariff: dict[str, object]) -> None:
    """Write file_name in the working directory: a fleet file under the top-level tariff, of two tou_optimized homes with 4 kW of PV, a deterministic 3400 kWh a year of load, and a battery of capacity_kwh that charges and discharges at 2.5 kW and grid-charges to 90%."""
    Path(file_name).write_text(
        yaml.safe_dump(
            {
                "tariff": tariff,
                "fleet_distribution": {
                    "n_homes": 2,
                    "seed": 42,
                    "pv": {"capacity_kw": 4.0},
                    "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
                    "dispatch_strategy": "tou_optimized",
                    "battery": {
                        "max_charge_kw": 2.5,
                        "max_discharge_kw": 2.5,
                        "grid_charging": {"target_soc_fraction": 0.9},
                        "capacity_kwh": capacity_kwh,
                    },
                },
            }
        )
    )


def _run_fleet(*argv: str) -> Result:
    """Run the `fleet` command argv for _DAY, simulating its homes one after another."""
    return runner.invoke(
        app,
        ["fleet", *argv, "--start", _DAY, "--end", _DAY, "--sequential"],
        catch_exceptions=False,
    )


@pytest.mark.usefixtures("clear_june_in_tmp_path")
class TestFleetSweepGivesEachPointTheFleetFilesBlocks:
    """Tests that `fleet sweep`, on either sweep path, gives every point's homes the fleet file's top-level blocks as `fleet run` gives them."""

    @pytest.mark.parametrize(("capacity_kwh", "options", "point_file"), _SWEEP_PATHS)
    def test_a_sweep_point_simulates_the_fleet_fleet_run_simulates(
        self, capacity_kwh: object, options: tuple[str, ...], point_file: str
    ) -> None:
        """The CSV `fleet sweep` exports for its 5 kWh point holds exactly the values of the CSV `fleet run` exports for the same fleet file with a 5 kWh battery.

        The frames are compared, not the texts: pytest's diff of two long CSV texts that differ takes minutes to report.
        """
        _write_fleet_file("run.yaml", 5.0, _ECONOMY_7_TARIFF)
        _write_fleet_file("sweep.yaml", capacity_kwh, _ECONOMY_7_TARIFF)

        fleet_run = _run_fleet("run", "run.yaml", "--output", "run.csv")
        fleet_sweep = _run_fleet("sweep", "sweep.yaml", "--output-dir", "sweep", *options)

        assert fleet_run.exit_code == 0, fleet_run.output
        assert fleet_sweep.exit_code == 0, fleet_sweep.output
        pd.testing.assert_frame_equal(
            pd.read_csv(Path("sweep", point_file)), pd.read_csv("run.csv"), check_exact=True
        )

    @pytest.mark.parametrize(("capacity_kwh", "options", "point_file"), _SWEEP_PATHS)
    def test_a_sweep_of_a_file_whose_tariff_the_loader_refuses_is_refused(
        self, capacity_kwh: object, options: tuple[str, ...], point_file: str
    ) -> None:
        """`fleet sweep` refuses a tariff: block `fleet run` refuses, with exit 1, before it simulates any point."""
        _write_fleet_file("sweep.yaml", capacity_kwh, {"type": "economy_8"})

        result = _run_fleet("sweep", "sweep.yaml", "--output-dir", "sweep", *options)

        assert result.exit_code == 1
        assert "Unknown tariff type 'economy_8'" in " ".join(result.stderr.split())
        assert not Path("sweep", point_file).exists()
        assert not Path("sweep", "sweep_summary.csv").exists()


class TestFleetSweepRefusesAFileItCannotSweep:
    """Tests that `fleet sweep` refuses a fleet file with nothing it can sweep, with exit 1 and the reason."""

    @pytest.mark.parametrize(
        ("document", "options", "refusal"),
        [
            pytest.param(
                "homes:\n  - pv: {capacity_kw: 4.0}\n",
                (),
                "Sweep requires fleet_distribution config",
                id="homes-yaml-sweep",
            ),
            pytest.param(
                "homes:\n  - pv: {capacity_kw: 4.0}\n",
                ("--param", "CAP", "--min", "5", "--max", "10", "--steps", "2"),
                "Sweep requires fleet_distribution config",
                id="homes-param-sweep",
            ),
            pytest.param(
                "fleet_distribution:\n  n_homes: 2\n  pv: {capacity_kw: 4.0}\n",
                (),
                "No sweep spec found in config. Use --param for CLI sweep or add type: sweep to multiplier.",
                id="fleet-distribution-without-a-sweep",
            ),
            pytest.param(
                "fleet_distribution:\n  n_homes: 2\n  pv: {capacity_kw: 4.0}\n  battery:\n"
                "    capacity_kwh: {type: proportional_to, source: pv.capacity_kw, multiplier: '${BATTERY_RATIO:1.0}'}\n",
                ("--param", "BATTERY_RATI0", "--min", "0.5", "--max", "2", "--steps", "2"),
                "Variables with no placeholder in the document: 'BATTERY_RATI0'; "
                "its placeholders: 'BATTERY_RATIO' at fleet_distribution.battery.capacity_kwh.multiplier",
                id="param-sweep-of-a-variable-no-placeholder-names",
            ),
        ],
    )
    def test_a_file_it_cannot_sweep_is_refused(
        self, tmp_path: Path, document: str, options: tuple[str, ...], refusal: str
    ) -> None:
        fleet_file = tmp_path / "fleet.yaml"
        fleet_file.write_text(document)

        result = _run_fleet("sweep", str(fleet_file), *options)

        assert result.exit_code == 1
        assert refusal in " ".join(result.stderr.split())


class TestQuietOption:
    """Tests that --quiet silences a command's status messages and progress on stderr, and leaves its product, its warnings and its errors."""

    @pytest.fixture(autouse=True)
    def _restore_status_quiet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CliRunner runs every invocation in this process, on the one status_console, so a --quiet invocation here must not silence a later test."""
        monkeypatch.setattr(status_console, "quiet", status_console.quiet)

    def test_quiet_config_template_writes_its_file_and_prints_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The template still goes to its file, but the status line that reports where is not printed, so neither stream carries anything."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["--quiet", "config", "template", "home", "--output", "x.yaml"], catch_exceptions=False
        )

        assert result.exit_code == 0
        assert (result.stdout, result.stderr) == ("", "")
        assert Path("x.yaml").read_text() == HOME_TEMPLATE

    def test_quiet_leaves_an_error_on_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A command whose weather PVGIS cannot supply still exits 1 with its one error line, and that line is all stderr carries: the status line and spinner frame that would come first are not printed."""
        monkeypatch.setattr(
            "solar_challenge.weather.get_pvgis_tmy", Mock(side_effect=ConnectionError("PVGIS is unreachable"))
        )

        result = runner.invoke(
            app,
            ["--quiet", "home", "run", "--start", "2024-06-21", "--end", "2024-06-21"],
            catch_exceptions=False,
        )

        assert result.exit_code == 1
        assert result.stdout == ""
        assert " ".join(result.stderr.split()) == (
            "Weather data unavailable: Failed to retrieve TMY data from PVGIS: PVGIS is unreachable"
        )

    @pytest.mark.usefixtures("clear_june_in_tmp_path")
    def test_quiet_leaves_a_warning_on_stderr(self) -> None:
        """A fleet run asked for a community report its scenario has no community: block for still warns that it ignored the request, and that warning is all stderr carries."""
        _write_scenario("Bristol")

        result = runner.invoke(
            app,
            [
                "--quiet", "fleet", "run", "scenario.yaml", "--start", _DAY, "--end", _DAY,
                "--community-report", "community.md",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert " ".join(result.stderr.split()) == "--community-report ignored: config has no community: block"

    @pytest.mark.usefixtures("clear_june_in_tmp_path")
    def test_quiet_leaves_the_product_on_stdout(self) -> None:
        """The fleet results table still opens stdout, while the status line and the progress bar are not printed on stderr."""
        _write_scenario("Bristol")

        result = runner.invoke(
            app,
            ["--quiet", "fleet", "run", "scenario.yaml", "--start", _DAY, "--end", _DAY],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert result.stdout.splitlines()[0].strip() == "Fleet Results: Bristol"
        assert result.stderr == ""

    def test_quiet_silences_only_its_own_invocation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An invocation without --quiet after one with it, in the same process, prints its status line again."""
        monkeypatch.chdir(tmp_path)

        quiet = runner.invoke(
            app, ["--quiet", "config", "template", "home", "--output", "quiet.yaml"], catch_exceptions=False
        )
        loud = runner.invoke(app, ["config", "template", "home", "--output", "loud.yaml"], catch_exceptions=False)

        assert quiet.stderr == ""
        assert " ".join(loud.stderr.split()) == "Template written to loud.yaml"
