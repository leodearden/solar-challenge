"""Tests for the CLI module."""

import io
import tempfile
import types
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import yaml
from rich.console import Console
from typer.testing import CliRunner, Result

import solar_challenge.cli.home as _cli_home_module
import solar_challenge.home as _home_module
from solar_challenge.cli.main import app
from solar_challenge.cli.utils import create_summary_table, parse_location
from solar_challenge.home import HomeConfig, SummaryStatistics
from solar_challenge.location import Location
from solar_challenge.seg import SEG_PRESETS
from solar_challenge.weather import WeatherCache
from tests._synthetic_weather import synthetic_june_weather

runner = CliRunner()


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
        assert "PV_KW" in result.stdout
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
        assert "CONFIG" in result.stdout
        assert "--start" in result.stdout
        assert "--output" in result.stdout


class TestValidateCLI:
    """Tests for validate subcommands."""

    def test_validate_help(self) -> None:
        """Test validate --help."""
        result = runner.invoke(app, ["validate", "--help"])
        assert result.exit_code == 0
        assert "results" in result.stdout
        assert "config" in result.stdout

    def test_validate_results_help(self) -> None:
        """Test validate results --help."""
        result = runner.invoke(app, ["validate", "results", "--help"])
        assert result.exit_code == 0
        assert "CSV" in result.stdout
        assert "--pv-kw" in result.stdout

    def test_validate_config_help(self) -> None:
        """Test validate config --help."""
        result = runner.invoke(app, ["validate", "config", "--help"])
        assert result.exit_code == 0


def _valid_results_frame() -> pd.DataFrame:
    """A valid 7-day, 1-minute results frame: a 3.5 kW daytime sinusoid and flat demand."""
    index = pd.date_range(
        "2024-06-01", periods=7 * 24 * 60, freq="1min", tz="Europe/London"
    )
    hours = index.hour + index.minute / 60.0
    daylight = (hours >= 6) & (hours < 21)
    sine = np.sin(np.pi * (hours - 6) / 15)
    generation = np.where(daylight, 3.5 * sine, 0.0)
    return pd.DataFrame({"generation_kw": generation, "demand_kw": 0.4}, index=index)


class TestValidateResultsCommand:
    """Functional tests for `validate results` running a CSV through the command."""

    def _validate_results(
        self, tmp_path: Path, frame: pd.DataFrame, *options: str
    ) -> Result:
        """Write *frame* as the results CSV and run `validate results` on it with *options*."""
        csv_file = tmp_path / "results.csv"
        frame.to_csv(csv_file)
        return runner.invoke(app, ["validate", "results", str(csv_file), *options])

    def test_valid_csv_passes_all_checks(self, tmp_path: Path) -> None:
        result = self._validate_results(
            tmp_path, _valid_results_frame(), "--pv-kw", "4.0"
        )

        assert result.exit_code == 0, result.output
        assert "Validation Results" in result.output
        assert "All 6 checks passed" in " ".join(result.output.split())

    def test_failed_check_is_reported_and_exits_nonzero(self, tmp_path: Path) -> None:
        frame = _valid_results_frame()
        at_night = frame.index.hour == 23
        frame.loc[at_night, "generation_kw"] = 1.0

        result = self._validate_results(tmp_path, frame)

        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "5/6 checks passed" in " ".join(result.output.split())

    @pytest.mark.parametrize("pv_kw", ["0", "nan", "inf"])
    def test_a_pv_capacity_that_is_not_positive_and_finite_is_refused(
        self, tmp_path: Path, pv_kw: str
    ) -> None:
        result = self._validate_results(
            tmp_path, _valid_results_frame(), "--pv-kw", pv_kw
        )

        assert result.exit_code == 1
        assert f"Capacity must be positive and finite, got {float(pv_kw)} kW" in " ".join(
            result.output.split()
        )

    @pytest.mark.parametrize(
        ("column", "required"),
        [("generation_kw", "generation"), ("demand_kw", "demand")],
    )
    def test_csv_missing_a_required_column_is_refused(
        self, tmp_path: Path, column: str, required: str
    ) -> None:
        frame = _valid_results_frame().rename(columns={column: "unrelated_kw"})

        result = self._validate_results(tmp_path, frame)

        assert result.exit_code == 1
        assert f"CSV must contain a '{required}' column" in " ".join(
            result.output.split()
        )


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

    def test_config_template_invalid_type(self) -> None:
        """Test config template with invalid type."""
        result = runner.invoke(app, ["config", "template", "invalid"])
        assert result.exit_code == 1
        assert "Unknown template type" in result.stdout

    def test_config_locations(self) -> None:
        """Test config locations shows Bristol."""
        result = runner.invoke(app, ["config", "locations"])
        assert result.exit_code == 0
        assert "bristol" in result.stdout.lower()
        assert "51.45" in result.stdout
        assert "Europe/London" in result.stdout

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


