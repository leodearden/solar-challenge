# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests of the `validate` command group: its help, `validate results` on a results CSV, and `validate config` on a config file."""

import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from rich.text import Text
from typer.testing import CliRunner, Result

from solar_challenge.cli.main import app
from solar_challenge.cli.utils import console
from tests._cli_table_text import table_text
from tests._names_as_a_word import names_as_a_word

runner = CliRunner()


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


def _valid_results_frame(
    first_day: str = "2024-06-01",
    last_day: str = "2024-06-07",
    *,
    freq: str = "1min",
    tz: str | None = "Europe/London",
) -> pd.DataFrame:
    """A valid results frame from first_day's midnight through last_day, a row every freq on tz's clock: a 3.5 kW daytime sinusoid and a flat 0.4 kW demand.

    tz None writes naive timestamps.
    """
    index = pd.date_range(first_day, f"{last_day} 23:59", freq=freq, tz=tz)
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

    @pytest.mark.parametrize(
        ("pv_kw", "refusal"),
        [
            ("0", "capacity_kw must be greater than 0, got 0.0"),
            ("nan", "capacity_kw must be a finite number, got nan"),
            ("inf", "capacity_kw must be a finite number, got inf"),
        ],
    )
    def test_a_pv_capacity_that_is_not_positive_and_finite_is_refused(
        self, tmp_path: Path, pv_kw: str, refusal: str
    ) -> None:
        result = self._validate_results(
            tmp_path, _valid_results_frame(), "--pv-kw", pv_kw
        )

        assert result.exit_code == 1
        assert refusal in " ".join(result.output.split())

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

    @pytest.mark.parametrize(
        "tz", [pytest.param("Europe/London", id="zoned"), pytest.param(None, id="naive")]
    )
    def test_a_half_hourly_export_is_judged_at_its_own_cadence(
        self, tmp_path: Path, tz: str | None
    ) -> None:
        """0.4 kW over 336 half-hours of 2023 is 67.2 kWh in 7 days, which x 365/7 is 3,504 kWh.

        A naive export is read as written.
        """
        frame = _valid_results_frame("2023-06-01", "2023-06-07", freq="30min", tz=tz)

        result = self._validate_results(tmp_path, frame, "--consumption-kwh", "3504")

        assert result.exit_code == 0, result.output
        assert "3504.0000" in result.output
        assert "All 7 checks passed" in " ".join(result.output.split())

    @pytest.mark.parametrize(
        ("first_day", "last_day", "annual_kwh"),
        [
            pytest.param("2024-03-30", "2024-04-01", "3464.8", id="spring-forward"),
            pytest.param("2024-10-26", "2024-10-28", "3562.4", id="fall-back"),
        ],
    )
    def test_an_export_across_a_clock_change_is_validated_on_the_uk_clock(
        self, tmp_path: Path, first_day: str, last_day: str, annual_kwh: str
    ) -> None:
        """read_csv leaves these rows' two UTC offsets as text.

        On the UK clock each window is 3 calendar days of 2024: 0.4 kW for 71 or 73 hours,
        x 366/3. Read in UTC, the fall-back window would start a day earlier and cover 4 days.
        """
        frame = _valid_results_frame(first_day, last_day)

        result = self._validate_results(tmp_path, frame, "--consumption-kwh", annual_kwh)

        assert result.exit_code == 0, result.output
        assert f"{float(annual_kwh):.4f}" in result.output
        assert "All 7 checks passed" in " ".join(result.output.split())

    def test_a_csv_whose_first_column_is_not_timestamps_is_refused(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "results.csv"
        csv_file.write_text("t,generation_kw,demand_kw\n0,0.0,0.4\n1,0.0,0.4\n2,0.0,0.4\n")

        result = runner.invoke(app, ["validate", "results", str(csv_file)])

        assert result.exit_code == 1
        assert "SimulationWindow.of_index reads a DatetimeIndex" in " ".join(
            result.output.split()
        )


# Ends inside the battery block, so a case can append a battery key.
_SWEEP_FLEET = """\
fleet_distribution:
  n_homes: 2
  pv: {capacity_kw: 4.0}
  battery:
    capacity_kwh:
      type: proportional_to
      source: pv.capacity_kw
      multiplier: {type: sweep, min: 0.5, max: 2.0, steps: 3}
"""

# The UserWarning load_fleet_config raises for a tou_optimized fleet with no top-level tariff:.
_TOU_ADVISORY = (
    "fleet_distribution.dispatch_strategy is 'tou_optimized' but no tariff is configured"
)


def _flex_document_with_infinite_event_hours() -> dict[str, Any]:
    """scenarios/bristol-phase1-flex.yaml as loaded, its first event window's event_hours infinite."""
    flex = Path(__file__).resolve().parents[2] / "scenarios" / "bristol-phase1-flex.yaml"
    document: dict[str, Any] = yaml.safe_load(flex.read_text())
    document["finance"]["grid_services_events"]["event_windows"][0]["event_hours"] = float("inf")
    return document


def _committed_scenario_with_seg_rate(scenario_name: str, rate: float) -> str:
    """scenarios/<scenario_name> as YAML, its seg: block's rate_pence_per_kwh set to *rate*."""
    scenario = Path(__file__).resolve().parents[2] / "scenarios" / scenario_name
    document: dict[str, Any] = yaml.safe_load(scenario.read_text())
    document["seg"]["rate_pence_per_kwh"] = rate
    return yaml.safe_dump(document)


def _scenario_document_holding(block: str, setting: Any) -> str:
    """A scenario: document of one 4 kW PV home for a week, the scenario also carrying a *block* block set to *setting*."""
    return yaml.safe_dump(
        {
            "scenario": {
                "name": "winter",
                "period": {"start_date": "2024-01-01", "end_date": "2024-01-07"},
                "home": {"pv": {"capacity_kw": 4.0}},
                block: setting,
            }
        }
    )


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
            assert "capacity_kw must be greater than 0" in table_text(result.stdout)

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
            assert "tilt must be between 0 and 90" in table_text(result.stdout)

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

    def _validate_config(
        self, tmp_path: Path, document: str, file_name: str = "config.yaml"
    ) -> Result:
        """Write *document* to *file_name* in *tmp_path* and run `validate config` on it.

        catch_exceptions=False makes an exception that escapes the command fail the test,
        instead of passing as exit code 1.
        """
        config_file = tmp_path / file_name
        config_file.write_text(document)
        return runner.invoke(
            app, ["validate", "config", str(config_file)], catch_exceptions=False
        )

    @pytest.mark.parametrize(
        ("document", "refusal"),
        [
            pytest.param(
                "home:\n  pv: {capacity_kw: 4.0}\n  load: {household_occupants: 2.5}\n",
                "household_occupants must be a whole number, got 2.5",
                id="home-occupants-not-whole",
            ),
            pytest.param(
                "home:\n  load: {occupants: 3}\n",
                "Unrecognised keys in home.load: 'occupants';",
                id="home-unrecognised-key",
            ),
            pytest.param(
                "pv: {capacity_kw: 4.0}\nload: {household_occupants: 11}\n",
                "household_occupants must be between 1 and 10, got 11",
                id="flat-home",
            ),
            pytest.param(
                "homes:\n  - {}\n  - load: {occupants: 3}\n",
                "Unrecognised keys in homes[1].load: 'occupants';",
                id="homes-list",
            ),
            pytest.param(
                "fleet_distribution:\n  n_homes: 2\n  pv: {capacity_kw: 4.0, tilt: 100}\n",
                "tilt must be between 0 and 90, got 100.0",
                id="fleet-distribution",
            ),
            pytest.param(
                _SWEEP_FLEET + "    max_charge_kw: -1\n",
                "max_charge_kw must be greater than 0, got -1.0",
                id="fleet-sweep",
            ),
            pytest.param(
                _SWEEP_FLEET + "tariff: {type: economy_8}\n",
                "Unknown tariff type 'economy_8'",
                id="fleet-sweep-tariff",
            ),
            pytest.param(
                "scenarios:\n  - name: winter\n    home: {pv: {capacity_kw: 4.0}}\n",
                "Scenario 'winter' must have a 'period' field",
                id="scenarios",
            ),
            pytest.param(
                "scenario:\n"
                "  name: winter\n"
                "  period: {start_date: '2024-01-01', end_date: '2024-01-07'}\n"
                "  homes:\n"
                "    - load: {household_occupants: 2.5}\n",
                "household_occupants must be a whole number, got 2.5",
                id="scenario",
            ),
            pytest.param("home: [\n", "Invalid YAML in", id="yaml-syntax"),
        ],
    )
    def test_a_file_its_loader_refuses_is_one_error_row(
        self, tmp_path: Path, document: str, refusal: str
    ) -> None:
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 1
        assert f"ERROR {refusal}" in table_text(result.stdout)

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param("pv: {capacity_kw: 4.0}\n", id="flat-home"),
            pytest.param(
                "homes:\n  - {}\n  - pv: {capacity_kw: 6.0}\n", id="homes-list"
            ),
            pytest.param(
                "fleet_distribution:\n  n_homes: 2\n  pv: {capacity_kw: 4.0}\n",
                id="fleet-distribution",
            ),
            pytest.param(_SWEEP_FLEET, id="fleet-sweep"),
            pytest.param(
                "scenarios:\n"
                "  - name: winter\n"
                "    period: {start_date: '2024-01-01', end_date: '2024-01-07'}\n"
                "    home: {pv: {capacity_kw: 4.0}}\n",
                id="scenarios",
            ),
        ],
    )
    def test_a_file_its_loader_builds_is_valid(
        self, tmp_path: Path, document: str
    ) -> None:
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 0
        assert "OK Configuration is valid" in table_text(result.stdout)

    @pytest.mark.parametrize(
        "scenario_file",
        sorted((Path(__file__).resolve().parents[2] / "scenarios").glob("*.yaml")),
        ids=lambda path: path.name,
    )
    def test_every_committed_scenario_is_valid(self, scenario_file: Path) -> None:
        result = runner.invoke(
            app, ["validate", "config", str(scenario_file)], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        assert "ERROR" not in result.stdout

    @pytest.mark.parametrize(
        ("document", "field", "value_repr"),
        [
            pytest.param(
                yaml.safe_dump(_flex_document_with_infinite_event_hours()),
                "event_hours",
                "inf",
                id="fleet-distribution",
            ),
            pytest.param(
                _scenario_document_holding(
                    "finance", _flex_document_with_infinite_event_hours()["finance"]
                ),
                "event_hours",
                "inf",
                id="scenario",
            ),
            pytest.param(
                "homes:\n  - {}\nfinance: {standing_charge_pence_per_day: 60.0, equity_fraction: .nan}\n",
                "equity_fraction",
                "nan",
                id="homes-list",
            ),
            pytest.param(
                _SWEEP_FLEET + "finance: {standing_charge_pence_per_day: .inf}\n",
                "standing_charge_pence_per_day",
                "inf",
                id="fleet-sweep",
            ),
            pytest.param(
                "home:\n  pv: {capacity_kw: 4.0}\nfinance: {standing_charge_pence_per_day: .nan}\n",
                "standing_charge_pence_per_day",
                "nan",
                id="home",
            ),
        ],
    )
    def test_a_finance_number_its_type_refuses_is_an_error_row_naming_the_field_and_the_value(
        self, tmp_path: Path, document: str, field: str, value_repr: str
    ) -> None:
        """Whatever the file's shape, a finance number its type refuses is the file's ERROR row.

        The rows cover each shape: a fleet_distribution: file, a scenario:, a homes: list,
        a YAML sweep and a home: file. The fleet-distribution row is the PRD's C3 file,
        scenarios/bristol-phase1-flex.yaml with its first event window's event_hours
        infinite; the scenario row holds that same finance block.
        """
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        assert field in error_row
        assert names_as_a_word(error_row, value_repr)

    @pytest.mark.parametrize(
        ("document", "value_repr"),
        [
            pytest.param(
                _committed_scenario_with_seg_rate("bristol-phase1-flex.yaml", float("nan")),
                "nan",
                id="fleet-distribution",
            ),
            pytest.param(
                _scenario_document_holding("seg", {"rate_pence_per_kwh": float("inf")}),
                "inf",
                id="scenario",
            ),
            pytest.param(
                "homes:\n  - {}\nseg: {rate_pence_per_kwh: .nan}\n",
                "nan",
                id="homes-list",
            ),
            pytest.param(
                _SWEEP_FLEET + "seg: {rate_pence_per_kwh: .nan}\n",
                "nan",
                id="fleet-sweep",
            ),
            pytest.param(
                _committed_scenario_with_seg_rate("bristol-arbitrage.yaml", float("inf")),
                "inf",
                id="home",
            ),
        ],
    )
    def test_a_seg_rate_its_parser_refuses_is_an_error_row_naming_the_rate_and_the_value(
        self, tmp_path: Path, document: str, value_repr: str
    ) -> None:
        """Whatever the file's shape, a SEG rate its parser refuses is the file's ERROR row.

        The rows cover the same shapes as the finance test's. The fleet-distribution row is a
        fleet file whose seg: block `finance run` reads, and the home row a home: file whose
        seg: block `home run` reads: each a committed scenario with its rate replaced.
        """
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        assert "rate_pence_per_kwh" in error_row
        assert names_as_a_word(error_row, value_repr)

    def test_a_misspelt_battery_strategy_type_is_an_error_row_naming_its_path_and_the_strategies(
        self, tmp_path: Path
    ) -> None:
        """scenarios/dispatch-comparison.yaml with its first home's battery strategy_type misspelt."""
        scenario = Path(__file__).resolve().parents[2] / "scenarios" / "dispatch-comparison.yaml"
        committed = scenario.read_text()
        misspelt = committed.replace("strategy_type: self_consumption", "strategy_type: tou_optimised", 1)
        assert misspelt != committed

        result = self._validate_config(tmp_path, misspelt, file_name=scenario.name)

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        assert "homes[0].battery.dispatch_strategy.strategy_type 'tou_optimised'" in error_row
        for strategy in ("peak_shaving", "self_consumption", "tou_optimized"):
            assert strategy in error_row

    @pytest.mark.parametrize(
        ("tariff", "named"),
        [
            pytest.param(
                "{type: custom, periods: ["
                "{start_time: '07:00', end_time: '23:00', rate_per_kwh: 0.30}]}",
                "23:00-07:00",
                id="gap",
            ),
            pytest.param(
                "{type: custom, periods: ["
                "{start_time: '00:00', end_time: '12:00', rate_per_kwh: 0.10}, "
                "{start_time: '06:00', end_time: '00:00', rate_per_kwh: 0.30}]}",
                "06:00-12:00",
                id="overlap",
            ),
            pytest.param("{type: flat_rate, rate_per_kwh: .nan}", "nan", id="nan-rate"),
            pytest.param("{type: flat_rate, rate_per_kwh: .inf}", "inf", id="inf-rate"),
        ],
    )
    def test_a_tariff_block_its_constructor_refuses_is_an_error_row_naming_the_clock_range_or_rate(
        self, tmp_path: Path, tariff: str, named: str
    ) -> None:
        """Times are quoted: PyYAML reads an unquoted 23:00 as the sexagesimal integer 1380."""
        result = self._validate_config(
            tmp_path, f"home:\n  pv: {{capacity_kw: 4.0}}\n  tariff: {tariff}\n"
        )

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        assert names_as_a_word(text[text.index("ERROR"):], named)

    @pytest.mark.parametrize(
        ("document", "field", "value_repr"),
        [
            pytest.param(
                "location: {altitude: .nan}\nhome:\n  pv: {capacity_kw: 4.0}\n",
                "altitude",
                "nan",
                id="location-altitude-nan",
            ),
            pytest.param(
                "location: {timezone: Europe/Londn}\nhome:\n  pv: {capacity_kw: 4.0}\n",
                "timezone",
                "'Europe/Londn'",
                id="location-unknown-time-zone",
            ),
            pytest.param(
                "home:\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  heat_pump: {heat_pump_type: ASHP, thermal_capacity_kw: .nan}\n",
                "thermal_capacity_kw",
                "nan",
                id="heat-pump-capacity-nan",
            ),
            pytest.param(
                "home:\n  pv: {capacity_kw: true}\n",
                "capacity_kw",
                "True",
                id="pv-capacity-boolean",
            ),
            pytest.param(
                "home:\n  pv: {capacity_kw: 4.0, azimuth: south}\n",
                "azimuth",
                "'south'",
                id="pv-azimuth-word",
            ),
            pytest.param(
                "home:\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  battery: {capacity_kwh: 5.0, grid_charging: {target_soc_fraction: true}}\n",
                "target_soc_fraction",
                "True",
                id="battery-grid-charging-target-boolean",
            ),
            pytest.param(
                "home:\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  battery:\n"
                "    capacity_kwh: 5.0\n"
                "    dispatch_strategy: {strategy_type: peak_shaving, import_limit_kw: true}\n",
                "import_limit_kw",
                "True",
                id="battery-peak-shaving-limit-boolean",
            ),
            pytest.param(
                "home:\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  battery:\n"
                "    capacity_kwh: 5.0\n"
                "    dispatch_strategy: {strategy_type: tou_optimized, peak_hours: [[16.5, 19]]}\n",
                "peak_hours[0][0]",
                "16.5",
                id="battery-tou-peak-hour-fraction",
            ),
        ],
    )
    def test_a_number_or_zone_a_component_refuses_is_an_error_row_naming_the_field_and_the_value(
        self, tmp_path: Path, document: str, field: str, value_repr: str
    ) -> None:
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        assert names_as_a_word(error_row, field)
        assert names_as_a_word(error_row, value_repr)

    def test_the_title_names_the_file_verbatim_in_the_table_title_style(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A file name Rich would read as markup ([draft]) or an emoji code (:sun:) titles the table as the user typed it, in Rich's table-title italics."""
        monkeypatch.setattr(console, "record", True)

        result = self._validate_config(
            tmp_path, "home:\n  pv:\n    capacity_kw: 4.0\n", file_name="[draft] :sun:.yaml"
        )
        recorded = Text.from_ansi(console.export_text(styles=True))

        assert result.exit_code == 0
        assert "Config Validation: [draft] :sun:.yaml" in " ".join(result.stdout.split())
        title_start = recorded.plain.index("Config Validation:")
        assert recorded.get_style_at_offset(console, title_start).italic

    def test_an_errors_text_is_shown_verbatim(self, tmp_path: Path) -> None:
        result = self._validate_config(tmp_path, "home:\n  load: {'[bold]x': 1}\n")

        assert result.exit_code == 1
        assert "ERROR Unrecognised keys in home.load: '[bold]x';" in table_text(
            result.stdout
        )

    @pytest.mark.parametrize(
        ("document", "warning"),
        [
            pytest.param(
                "homes:\n"
                "  - pv: {capacity_kw: 55.0}\n"
                "  - pv: {capacity_kw: 60.0}\n"
                "  - pv: {capacity_kw: 4.0}\n",
                "PV capacity 60.0 kW seems high for domestic (2 of 3 homes above 50 kW)",
                id="pv-homes-list",
            ),
            pytest.param(
                "home:\n  battery: {capacity_kwh: 150.0}\n",
                "Battery capacity 150.0 kWh seems high for domestic (1 of 1 homes above 100 kWh)",
                id="battery-home",
            ),
            pytest.param(
                "fleet_distribution:\n"
                "  n_homes: 2\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  load: {annual_consumption_kwh: 25000.0}\n",
                "Annual consumption 25000.0 kWh seems high for domestic (2 of 2 homes above 20000 kWh)",
                id="consumption-fleet-distribution",
            ),
            pytest.param(
                "fleet_distribution:\n"
                "  n_homes: 2\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  battery:\n"
                "    capacity_kwh:\n"
                "      type: proportional_to\n"
                "      source: pv.capacity_kw\n"
                "      multiplier: {type: sweep, min: 10, max: 30, steps: 3, mode: linear}\n",
                "Battery capacity 120.0 kWh seems high for domestic "
                "(2 of 6 homes above 100 kWh, across 3 sweep points)",
                id="battery-sweep",
            ),
        ],
    )
    def test_a_home_above_a_domestic_ceiling_is_one_warning_row(
        self, tmp_path: Path, document: str, warning: str
    ) -> None:
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 0
        assert f"WARNING {warning}" in table_text(result.stdout)
        assert table_text(result.stdout).count("WARNING") == 1

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param(
                "fleet_distribution:\n"
                "  n_homes: 2\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  dispatch_strategy: tou_optimized\n",
                id="fleet-distribution",
            ),
            pytest.param(_SWEEP_FLEET + "  dispatch_strategy: tou_optimized\n", id="fleet-sweep"),
        ],
    )
    def test_a_loader_advisory_is_a_warning_row_not_a_python_warning(
        self, tmp_path: Path, recwarn: pytest.WarningsRecorder, document: str
    ) -> None:
        """The advisory is one row for the whole file, however many sweep points it builds."""
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 0
        assert f"WARNING {_TOU_ADVISORY}" in table_text(result.stdout)
        assert table_text(result.stdout).count(_TOU_ADVISORY) == 1
        assert "OK Configuration is valid" not in table_text(result.stdout)
        assert [w for w in recwarn if issubclass(w.category, UserWarning)] == []

    def test_a_loader_advisory_raised_before_a_refusal_is_shown_beside_it(
        self, tmp_path: Path
    ) -> None:
        result = self._validate_config(
            tmp_path,
            "fleet_distribution:\n"
            "  n_homes: 2\n"
            "  pv: {capacity_kw: 4.0, tilt: 100}\n"
            "  dispatch_strategy: tou_optimized\n",
        )

        assert result.exit_code == 1
        assert "ERROR tilt must be between 0 and 90, got 100.0" in table_text(result.stdout)
        assert f"WARNING {_TOU_ADVISORY}" in table_text(result.stdout)
