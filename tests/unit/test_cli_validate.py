# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests of the `validate` command group: its help, `validate results` on a results CSV, and `validate config` on a config file."""

import re
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import pytest
import yaml
from rich.text import Text
from typer.testing import CliRunner, Result

from solar_challenge.cli.main import app
from solar_challenge.cli.utils import console
from solar_challenge.ev import EVConfig
from solar_challenge.finance import FinanceConfig
from solar_challenge.gridservices import EventWindow
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import parse_tariff_config
from solar_challenge.tariff import TariffConfig
from tests._cli_table_text import table_text
from tests._construction_refusals import prefixed_construction_refusal
from tests._names_as_a_word import names_as_a_word
from tests._proportional_source_refusals import proportional_source_refusal
from tests._repository_paths import SCENARIOS_DIR
from tests._retired_dispatch_strategy import retired_dispatch_strategy_refusal

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

def _bristol_arbitrage_with_its_home(edit_home: Callable[[dict[str, Any]], object]) -> str:
    """scenarios/bristol-arbitrage.yaml as YAML, its home: block changed by *edit_home*."""
    document: dict[str, Any] = yaml.safe_load((SCENARIOS_DIR / "bristol-arbitrage.yaml").read_text())
    edit_home(document["home"])
    return yaml.safe_dump(document)