class TestValidateConfig:
    """Tests for validate config command."""

    def test_validate_config_valid(self) -> None:
        """Test validate config with valid file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "valid.yaml"
            config_path.write_text(
                """
home:
  pv:
    capacity_kw: 4.0
    tilt: 35.0
    azimuth: 180.0
  battery:
    capacity_kwh: 5.0
  load:
    annual_consumption_kwh: 3400.0
    household_occupants: 3
"""
            )
            result = runner.invoke(app, ["validate", "config", str(config_path)])
            assert result.exit_code == 0

    def test_validate_config_invalid_pv(self) -> None:
        """Test validate config with invalid PV capacity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "invalid.yaml"
            config_path.write_text(
                """
home:
  pv:
    capacity_kw: -4.0
"""
            )
            result = runner.invoke(app, ["validate", "config", str(config_path)])
            assert result.exit_code == 1
            assert "must be positive" in result.stdout

    def test_validate_config_invalid_tilt(self) -> None:
        """Test validate config with invalid tilt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "invalid.yaml"
            config_path.write_text(
                """
home:
  pv:
    capacity_kw: 4.0
    tilt: 100.0
"""
            )
            result = runner.invoke(app, ["validate", "config", str(config_path)])
            assert result.exit_code == 1
            assert "0-90" in result.stdout

    def test_validate_config_warning_high_consumption(self) -> None:
        """Test validate config warns about high consumption."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "warning.yaml"
            config_path.write_text(
                """
home:
  pv:
    capacity_kw: 4.0
  load:
    annual_consumption_kwh: 50000.0
"""
            )
            result = runner.invoke(app, ["validate", "config", str(config_path)])
            # Should pass but with warning
            assert result.exit_code == 0
            assert "WARNING" in result.stdout or "seems high" in result.stdout


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
        """A command whose weather PVGIS cannot supply exits 1 with one error line naming why, and raises nothing."""
        monkeypatch.setattr(
            "solar_challenge.weather.get_pvgis_tmy", Mock(side_effect=ConnectionError("PVGIS is unreachable"))
        )

        result = runner.invoke(
            app, ["home", "run", "--start", "2024-06-21", "--end", "2024-06-21"], catch_exceptions=False
        )

        assert result.exit_code == 1
        assert " ".join(result.stderr.split()) == (
            "Weather data unavailable: Failed to retrieve TMY data from PVGIS: PVGIS is unreachable"
        )


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


class TestLocationParsing:
    """Tests for location parsing in CLI."""

    def test_parse_bristol_preset(self) -> None:
        """Test parsing 'bristol' preset."""
        loc = parse_location("bristol")
        assert loc.latitude == 51.45
        assert loc.longitude == -2.58

    def test_parse_bristol_case_insensitive(self) -> None:
        """Test parsing 'BRISTOL' is case-insensitive."""
        loc = parse_location("BRISTOL")
        assert loc.latitude == 51.45

    def test_parse_lat_lon(self) -> None:
        """Test parsing lat,lon format."""
        loc = parse_location("51.50,-0.12")
        assert loc.latitude == 51.50
        assert loc.longitude == -0.12

    def test_parse_lat_lon_altitude(self) -> None:
        """Test parsing lat,lon,altitude format."""
        loc = parse_location("51.50,-0.12,25")
        assert loc.latitude == 51.50
        assert loc.longitude == -0.12
        assert loc.altitude == 25.0

    def test_parse_invalid_location(self) -> None:
        """Test parsing invalid location raises error."""
        with pytest.raises(ValueError, match="Invalid location"):
            parse_location("invalid")

    def test_parse_invalid_coordinates(self) -> None:
        """Test parsing invalid coordinates raises error."""
        with pytest.raises(ValueError, match="Invalid coordinates"):
            parse_location("abc,def")


