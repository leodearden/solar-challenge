"""Tests for the CLI module."""

import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from typer.testing import CliRunner

from solar_challenge.cli.main import app

runner = CliRunner()


def _make_june21_weather() -> pd.DataFrame:
    """Synthetic June-21 24h weather DataFrame (mirrors test_home.py fixture).

    Avoids any PVGIS network call / disk cache.
    """
    index = pd.date_range(
        "2024-06-21 00:00", periods=24, freq="1h", tz="Europe/London"
    )
    return pd.DataFrame(
        {
            "ghi": [
                0, 0, 0, 0, 0, 50, 150, 300, 500, 650, 780, 850,
                870, 850, 780, 650, 500, 300, 150, 50, 0, 0, 0, 0,
            ],
            "dni": [
                0, 0, 0, 0, 0, 100, 250, 450, 650, 800, 900, 950,
                970, 950, 900, 800, 650, 450, 250, 100, 0, 0, 0, 0,
            ],
            "dhi": [
                0, 0, 0, 0, 0, 30, 70, 130, 180, 200, 200, 200,
                200, 200, 200, 200, 180, 130, 70, 30, 0, 0, 0, 0,
            ],
            "temp_air": [
                12, 11, 11, 11, 12, 13, 15, 17, 19, 21, 22, 23,
                23, 23, 22, 21, 19, 17, 16, 14, 13, 12, 12, 12,
            ],
            "wind_speed": [
                2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3,
                3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2,
            ],
        },
        index=index,
    )


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


class TestCLIOutputFormats:
    """Tests for CLI output generation."""

    def test_template_generates_valid_yaml(self) -> None:
        """Test that generated templates are valid YAML."""
        import yaml

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
        from solar_challenge.cli.utils import parse_location

        loc = parse_location("bristol")
        assert loc.latitude == 51.45
        assert loc.longitude == -2.58

    def test_parse_bristol_case_insensitive(self) -> None:
        """Test parsing 'BRISTOL' is case-insensitive."""
        from solar_challenge.cli.utils import parse_location

        loc = parse_location("BRISTOL")
        assert loc.latitude == 51.45

    def test_parse_lat_lon(self) -> None:
        """Test parsing lat,lon format."""
        from solar_challenge.cli.utils import parse_location

        loc = parse_location("51.50,-0.12")
        assert loc.latitude == 51.50
        assert loc.longitude == -0.12

    def test_parse_lat_lon_altitude(self) -> None:
        """Test parsing lat,lon,altitude format."""
        from solar_challenge.cli.utils import parse_location

        loc = parse_location("51.50,-0.12,25")
        assert loc.latitude == 51.50
        assert loc.longitude == -0.12
        assert loc.altitude == 25.0

    def test_parse_invalid_location(self) -> None:
        """Test parsing invalid location raises error."""
        from solar_challenge.cli.utils import parse_location

        with pytest.raises(ValueError, match="Invalid location"):
            parse_location("invalid")

    def test_parse_invalid_coordinates(self) -> None:
        """Test parsing invalid coordinates raises error."""
        from solar_challenge.cli.utils import parse_location

        with pytest.raises(ValueError, match="Invalid coordinates"):
            parse_location("abc,def")


class TestCreateSummaryTableFinancials:
    """Tests that create_summary_table renders financial/SEG rows (step-5/step-6)."""

    def _make_summary_with_financials(self) -> "SummaryStatistics":  # type: ignore[name-defined]
        """Construct a SummaryStatistics with all financial fields populated."""
        from solar_challenge.home import SummaryStatistics

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
        import io
        from rich.console import Console
        from solar_challenge.cli.utils import create_summary_table

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
        from solar_challenge.home import SummaryStatistics

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
        import types
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


class TestHomeRunFullConfigParity:
    """Tests that `home run` threads tariff + SEG via canonical parser (step-3/step-4)."""

    def _write_home_config(self, tmpdir: str) -> Path:
        """Write a temp YAML config with tariff and top-level SEG block.

        Uses economy_7 (not flat_rate) because flat_rate has a known gap at 23:59
        that causes a simulation error on a full-day run; economy_7 fully covers
        all 24 hours via a midnight-crossing peak period.
        """
        cfg_path = Path(tmpdir) / "home_seg.yaml"
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

seg:
  rate_pence_per_kwh: 15.0
"""
        )
        return cfg_path

    def test_home_run_threads_tariff_and_seg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """home run passes tariff + seg to simulate_home and reports SEG Revenue."""
        import solar_challenge.home as _home_module
        import solar_challenge.cli.home as _cli_home_module

        # Capture the home_config passed to simulate_home by wrapping the real function
        captured: dict = {}
        real_simulate_home = _home_module.simulate_home

        def spy_simulate_home(home_config, start_date, end_date, progress_callback=None):  # type: ignore[no-untyped-def]
            captured["home_config"] = home_config
            return real_simulate_home(home_config, start_date, end_date, progress_callback)

        # Patch get_tmy_data to avoid PVGIS network call
        monkeypatch.setattr(_home_module, "get_tmy_data", lambda loc: _make_june21_weather())
        # Patch simulate_home in the CLI module (local binding)
        monkeypatch.setattr(_cli_home_module, "simulate_home", spy_simulate_home)

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._write_home_config(tmpdir)
            result = runner.invoke(
                app,
                [
                    "home", "run", str(cfg_path),
                    "--start", "2024-06-21",
                    "--end", "2024-06-21",
                    "--report",
                ],
                catch_exceptions=False,
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