def _dispatched_by_its_battery(dispatch_strategy: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
    """An edit of a home: block that gives its battery the dispatch_strategy: block *dispatch_strategy*."""

    def edit(home: dict[str, Any]) -> None:
        home["battery"]["dispatch_strategy"] = dispatch_strategy

    return edit


def _tariff_name(block: dict[str, Any]) -> str:
    """The name of the tariff the tariff: block *block* builds."""
    tariff = parse_tariff_config(block)
    assert tariff is not None
    return tariff.name


def _bristol_arbitrage_tariff_name() -> str:
    """The name of the tariff scenarios/bristol-arbitrage.yaml's home is on."""
    document: dict[str, Any] = yaml.safe_load((SCENARIOS_DIR / "bristol-arbitrage.yaml").read_text())
    return _tariff_name(document["home"]["tariff"])


def _example_economy7_with_an_off_peak_ev(edit_home: Callable[[dict[str, Any]], object]) -> str:
    """scenarios/example-economy7.yaml as YAML, its home given a 7 kW off_peak EV home from 18:00 to 07:00, then changed by *edit_home*."""
    document: dict[str, Any] = yaml.safe_load((SCENARIOS_DIR / "example-economy7.yaml").read_text())
    document["home"]["ev"] = {
        "charger_type": "7kW",
        "arrival_hour": 18,
        "departure_hour": 7,
        "required_charge_kwh": 35,
        "smart_charging_mode": "off_peak",
    }
    edit_home(document["home"])
    return yaml.safe_dump(document)


def _flex_document_with_infinite_event_hours() -> dict[str, Any]:
    """scenarios/bristol-phase1-flex.yaml as loaded, its first event window's event_hours infinite."""
    flex = SCENARIOS_DIR / "bristol-phase1-flex.yaml"
    document: dict[str, Any] = yaml.safe_load(flex.read_text())
    document["finance"]["grid_services_events"]["event_windows"][0]["event_hours"] = float("inf")
    return document


def _committed_scenario_with_seg_rate(scenario_name: str, rate: float) -> str:
    """scenarios/<scenario_name> as YAML, its seg: block's rate_pence_per_kwh set to *rate*."""
    scenario = SCENARIOS_DIR / scenario_name
    document: dict[str, Any] = yaml.safe_load(scenario.read_text())
    document["seg"]["rate_pence_per_kwh"] = rate
    return yaml.safe_dump(document)


def _committed_battery_sweep_with_multiplier(**multiplier: float) -> str:
    """scenarios/bristol-phase1-proportional-battery-sweep.yaml as YAML, its battery capacity's sweep multiplier given *multiplier*'s keys."""
    scenario = SCENARIOS_DIR / "bristol-phase1-proportional-battery-sweep.yaml"
    document: dict[str, Any] = yaml.safe_load(scenario.read_text())
    document["fleet_distribution"]["battery"]["capacity_kwh"]["multiplier"].update(multiplier)
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
                "home.load: household_occupants must be a whole number, got 2.5",
                id="home-occupants-not-whole",
            ),
            pytest.param(
                "home:\n  load: {occupants: 3}\n",
                "home.load: unrecognised keys 'occupants';",
                id="home-unrecognised-key",
            ),
            pytest.param(
                "home:\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  battery: {capacity_kwh: 5.0, efficiency: 0.95, charge_efficiency: 0.99}\n",
                "home.battery: sets both forms of a battery's efficiency: efficiency and charge_efficiency;",
                id="home-battery-both-efficiency-forms",
            ),
            pytest.param(
                "pv: {capacity_kw: 4.0}\nload: {household_occupants: 11}\n",
                "load: household_occupants must be between 1 and 10, got 11",
                id="flat-home",
            ),
            pytest.param(
                "homes:\n  - {}\n  - load: {occupants: 3}\n",
                "homes[1].load: unrecognised keys 'occupants';",
                id="homes-list",
            ),
            pytest.param(
                "homes:\n  - {}\n  - heat_pump: {thermal_capacity_kw: 8}\n",
                "homes[1].heat_pump: requires 'heat_pump_type'",
                id="homes-heat-pump-without-its-type",
            ),
            pytest.param(
                "homes:\n  - {}\n  - pv: {azimuth: 400}\n",
                "homes[1].pv: azimuth must be between 0 and 360, got 400",
                id="homes-pv-azimuth-out-of-range",
            ),
            pytest.param(
                "fleet_distribution:\n  n_homes: 2\n  pv: {capacity_kw: 4.0, tilt: 100}\n",
                "fleet_distribution.pv: home 1: tilt must be between 0 and 90, got 100.0",
                id="fleet-distribution",
            ),
            pytest.param(
                "fleet_distribution:\n  n_homes: 2.7\n  pv: {capacity_kw: 4.0}\n",
                "fleet_distribution: n_homes must be a whole number, got 2.7",
                id="fleet-distribution-fractional-n-homes",
            ),
            pytest.param(
                "fleet_distribution:\n",
                "fleet_distribution: must be a mapping, got NoneType",
                id="fleet-distribution-null",
            ),
            pytest.param(
                "fleet_distribution: 5\n",
                "fleet_distribution: must be a mapping, got int",
                id="fleet-distribution-a-number",
            ),
            pytest.param(
                "fleet_distribution:\n  n_homes: 2\n  pv: {capacity_kw: true}\n",
                "fleet_distribution.pv.capacity_kw must be a finite number, got True",
                id="fleet-distribution-boolean-capacity",
            ),
            pytest.param(
                _SWEEP_FLEET + "    max_charge_kw: -1\n",
                "fleet_distribution.battery: home 1: max_charge_kw must be greater than 0, got -1.0",
                id="fleet-sweep",
            ),
            pytest.param(
                _SWEEP_FLEET + "tariff: {type: economy_8}\n",
                "tariff.type: unknown tariff type 'economy_8'; supported types:",
                id="fleet-sweep-tariff",
            ),
            pytest.param(
                "scenario:\n"
                "  name: winter\n"
                "  period: {start_date: '2024-01-01', end_date: '2024-01-07'}\n"
                "  homes:\n"
                "    - load: {household_occupants: 2.5}\n",
                "scenario.homes[0].load: household_occupants must be a whole number, got 2.5",
                id="scenario",
            ),
            pytest.param("home: [\n", "Invalid YAML in", id="yaml-syntax"),
            pytest.param("homes: 5\n", "homes: must be a list, got int", id="R2-homes-a-number"),
            pytest.param("- a\n- b\n", "the top level: must be a mapping, got list", id="R3-a-list-document"),
        ],
    )
    def test_a_file_its_loader_refuses_is_one_error_row(
        self, tmp_path: Path, document: str, refusal: str
    ) -> None:
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 1
        assert f"ERROR {refusal}" in table_text(result.stdout)

    def test_a_homes_value_that_is_no_list_exits_as_a_refusal_not_a_traceback(self, tmp_path: Path) -> None:
        """R2: homes: 5 was a TypeError, which the command does not catch, so it escaped with a traceback."""
        result = self._validate_config(tmp_path, "homes: 5\n")

        assert isinstance(result.exception, SystemExit)

    @pytest.mark.parametrize(
        ("document", "label", "construct"),
        [
            pytest.param(
                "home:\n  pv: {capacity_kw: true}\n",
                "home.pv",
                lambda: PVConfig(capacity_kw=True),
                id="home-pv-capacity-boolean",
            ),
            pytest.param(
                "home:\n  pv: {capacity_kw: 4.0}\n  ev: {charger_type: 7kW, arrival_hour: 18.9}\n",
                "home.ev",
                lambda: EVConfig(charger_type="7kW", arrival_hour=18.9),
                id="home-ev-arrival-not-whole",
            ),
            pytest.param(
                "homes:\n  - {}\n  - pv: {capacity_kw: true}\n",
                "homes[1].pv",
                lambda: PVConfig(capacity_kw=True),
                id="homes-entry-pv-capacity-boolean",
            ),
            pytest.param(
                "pv: {capacity_kw: 4.0, azimuth: south}\n",
                "pv",
                lambda: PVConfig(capacity_kw=4.0, azimuth="south"),
                id="flat-home-pv-azimuth-word",
            ),
            pytest.param(
                "location: {latitude: 51.45, longitude: -2.58, altitude: .nan}\n"
                "home:\n  pv: {capacity_kw: 4.0}\n",
                "location",
                lambda: Location(latitude=51.45, longitude=-2.58, altitude=float("nan")),
                id="location-altitude-nan",
            ),
            pytest.param(
                "home:\n  pv: {capacity_kw: 4.0}\n  tariff: {type: flat_rate, rate_per_kwh: true}\n",
                "home.tariff",
                lambda: TariffConfig.flat_rate(rate_per_kwh=True),
                id="home-flat-rate-boolean",
            ),
            pytest.param(
                "home:\n  pv: {capacity_kw: 4.0}\nfinance: {standing_charge_pence_per_day: 60.0, vat_rate: true}\n",
                "finance",
                lambda: FinanceConfig(standing_charge_pence_per_day=60.0, vat_rate=True),
                id="finance-vat-rate-boolean",
            ),
            pytest.param(
                yaml.safe_dump(_flex_document_with_infinite_event_hours()),
                "finance.grid_services_events.event_windows[0]",
                lambda: EventWindow(
                    **_flex_document_with_infinite_event_hours()["finance"]["grid_services_events"]["event_windows"][0]
                ),
                id="flex-fleet-event-hours-infinite",
            ),
        ],
    )
    def test_a_value_its_blocks_type_refuses_is_an_error_row_prefixed_by_the_blocks_path(
        self, tmp_path: Path, document: str, label: str, construct: Callable[[], object]
    ) -> None:
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 1
        assert f"ERROR {prefixed_construction_refusal(label, construct)}" in table_text(result.stdout)

    @pytest.mark.parametrize(
        ("document", "refusal"),
        [
            pytest.param(
                "fleet_distribution: {n_homes: 2, pv: {capacity_kw: 4.0}, heat_pump: {heat_pump_type: XSHP}}\n",
                "fleet_distribution.heat_pump.heat_pump_type: invalid value 'XSHP'; "
                "valid values: null or one of ['ASHP', 'GSHP']",
                id="a heat pump type outside its choices",
            ),
            pytest.param(
                "fleet_distribution:\n"
                "  n_homes: 2\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  heat_pump: {heat_pump_type: {type: normal, mean: 1, std: 0.1}}\n",
                "fleet_distribution.heat_pump.heat_pump_type: invalid spec {'type': 'normal', 'mean': 1, 'std': 0.1}; "
                "valid specs: null, one of ['ASHP', 'GSHP'], or a weighted_discrete or shuffled_pool of them and nulls",
                id="a normal on a heat pump type",
            ),
            pytest.param(
                "fleet_distribution:\n"
                "  n_homes: 2\n"
                "  pv: {capacity_kw: 4.0, tilt: {type: weighted_discrete, values: [30, '35'], weights: [1, 1]}}\n",
                "fleet_distribution.pv.tilt: invalid value '35'; valid values: null or a number",
                id="a string among a number's weighted values",
            ),
        ],
    )
    def test_a_fleet_whose_specs_its_fields_kinds_do_not_draw_is_refused_at_read_naming_the_path_and_rule(
        self, tmp_path: Path, document: str, refusal: str
    ) -> None:
        """Each refusal names a key's path and no home: the fleet is refused as it is read, before any home is drawn."""
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 1
        assert f"ERROR {refusal}" in table_text(result.stdout)

    @pytest.mark.parametrize(
        ("document", "path", "source"),
        [
            pytest.param(
                "fleet_distribution:\n"
                "  n_homes: 2\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  battery: {capacity_kwh: {type: proportional_to, source: pv.capacity}}\n",
                "fleet_distribution.battery.capacity_kwh",
                "pv.capacity",
                id="a path no field has",
            ),
            pytest.param(
                "fleet_distribution:\n"
                "  n_homes: 2\n"
                "  pv: {capacity_kw: 4.0, tilt: {type: proportional_to, source: battery.capacity_kwh}}\n"
                "  battery: {capacity_kwh: 5.0}\n",
                "fleet_distribution.pv.tilt",
                "battery.capacity_kwh",
                id="a field of a later component",
            ),
        ],
    )
    def test_a_fleet_whose_proportional_to_source_is_not_drawn_earlier_is_refused_at_read_naming_the_path_and_sources(
        self, tmp_path: Path, document: str, path: str, source: str
    ) -> None:
        """The refusal names the dependent's path, its source and the sources it may name, and no home."""
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 1
        assert f"ERROR {proportional_source_refusal(path, source, ['pv.capacity_kw'])}" in table_text(result.stdout)

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
            pytest.param(
                "fleet_distribution: {n_homes: 2, pv: {capacity_kw: 4.0, "
                "tilt: {type: proportional_to, source: pv.capacity_kw, multiplier: 5}}}\n",
                id="fleet-distribution-proportional-to-an-earlier-field",
            ),
            pytest.param(_SWEEP_FLEET, id="fleet-sweep"),
            pytest.param(
                "scenarios:\n"
                "  - name: winter\n"
                "    period: {start_date: '2024-01-01', end_date: '2024-01-07'}\n"
                "    home: {pv: {capacity_kw: 4.0}}\n",
                id="scenarios",
            ),
            pytest.param(
                "scenarios:\n  - name: winter\n    home: {pv: {capacity_kw: 4.0}}\n", id="scenarios-without-a-period"
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
        sorted(SCENARIOS_DIR.glob("*.yaml")),
        ids=lambda path: path.name,
    )
    def test_every_committed_scenario_is_valid(self, scenario_file: Path) -> None:
        result = runner.invoke(
            app, ["validate", "config", str(scenario_file)], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        assert "ERROR" not in result.stdout

    def test_a_sweep_whose_points_are_not_all_finite_is_an_error_row_naming_its_ends_not_an_infinite_point(
        self, tmp_path: Path
    ) -> None:
        """The shipped proportional battery sweep, its geometric multiplier from 1e-300 to 1e300 in 3 steps.

        The row names the sweep's min and max, and no infinite value: the spec is refused as it
        is built, before any of its points becomes a fleet's multiplier.
        """
        result = self._validate_config(
            tmp_path, _committed_battery_sweep_with_multiplier(min=1.0e-300, max=1.0e300, steps=3)
        )

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        assert names_as_a_word(error_row, "min")
        assert names_as_a_word(error_row, "max")
        assert not names_as_a_word(error_row, "inf")

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

    @pytest.mark.parametrize(
        ("key", "setting", "named"),
        [
            pytest.param("output", {"csv_path": "r.csv"}, ("scenario.output", "--output"), id="output"),
            pytest.param(
                "tariff_config",
                {"type": "economy_7"},
                ("scenario.tariff_config", "tariff:"),
                id="tariff_config",
            ),
            pytest.param("bogus", 1, ("scenario", "'bogus'"), id="unrecognised"),
        ],
    )
    def test_a_scenario_key_no_command_reads_is_an_error_row_naming_its_path_and_replacement(
        self, tmp_path: Path, key: str, setting: Any, named: tuple[str, str]
    ) -> None:
        """A scenario: document's output:, tariff_config: or unrecognised key is the file's ERROR row, naming the key's path and what replaces it, or the key itself."""
        result = self._validate_config(tmp_path, _scenario_document_holding(key, setting))

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        for name in named:
            assert name in error_row, (name, error_row)

    def test_a_misspelt_battery_strategy_type_is_an_error_row_naming_its_path_and_the_strategies(
        self, tmp_path: Path
    ) -> None:
        """scenarios/dispatch-comparison.yaml with its first home's battery strategy_type misspelt."""
        scenario = SCENARIOS_DIR / "dispatch-comparison.yaml"
        committed = scenario.read_text()
        misspelt = committed.replace("strategy_type: self_consumption", "strategy_type: tou_optimised", 1)
        assert misspelt != committed

        result = self._validate_config(tmp_path, misspelt, file_name=scenario.name)

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        assert "homes[0].battery.dispatch_strategy.strategy_type: invalid value 'tou_optimised';" in error_row
        for strategy in ("peak_shaving", "self_consumption", "tou_optimized"):
            assert strategy in error_row

    @pytest.mark.parametrize(
        ("edit_home", "named"),
        [
            pytest.param(
                _dispatched_by_its_battery({"strategy_type": "self_consumption"}),
                ["grid_charging", "self_consumption"],
                id="dispatched-self_consumption",
            ),
            pytest.param(lambda home: home.pop("tariff"), ["tou_optimized", "tariff"], id="without-its-tariff"),
        ],
    )
    def test_a_grid_charging_home_whose_dispatch_would_ignore_it_is_an_error_row(
        self, tmp_path: Path, edit_home: Callable[[dict[str, Any]], object], named: list[str]
    ) -> None:
        """scenarios/bristol-arbitrage.yaml, whose battery grid-charges as it dispatches tou_optimized on its tariff's clock."""
        result = self._validate_config(
            tmp_path, _bristol_arbitrage_with_its_home(edit_home), file_name="bristol-arbitrage.yaml"
        )

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        for name in named:
            assert name in error_row

    def test_a_grid_charging_home_on_a_flat_tariff_is_an_error_row_naming_the_tariff(self, tmp_path: Path) -> None:
        """scenarios/bristol-arbitrage.yaml on a flat 0.25 £/kWh tariff, which has no cheap period, its battery's tou_optimized on the tariff's clock."""
        flat_rate = {"type": "flat_rate", "rate_per_kwh": 0.25}

        def edit(home: dict[str, Any]) -> None:
            home["tariff"] = flat_rate

        result = self._validate_config(
            tmp_path, _bristol_arbitrage_with_its_home(edit), file_name="bristol-arbitrage.yaml"
        )

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        for name in ("grid_charging", "'tou_optimized'", "no cheap period", _tariff_name(flat_rate)):
            assert name in error_row, (name, error_row)

    def test_a_grid_charging_battery_dispatched_on_its_tariffs_clock_is_valid(self, tmp_path: Path) -> None:
        """scenarios/bristol-arbitrage.yaml, its battery's tou_optimized written without peak_hours: it dispatches on Economy 7's clock."""
        document = _bristol_arbitrage_with_its_home(_dispatched_by_its_battery({"strategy_type": "tou_optimized"}))

        result = self._validate_config(tmp_path, document, file_name="bristol-arbitrage.yaml")

        assert result.exit_code == 0, result.stdout
        assert "OK Configuration is valid" in table_text(result.stdout)

    def test_a_battery_whose_peak_hours_reach_a_cheap_minute_of_its_tariff_is_an_error_row(
        self, tmp_path: Path
    ) -> None:
        """scenarios/bristol-arbitrage.yaml, its battery dispatched by tou_optimized at 07:00-09:00, which reaches Economy 7's cheap 07:00-07:30."""
        document = _bristol_arbitrage_with_its_home(
            _dispatched_by_its_battery({"strategy_type": "tou_optimized", "peak_hours": [[7, 9]]})
        )

        result = self._validate_config(tmp_path, document, file_name="bristol-arbitrage.yaml")

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        for name in ("07:00-07:30", _bristol_arbitrage_tariff_name()):
            assert name in error_row, (name, error_row)

    def test_a_home_with_an_off_peak_ev_and_no_tariff_is_an_error_row(self, tmp_path: Path) -> None:
        """scenarios/example-economy7.yaml with an off_peak EV: valid on Economy 10, an error row without a tariff."""
        on_economy_10 = self._validate_config(
            tmp_path, _example_economy7_with_an_off_peak_ev(lambda home: home.update(tariff={"type": "economy_10"}))
        )
        assert on_economy_10.exit_code == 0, f"premise: the home is valid with a tariff\n{on_economy_10.stdout}"

        result = self._validate_config(tmp_path, _example_economy7_with_an_off_peak_ev(lambda home: home.pop("tariff")))

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        assert "smart_charging_mode 'off_peak'" in error_row
        assert "tariff" in error_row

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
                "location: {latitude: 51.45, longitude: -2.58, altitude: .nan}\n"
                "home:\n  pv: {capacity_kw: 4.0}\n",
                "altitude",
                "nan",
                id="location-altitude-nan",
            ),
            pytest.param(
                "location: {latitude: 51.45, longitude: -2.58, timezone: Europe/Londn}\n"
                "home:\n  pv: {capacity_kw: 4.0}\n",
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
        assert "ERROR home.load: unrecognised keys '[bold]x';" in table_text(
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
                "scenarios:\n"
                "  - name: one\n"
                "    period: {start_date: '2024-01-01', end_date: '2024-01-07'}\n"
                "    home: {pv: {capacity_kw: 60.0}}\n"
                "  - name: fleet\n"
                "    period: {start_date: '2024-01-01', end_date: '2024-01-07'}\n"
                "    seg: {rate_pence_per_kwh: 15.0}\n"
                "    homes:\n"
                "      - pv: {capacity_kw: 55.0}\n"
                "      - pv: {capacity_kw: 4.0}\n",
                "PV capacity 60.0 kW seems high for domestic (2 of 3 homes above 50 kW)",
                id="pv-scenarios",
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
                "  battery: {capacity_kwh: 5.0, dispatch_strategy: {strategy_type: tou_optimized}}\n",
                id="fleet-distribution",
            ),
            pytest.param(
                _SWEEP_FLEET + "    dispatch_strategy: {strategy_type: tou_optimized}\n", id="fleet-sweep"
            ),
        ],
    )
    def test_a_fleet_of_tou_optimized_batteries_and_no_tariff_is_an_error_row(
        self, tmp_path: Path, document: str
    ) -> None:
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        assert "tou_optimized" in error_row
        assert "tariff" in error_row
        assert "WARNING" not in text

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param(
                "fleet_distribution:\n"
                "  n_homes: 2\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  battery: {capacity_kwh: 5.0}\n"
                "  dispatch_strategy: tou_optimized\n",
                id="fleet-distribution",
            ),
            pytest.param(
                "fleet_distribution:\n"
                "  n_homes: 2\n"
                "  pv: {capacity_kw: 4.0}\n"
                "  dispatch_strategy: tou_optimized\n",
                id="fleet-without-batteries",
            ),
            pytest.param(_SWEEP_FLEET + "  dispatch_strategy: tou_optimized\n", id="fleet-sweep"),
        ],
    )
    def test_a_fleet_level_dispatch_strategy_is_an_error_row_naming_the_batterys(
        self, tmp_path: Path, document: str
    ) -> None:
        """The dispatch strategy is the battery's own setting, so `validate config` reports the retired fleet-level key, with or without batteries, naming where it goes."""
        result = self._validate_config(tmp_path, document)

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        assert re.search(retired_dispatch_strategy_refusal("fleet_distribution.dispatch_strategy"), error_row), error_row

    def test_a_flat_home_files_dispatch_strategy_is_an_error_row_naming_the_batterys(self, tmp_path: Path) -> None:
        """A flat home file is itself a home block, so `validate config` reports its retired dispatch_strategy key naming where it goes."""
        result = self._validate_config(
            tmp_path, "pv: {capacity_kw: 4.0}\nbattery: {capacity_kwh: 5.0}\ndispatch_strategy: tou_optimized\n"
        )

        assert result.exit_code == 1
        text = table_text(result.stdout)
        assert "ERROR" in text
        error_row = text[text.index("ERROR"):]
        assert re.search(retired_dispatch_strategy_refusal("dispatch_strategy"), error_row), error_row