class TestCreateSummaryTableFinancials:
    """Tests that create_summary_table renders financial/SEG rows (step-5/step-6)."""

    def _make_summary_with_financials(self) -> SummaryStatistics:
        """Construct a SummaryStatistics with all financial fields populated."""
        return SummaryStatistics(
            total_generation_kwh=10.0,
            total_demand_kwh=8.0,
            total_self_consumption_kwh=6.0,
            total_grid_import_kwh=2.0,
            total_grid_export_kwh=4.0,
            total_battery_charge_kwh=0.0,
            total_battery_discharge_kwh=0.0,
            peak_generation_kw=3.5,
            peak_demand_kw=2.5,
            self_consumption_ratio=0.6,
            grid_dependency_ratio=0.25,
            export_ratio=0.4,
            simulation_days=1,
            total_import_cost_gbp=0.56,
            total_export_revenue_gbp=0.24,
            net_cost_gbp=0.32,
            seg_revenue_gbp=1.23,
        )

    def _render_table(self, summary: object) -> str:
        """Render create_summary_table to a string via Rich Console."""
        buf = io.StringIO()
        console_obj = Console(file=buf, width=200, highlight=False)
        table = create_summary_table(summary)
        console_obj.print(table)
        return buf.getvalue()

    def test_financial_and_seg_rows_present(self) -> None:
        """create_summary_table renders Grid Import Cost, Export Revenue, Net Cost, SEG Revenue."""
        summary = self._make_summary_with_financials()
        output = self._render_table(summary)

        assert "SEG Revenue" in output, "SEG Revenue row must be present"
        assert "Net Cost" in output, "Net Cost row must be present"
        assert "Export Revenue" in output or "Grid Export Revenue" in output, (
            "Export Revenue row must be present"
        )
        assert "Grid Import Cost" in output, "Grid Import Cost row must be present"
        # Check the SEG value appears
        assert "1.23" in output, "SEG revenue value 1.23 must appear in output"

    def test_no_seg_row_when_seg_revenue_is_none(self) -> None:
        """No SEG Revenue row when seg_revenue_gbp is None."""
        summary = SummaryStatistics(
            total_generation_kwh=10.0,
            total_demand_kwh=8.0,
            total_self_consumption_kwh=6.0,
            total_grid_import_kwh=2.0,
            total_grid_export_kwh=4.0,
            total_battery_charge_kwh=0.0,
            total_battery_discharge_kwh=0.0,
            peak_generation_kw=3.5,
            peak_demand_kw=2.5,
            self_consumption_ratio=0.6,
            grid_dependency_ratio=0.25,
            export_ratio=0.4,
            simulation_days=1,
            total_import_cost_gbp=0.56,
            total_export_revenue_gbp=0.24,
            net_cost_gbp=0.32,
            seg_revenue_gbp=None,  # no SEG
        )
        output = self._render_table(summary)
        assert "SEG Revenue" not in output, "SEG Revenue must not appear when seg_revenue_gbp is None"

    def test_no_financial_rows_for_fleet_summary_like_object(self) -> None:
        """Objects without financial fields (e.g. FleetSummary) render without SEG row, no error."""
        # Minimal FleetSummary-like namespace with n_homes but no financial fields
        fleet_like = types.SimpleNamespace(
            total_generation_kwh=100.0,
            total_demand_kwh=80.0,
            total_self_consumption_kwh=60.0,
            total_grid_import_kwh=20.0,
            total_grid_export_kwh=40.0,
            self_consumption_ratio=0.6,
            grid_dependency_ratio=0.25,
            n_homes=5,
            simulation_days=365,
        )
        output = self._render_table(fleet_like)
        assert "SEG Revenue" not in output, "SEG Revenue must not appear for fleet-like summary"
        assert "Number of Homes" in output, "n_homes should render"


@pytest.mark.usefixtures("clear_june_tmy")
class TestHomeRunFullConfigParity:
    """Tests that `home run` threads tariff + SEG via canonical parser (step-3/step-4)."""

    @pytest.fixture
    def clear_june_tmy(self, weather_cache: WeatherCache) -> None:
        """Serve a clear 21 June as the TMY of Bristol, where `home run` puts a home whose config has no location."""
        weather_cache.put(synthetic_june_weather("2024-06-21"), "tmy", Location.bristol())

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
        """Run `home run --report` for 21 June on a config ending in *seg_yaml*.

        *extra_args* are appended to the command line after ``--report``.
        Returns the CLI result and the spy's capture; ``captured["home_config"]``
        is the HomeConfig passed to simulate_home, absent if it was never called.
        """
        # Capture the home_config passed to simulate_home by wrapping the real function
        captured: dict[str, HomeConfig] = {}
        real_simulate_home = _home_module.simulate_home

        def spy_simulate_home(home_config, start_date, end_date, progress_callback=None):  # type: ignore[no-untyped-def]
            captured["home_config"] = home_config
            return real_simulate_home(home_config, start_date, end_date, progress_callback)

        # Patch simulate_home in the CLI module (local binding)
        monkeypatch.setattr(_cli_home_module, "simulate_home", spy_simulate_home)

        cfg_path = self._write_home_config(tmp_path, seg_yaml)
        result = runner.invoke(
            app,
            [
                "home", "run", str(cfg_path),
                "--start", "2024-06-21",
                "--end", "2024-06-21",
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
        """``--location`` places the simulated home where parse_location puts it."""
        edinburgh = parse_location("55.95,-3.19")
        weather_cache.put(synthetic_june_weather("2024-06-21"), "tmy", edinburgh)

        result, captured = self._run_home(
            monkeypatch,
            tmp_path,
            "seg:\n  rate_pence_per_kwh: 15.0\n",
            "--location",
            "55.95,-3.19",
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert captured["home_config"].location == edinburgh
