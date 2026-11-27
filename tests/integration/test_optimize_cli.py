# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for `optimize configs`, W3 sweep E's command.

The report it prints, board_report.generate_config_ranking_report's, is
tested in tests/unit/test_config_ranking_report.py and
tests/unit/test_board_report.py.
"""
from __future__ import annotations

import re
import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Optional

import pytest
import yaml
from typer.testing import CliRunner, Result

from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.main import app
from solar_challenge.errors import ConfigurationError
from solar_challenge.config import load_scenario
from solar_challenge.fleet import FleetConfig, FleetResults, default_runner
from solar_challenge.optimize import SENSITIVITY_BANDS
from solar_challenge.projection import fewest_simulated_ages
from solar_challenge.scenario_knobs import KNOBS, knob_named
from solar_challenge.weather import WeatherCache
from tests._cli_fleet_simulator import ReachedTheSweep, answering, invoke_cli, simulate_reaching_the_sweep
from tests._cli_stderr_text import stderr_text
from tests._finance_builders import make_fleet_results, make_home_config
from tests._fleet_simulate_stand_in import answering_with
from tests._ranking_report_tables import RANK, TRADE_OFF, config_row, section_under
from tests._repository_paths import SCENARIOS_DIR
from tests._synthetic_weather import synthetic_tmy
from tests.integration._helpers import SCENARIO


# ---------------------------------------------------------------------------
# §A — The patched `optimize configs` tests' scenario writer
# ---------------------------------------------------------------------------


def _write_optimize_scenario(
    tmp_path: Path,
    n_homes: int = 5,
    *,
    finance_overrides: Optional[dict[str, object]] = None,
    seg_rate: Optional[float] = None,
) -> Path:
    """Write a minimal feasible-regime scenario YAML to tmp_path, its finance block updated with *finance_overrides*, and its top-level SEG rate *seg_rate* when given."""
    scenario: dict[str, object] = {
        "name": "W3 Optimize CLI Test",
        "location": {
            "latitude": 51.45,
            "longitude": -2.58,
            "timezone": "Europe/London",
        },
        "fleet_distribution": {
            "n_homes": n_homes,
            "seed": 42,
            "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
            "battery": {"capacity_kwh": None},
            "load": {"annual_consumption_kwh": 3500},
        },
        "finance": {
            "standing_charge_pence_per_day": 28.0,
            # Interior feasibility: high capex, no grant, floor=100, retail=30p
            "pv_cost_per_kwp_gbp": 2000.0,
            "battery_cost_per_kwh_gbp": 300.0,
            "inverter_cost_per_kw_gbp": 200.0,
            "grant_gbp": 0.0,
            "own_use_rate_pence_per_kwh": 15.0,
            "retained_cash_floor_per_home_per_year_gbp": 100.0,
            "retail_baseline_rate_pence_per_kwh": 30.0,
            "asset_life_years": 25,
            "vat_rate": 0.05,
            **(finance_overrides or {}),
        },
    }
    if seg_rate is not None:
        scenario["seg"] = {"rate_pence_per_kwh": seg_rate}
    path = tmp_path / "optimize_scenario.yaml"
    path.write_text(yaml.dump(scenario))
    return path


# ---------------------------------------------------------------------------
# §B — CLI registration + help
# ---------------------------------------------------------------------------


class TestOptimizeCLIHelp:
    """`optimize configs --help` exits 0 and lists required flags."""

    def test_optimize_help_shows_configs_command(self) -> None:
        """`optimize --help` must list the 'configs' subcommand."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "--help"])
        assert result.exit_code == 0, (
            f"Expected exit 0 for 'optimize --help':\n{result.output}"
        )
        assert "configs" in result.output.lower(), (
            f"Expected 'configs' subcommand in 'optimize --help':\n{result.output}"
        )

    def test_optimize_configs_help_exits_zero(self) -> None:
        """`optimize configs --help` must exit 0."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert result.exit_code == 0, (
            f"Expected exit 0 for 'optimize configs --help':\n{result.output}"
        )

    def test_pv_flag_in_help(self) -> None:
        """`optimize configs --help` must show --pv flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--pv" in result.output, (
            f"Expected '--pv' flag in help:\n{result.output}"
        )

    def test_battery_flag_in_help(self) -> None:
        """`optimize configs --help` must show --battery flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--battery" in result.output, (
            f"Expected '--battery' flag in help:\n{result.output}"
        )

    def test_inverter_flag_in_help(self) -> None:
        """`optimize configs --help` must show --inverter flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--inverter" in result.output, (
            f"Expected '--inverter' flag in help:\n{result.output}"
        )

    def test_retained_floor_flag_in_help(self) -> None:
        """`optimize configs --help` must show --retained-floor flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--retained-floor" in result.output, (
            f"Expected '--retained-floor' flag in help:\n{result.output}"
        )

    def test_grid_services_kw_flag_in_help(self) -> None:
        """`optimize configs --help` must show --grid-services-kw flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--grid-services-kw" in result.output, (
            f"Expected '--grid-services-kw' flag in help:\n{result.output}"
        )

    def test_sensitivity_flag_in_help(self) -> None:
        """`optimize configs --help` must show --sensitivity flag."""
        runner = CliRunner()
        result = runner.invoke(app, ["optimize", "configs", "--help"])
        assert "--sensitivity" in result.output, (
            f"Expected '--sensitivity' flag in help:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# §C — fast injected-simulate E2E
# ---------------------------------------------------------------------------


def _feasible_fleet_results(n_homes: int) -> FleetResults:
    """*n_homes* default homes, each self-consuming 2,000 kWh, exporting 800 and importing 1,200 a year.

    Under _write_optimize_scenario's finance the cost-recovery solve binds at
    the floor and is feasible.
    """
    return make_fleet_results(n_homes=n_homes, self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0)


@pytest.fixture(scope="module")
def optimize_fleet_results() -> FleetResults:
    """Module-scoped fixture: constant feasible FleetResults for a five-home scenario, built once per module."""
    return _feasible_fleet_results(n_homes=5)


@pytest.fixture(scope="module")
def one_home_fleet_results() -> FleetResults:
    """Module-scoped fixture: constant feasible FleetResults for a one-home scenario, built once per module."""
    return _feasible_fleet_results(n_homes=1)


# Each --sensitivity alias the CLI documents → the knob whose axis section it adds to the report.
_SENSITIVITY_ALIAS_KNOBS: dict[str, str] = {
    "retained_floor": "retained_cash_floor_per_home_per_year_gbp",
    "grid_services": "grid_services_income_per_kw_per_year_gbp",
    "battery_cost": "battery_cost_per_kwh_gbp",
    "pv_cost": "pv_cost_per_kwp_gbp",
    "inverter_cost": "inverter_cost_per_kw_gbp",
}


def test_the_documented_sensitivity_aliases_cover_exactly_the_library_bands() -> None:
    """Each documented alias names its knob in the registry, and their knobs are exactly the optimize.SENSITIVITY_BANDS knobs, so the end-to-end alias test covers every band."""
    assert [alias for alias, knob in _SENSITIVITY_ALIAS_KNOBS.items() if knob_named(alias) is not KNOBS[knob]] == []
    assert {KNOBS[knob] for knob in _SENSITIVITY_ALIAS_KNOBS.values()} == set(SENSITIVITY_BANDS), (
        "Every library band must be reachable from a CLI alias."
    )


def _swept_values_by_axis(report: str) -> dict[str, list[float]]:
    """Return, for each '### Axis: <knob>' section of a config-ranking report, the values its table rows sweep."""
    swept: dict[str, list[float]] = {}
    axis_values: list[float] | None = None
    for line in report.splitlines():
        if line.startswith("### Axis: "):
            axis_values = swept.setdefault(line.removeprefix("### Axis: "), [])
        elif line.startswith("#"):
            axis_values = None
        elif axis_values is not None and line.startswith("| ") and not line.startswith("| Value"):
            axis_values.append(float(line.split("|")[1]))
    return swept


def _pounds(cell: str) -> float:
    """The figure of a report's '£1,234.56', '+£1,234.56' or '-£3.25' cell."""
    return float(cell.replace("£", "").replace(",", ""))


def _invoke_configs(
    tmp_path: Path,
    fleet_results: FleetResults,
    options: list[str],
    *,
    n_homes: int = 5,
    finance_overrides: Optional[dict[str, object]] = None,
    seg_rate: Optional[float] = None,
) -> tuple[Result, list[FleetConfig]]:
    """Run `optimize configs` on a fresh *n_homes*-home scenario, its finance block updated with *finance_overrides* and its SEG rate *seg_rate* when given, with *options*, answering every fleet simulation with *fleet_results*' per-home results, paired with that fleet's homes.

    Returns the CliRunner result and the fleet configs the injected simulator
    was asked to simulate.
    """
    simulated_fleets: list[FleetConfig] = []
    answer = answering_with(fleet_results)

    def simulate(fleet_config, start, end):
        simulated_fleets.append(fleet_config)
        return answer(fleet_config, start, end)

    scenario_file = _write_optimize_scenario(
        tmp_path, n_homes=n_homes, finance_overrides=finance_overrides, seg_rate=seg_rate
    )
    result = invoke_cli(["optimize", "configs", str(scenario_file), *options], answering(simulate))
    return result, simulated_fleets


class TestOptimizeCLIE2EFast:
    """Fast injected-simulator end-to-end tests for `optimize configs` wiring (G2/W-H6 signal).

    Each test that runs a sweep passes its own fleet simulator as the Click
    context object (``obj=CliInvocation(runner=...)``), so the whole sweep,
    sensitivity panel included, runs offline without PVGIS.
    """

    def test_optimize_configs_standard_sweep_output(
        self,
        tmp_path: Path,
        optimize_fleet_results: FleetResults,
    ) -> None:
        """Standard sweep must exit 0 and produce all expected report tokens.

        Invokes `optimize configs` once and asserts the union of wiring signals
        (exit code, the sweep's use of the injected simulator, both table headings
        using exact strings, sensitivity heading, recommendation marker, and rate
        token) to avoid re-running the CLI and its injected simulator once per
        assertion.
        """
        result, simulated_fleets = _invoke_configs(
            tmp_path,
            optimize_fleet_results,
            [
                "--pv", "4",
                "--battery", "0,5",
                "--inverter", "5",
                "--sensitivity", "grid_services",
            ],
        )

        assert result.exit_code == 0, (
            f"Expected exit 0 from 'optimize configs'; got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )
        assert simulated_fleets, (
            "Expected 'optimize configs' to run its sweep with the simulator passed as "
            "obj=CliInvocation(runner=...); it asked that simulator for no fleet simulation.\n"
            f"Output:\n{result.output}"
        )
        assert "cost-recovery rank" in result.output.lower(), (
            f"Expected cost-recovery rank heading in output:\n{result.output}"
        )
        # Exact heading — guards against regressions that drop the section.
        assert f"{TRADE_OFF}\n" in result.output, (
            f"Expected {TRADE_OFF!r} heading in output:\n{result.output}"
        )
        assert "sensitivity" in result.output.lower(), (
            f"Expected sensitivity section heading in output:\n{result.output}"
        )
        assert (
            "recommendation" in result.output.lower()
            or "★" in result.output
        ), (
            f"Expected RECOMMENDATION marker in output:\n{result.output}"
        )
        assert "p/kWh" in result.output, (
            f"Expected 'p/kWh' solved-rate token in output:\n{result.output}"
        )

    def test_every_sensitivity_alias_sweeps_its_knobs_library_band(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """Each alias's axis sweeps exactly its knob's optimize.SENSITIVITY_BANDS values."""
        result, _ = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            [
                "--pv", "4",
                "--battery", "0",
                "--inverter", "5",
                "--sensitivity", ",".join(_SENSITIVITY_ALIAS_KNOBS),
            ],
            n_homes=1,
        )

        assert result.exit_code == 0, (
            f"Expected exit 0 from 'optimize configs'; got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )
        swept = _swept_values_by_axis(result.stdout)
        assert set(swept) == set(_SENSITIVITY_ALIAS_KNOBS.values()), (
            f"Expected one axis section per alias's knob in the report:\n{result.output}"
        )
        for knob in _SENSITIVITY_ALIAS_KNOBS.values():
            assert swept[knob] == pytest.approx(SENSITIVITY_BANDS[KNOBS[knob]], abs=0.005), (
                f"Axis {knob} swept {swept[knob]}, not its SENSITIVITY_BANDS values.\n"
                f"Output:\n{result.output}"
            )

    def test_a_banded_knobs_canonical_name_sweeps_its_band(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """--sensitivity takes a knob's canonical name as well as its alias, sweeping that knob's band."""
        knob = "retained_cash_floor_per_home_per_year_gbp"
        result, _ = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            ["--pv", "4", "--battery", "0", "--inverter", "5", "--sensitivity", knob],
            n_homes=1,
        )

        assert result.exit_code == 0, result.output
        swept = _swept_values_by_axis(result.stdout)
        assert list(swept) == [knob], result.output
        assert swept[knob] == pytest.approx(SENSITIVITY_BANDS[KNOBS[knob]], abs=0.005), result.output

    def test_a_knob_without_a_band_is_refused_naming_it_and_every_banded_knob_before_any_simulation(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """A knob with no sensitivity band is a configuration error naming it and the banded knobs, refused before the sweep."""
        result, simulated_fleets = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            ["--pv", "4", "--battery", "0", "--inverter", "5", "--sensitivity", "seg"],
            n_homes=1,
        )

        assert result.exit_code == 1, result.output
        refusal = stderr_text(result)
        assert refusal.startswith("Configuration error:"), refusal
        assert "seg_tariff_pence_per_kwh" in refusal
        assert "band" in refusal
        assert [knob.name for knob in SENSITIVITY_BANDS if knob.name not in refusal] == [], refusal
        assert simulated_fleets == []

    def test_a_knob_named_twice_is_refused_naming_both_spellings_before_any_simulation(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """A knob named by its alias and by its canonical name is a configuration error naming both, refused before the sweep."""
        canonical = "retained_cash_floor_per_home_per_year_gbp"
        result, simulated_fleets = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            ["--pv", "4", "--battery", "0", "--inverter", "5", "--sensitivity", f"retained_floor,{canonical}"],
            n_homes=1,
        )

        assert result.exit_code == 1, result.output
        refusal = stderr_text(result)
        assert refusal.startswith("Configuration error:"), refusal
        assert f"as retained_floor and as {canonical}" in refusal, refusal
        assert simulated_fleets == []

    def test_parse_robustness_single_pv_value_works(
        self,
        tmp_path: Path,
        optimize_fleet_results: FleetResults,
    ) -> None:
        """Single value `--pv 4` (no comma) must parse correctly and succeed.

        Robustness: the comma-list parser must handle a single non-comma value
        without raising an error.
        """
        result, _ = _invoke_configs(
            tmp_path,
            optimize_fleet_results,
            [
                "--pv", "4",         # single value, no comma
                "--battery", "0",    # single battery
                "--inverter", "5",   # single inverter
                "--sensitivity", "",  # skip sensitivity
            ],
        )

        assert result.exit_code == 0, (
            f"Expected exit 0 for single-value --pv 4; got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )

    def test_the_default_sensitivity_without_events_sweeps_the_retained_floor_and_grid_services_axes(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """With no --sensitivity, a scenario that prices no grid services at events sweeps both default axes and notes no omission."""
        result, _ = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            ["--pv", "4", "--battery", "0", "--inverter", "5"],
            n_homes=1,
        )

        assert result.exit_code == 0, result.output
        assert set(_swept_values_by_axis(result.stdout)) == {
            "retained_cash_floor_per_home_per_year_gbp",
            "grid_services_income_per_kw_per_year_gbp",
        }, result.output
        assert "capacity_at_events" not in result.stderr, result.stderr

    def test_the_default_sensitivity_under_the_events_model_omits_the_grid_services_axis_with_a_note(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """C8: with no --sensitivity, a scenario that prices grid services at events sweeps the retained floor alone, and one stderr note names the omitted grid_services axis and why."""
        result, _ = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            ["--pv", "4", "--battery", "0", "--inverter", "5"],
            n_homes=1,
            finance_overrides={"grid_services_model": {"type": "capacity_at_events", "band": "central"}},
        )

        stderr = " ".join(result.stderr.split())
        assert result.exit_code == 0, result.output
        assert stderr.count("capacity_at_events") == 1, stderr
        assert "axis grid_services" in stderr, stderr
        assert set(_swept_values_by_axis(result.stdout)) == {
            "retained_cash_floor_per_home_per_year_gbp"
        }, result.output

    def test_grid_services_kw_under_the_flat_model_prices_the_battery_at_the_flag_rate(
        self,
        tmp_path: Path,
    ) -> None:
        """--grid-services-kw sets the flat rate a battery's discharge power earns, so it raises the baseline CBS surplus by that rate × the home's discharge power."""
        battery = BatteryConfig(capacity_kwh=5.0)
        fleet_results = make_fleet_results(
            homes=[make_home_config(battery_config=battery)],
            self_kwh=2000.0,
            export_kwh=800.0,
            import_kwh=1200.0,
        )

        def baseline_surplus_gbp(options: list[str]) -> float:
            result, _ = _invoke_configs(
                tmp_path,
                fleet_results,
                ["--pv", "4", "--battery", "5", "--inverter", "5", "--sensitivity", "", *options],
                n_homes=1,
            )
            assert result.exit_code == 0, result.output
            row = config_row(result.stdout, TRADE_OFF, "4.0 kWp / 5.0 kWh / 5.0 kW")
            return float(row["Baseline CBS Surplus (£/home/yr)"].removeprefix("£"))

        assert baseline_surplus_gbp(["--grid-services-kw", "20"]) - baseline_surplus_gbp(
            []
        ) == pytest.approx(20.0 * battery.max_discharge_kw, abs=0.01)

    def test_the_trade_off_table_names_the_scenarios_own_use_rate(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        result, _ = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            ["--pv", "4", "--battery", "0", "--inverter", "5", "--sensitivity", ""],
            n_homes=1,
            finance_overrides={"own_use_rate_pence_per_kwh": 12.0},
        )

        assert result.exit_code == 0, result.output
        row = config_row(result.stdout, TRADE_OFF, "4.0 kWp / 0.0 kWh / 5.0 kW")
        assert row["Configured Rate (p/kWh)"] == "12.00 p/kWh", result.stdout

    def test_each_config_asks_its_simulator_for_one_projection(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """Two configs over _write_optimize_scenario's 25-year asset life, each one smooth projection."""
        result, simulated_fleets = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            ["--pv", "4,5", "--battery", "0", "--inverter", "5", "--sensitivity", ""],
            n_homes=1,
        )

        assert result.exit_code == 0, result.output
        assert len(simulated_fleets) == 2 * fewest_simulated_ages(25), [fleet.name for fleet in simulated_fleets]

    def test_every_fleet_the_sweep_simulates_pays_the_scenarios_seg_rate(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        result, simulated_fleets = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            ["--pv", "4", "--battery", "0", "--inverter", "5", "--sensitivity", ""],
            n_homes=1,
            seg_rate=5.5,
        )

        assert result.exit_code == 0, result.output
        rates = [
            home.seg_tariff.rate_pence_per_kwh if home.seg_tariff is not None else None
            for fleet in simulated_fleets
            for home in fleet.homes
        ]
        assert rates, result.output
        assert rates == [5.5] * len(rates)

    def test_unknown_sensitivity_alias_exits_one(
        self,
        tmp_path: Path,
    ) -> None:
        """An unknown `--sensitivity` name is knob_named's configuration error, listing the knobs and their aliases."""
        scenario_file = _write_optimize_scenario(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "optimize", "configs", str(scenario_file),
                "--pv", "4",
                "--battery", "0",
                "--inverter", "5",
                "--sensitivity", "completely_unknown_alias_xyz",
            ],
        )

        assert result.exit_code == 1, (
            f"Expected exit 1 for unknown sensitivity alias; got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )
        refusal = stderr_text(result)
        assert refusal.startswith("Configuration error:"), refusal
        assert "completely_unknown_alias_xyz" in refusal
        assert "retained_cash_floor_per_home_per_year_gbp" in refusal
        assert "retained_floor" in refusal

    def test_a_plain_value_error_while_the_sensitivity_panel_runs_exits_one_as_an_invalid_value(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """A plain ValueError raised while the sensitivity panel runs ends the command with exit 1 and its invalid-value line on stderr; the panel is not skipped.

        A run without the panel counts the simulations the sweep asks for; the
        simulator answers that many and raises on the next, which the panel asks for.
        """
        options = ["--pv", "4", "--battery", "0", "--inverter", "5"]
        sweep_only, sweep_fleets = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            [*options, "--sensitivity", ""],
            n_homes=1,
        )
        assert sweep_only.exit_code == 0, sweep_only.output
        asked: list[object] = []
        answer = answering_with(one_home_fleet_results)

        def simulate(fleet_config, start, end):
            asked.append(fleet_config)
            if len(asked) > len(sweep_fleets):
                raise ValueError("a defect raised while the sensitivity panel runs")
            return answer(fleet_config, start, end)

        result = invoke_cli(
            [
                "optimize", "configs", str(_write_optimize_scenario(tmp_path, n_homes=1)),
                *options,
                "--sensitivity", "grid_services",
            ],
            answering(simulate),
        )

        assert len(asked) > len(sweep_fleets), "the panel asked for no simulation"
        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        stderr = " ".join(result.stderr.split())
        assert "Computing sensitivity panel for axes" in stderr
        assert stderr.endswith("Invalid value: a defect raised while the sensitivity panel runs")
        assert "Sensitivity panel skipped" not in result.output

    def test_the_sensitivity_panel_is_skipped_with_a_note_when_the_sweep_has_no_feasible_config(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """With every config infeasible, the command prints the report without the panel, notes the skip on stderr and exits 0."""
        options = ["--pv", "4", "--battery", "0", "--inverter", "5"]
        result, _ = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            [*options, "--retained-floor", "9999999", "--sensitivity", "grid_services"],
            n_homes=1,
        )

        assert result.exit_code == 0, result.output
        assert "## Cost-Recovery Rank" in result.stdout
        assert "## Sensitivity Analysis" not in result.stdout
        stderr = " ".join(result.stderr.split())
        assert "Computing sensitivity panel" not in stderr
        assert stderr.endswith(
            "Sensitivity panel skipped: no feasible baseline config found "
            "(sensitivity requires at least one feasible config)."
        )

    def test_a_refusal_while_the_sensitivity_panel_runs_exits_one_as_a_configuration_error(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """A ConfigurationError raised while the sensitivity panel runs ends the command with exit 1 and its configuration-error line on stderr; the panel is not skipped.

        A run without the panel counts the simulations the sweep asks for; the
        simulator answers that many and refuses the next, which the panel asks for.
        """
        options = ["--pv", "4", "--battery", "0", "--inverter", "5"]
        sweep_only, sweep_fleets = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            [*options, "--sensitivity", ""],
            n_homes=1,
        )
        assert sweep_only.exit_code == 0, sweep_only.output
        asked: list[object] = []
        answer = answering_with(one_home_fleet_results)

        def simulate(fleet_config, start, end):
            asked.append(fleet_config)
            if len(asked) > len(sweep_fleets):
                raise ConfigurationError("a refusal raised while the sensitivity panel runs")
            return answer(fleet_config, start, end)

        result = invoke_cli(
            [
                "optimize", "configs", str(_write_optimize_scenario(tmp_path, n_homes=1)),
                *options,
                "--sensitivity", "grid_services",
            ],
            answering(simulate),
        )

        assert len(asked) > len(sweep_fleets), "the panel asked for no simulation"
        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        stderr = " ".join(result.stderr.split())
        assert "Computing sensitivity panel for axes" in stderr
        assert stderr.endswith("Configuration error: a refusal raised while the sensitivity panel runs")
        assert "Sensitivity panel skipped" not in result.output

    def test_the_default_sensitivity_asks_for_six_sweeps_and_reuses_the_baseline_at_the_scenarios_floor(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """C8: the default axes sweep three floors and three grid-services rates, and the floor band's value at the scenario's own floor reuses the sweep the report ranks, so the run asks for six sweeps' simulations."""
        floor_band = SENSITIVITY_BANDS[KNOBS["retained_cash_floor_per_home_per_year_gbp"]]
        grid_band = SENSITIVITY_BANDS[KNOBS["grid_services_income_per_kw_per_year_gbp"]]
        assert 27.0 in floor_band, f"The premise needs 27.0 in the floor band {floor_band}"
        assert 6.0 not in grid_band, f"The premise needs 6.0 outside the grid-services band {grid_band}"
        finance_overrides: dict[str, object] = {
            "retained_cash_floor_per_home_per_year_gbp": 27.0,
            "grid_services_model": {"type": "flat", "income_per_kw_per_year_gbp": 6.0},
        }
        options = ["--pv", "4", "--battery", "0", "--inverter", "5"]
        sweep_only, one_sweeps_fleets = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            [*options, "--sensitivity", ""],
            n_homes=1,
            finance_overrides=finance_overrides,
        )
        assert sweep_only.exit_code == 0, sweep_only.output

        result, simulated_fleets = _invoke_configs(
            tmp_path, one_home_fleet_results, options, n_homes=1, finance_overrides=finance_overrides
        )

        assert result.exit_code == 0, result.output
        assert len(simulated_fleets) == 6 * len(one_sweeps_fleets)
        swept = _swept_values_by_axis(result.stdout)
        assert swept["retained_cash_floor_per_home_per_year_gbp"] == pytest.approx(floor_band, abs=0.005), result.stdout
        assert swept["grid_services_income_per_kw_per_year_gbp"] == pytest.approx(grid_band, abs=0.005), result.stdout

    def test_retained_floor_at_the_scenarios_own_floor_changes_neither_the_report_nor_the_simulations(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """C9: --retained-floor at the scenario's own floor of 27 is the scenario's floor, so the run reports and simulates exactly as it does without the flag."""
        finance_overrides: dict[str, object] = {
            "retained_cash_floor_per_home_per_year_gbp": 27.0,
            "grid_services_model": {"type": "flat", "income_per_kw_per_year_gbp": 6.0},
        }
        options = ["--pv", "4", "--battery", "0", "--inverter", "5"]
        without_flag, fleets_without_flag = _invoke_configs(
            tmp_path, one_home_fleet_results, options, n_homes=1, finance_overrides=finance_overrides
        )
        with_flag, fleets_with_flag = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            [*options, "--retained-floor", "27"],
            n_homes=1,
            finance_overrides=finance_overrides,
        )

        assert without_flag.exit_code == 0, without_flag.output
        assert with_flag.exit_code == 0, with_flag.output
        assert with_flag.stdout == without_flag.stdout
        assert len(fleets_with_flag) == len(fleets_without_flag)

    def test_retained_floor_sets_the_floor_the_solve_binds_at(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """--retained-floor 60 on the scenario's floor of 100 is the floor the ranked configs' solve binds at, with the floor axis still swept."""
        result, _ = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            ["--pv", "4", "--battery", "0", "--inverter", "5", "--retained-floor", "60"],
            n_homes=1,
        )

        assert result.exit_code == 0, result.output
        row = config_row(result.stdout, "## Cost-Recovery Rank", "4.0 kWp / 0.0 kWh / 5.0 kW")
        assert row["CBS Surplus (£/home/yr)"] == "£60.00", result.stdout
        assert "retained_cash_floor_per_home_per_year_gbp" in _swept_values_by_axis(result.stdout), result.stdout

    # One PV size, with and without a battery, and no sensitivity panel: the --assumptions tests' sweep.
    _ASSUMPTION_SWEEP: tuple[str, ...] = ("--pv", "4", "--battery", "0,5", "--inverter", "5", "--sensitivity", "")

    def _invoke_on_override(
        self,
        tmp_path: Path,
        run: str,
        fleet_results: FleetResults,
        override: Optional[float],
        *assumptions: str,
    ) -> tuple[Result, list[FleetConfig]]:
        """Run _ASSUMPTION_SWEEP with *assumptions* on a one-home scenario whose finance sets *override*, none when None, written in *run*'s own directory under *tmp_path*."""
        run_dir = tmp_path / run
        run_dir.mkdir()
        return _invoke_configs(
            run_dir,
            fleet_results,
            [*self._ASSUMPTION_SWEEP, *assumptions],
            n_homes=1,
            finance_overrides=None if override is None else {"self_consumption_override": override},
        )

    def test_without_assumptions_a_scenarios_override_is_cleared_and_the_ranking_is_physics(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """A scenario whose finance overrides own-use to 0.7 reports, by default, exactly as the scenario without the override."""
        overridden, _ = self._invoke_on_override(tmp_path, "overridden", one_home_fleet_results, 0.7)
        plain, _ = self._invoke_on_override(tmp_path, "plain", one_home_fleet_results, None)

        assert overridden.exit_code == 0, overridden.output
        assert plain.exit_code == 0, plain.output
        assert overridden.stdout.startswith("Self-consumption assumption: **Physics**\n"), overridden.stdout
        assert overridden.stdout == plain.stdout

    def test_spreadsheet_ranks_under_the_scenarios_override(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """Under --assumptions spreadsheet the 0.7 override's own-use, 1,960 of the stand-in's 2,800 kWh generation, prices the trade-off, not the simulated 2,000.

        The 40 kWh below the simulated own-use is imported at the scenario's 30 p
        retail baseline rather than paid for as own-use at its 15 p configured
        rate, so the spreadsheet's baseline outlay is that 40 kWh × 15 p, with
        5% VAT, above physics'.
        """
        spreadsheet, _ = self._invoke_on_override(
            tmp_path, "spreadsheet", one_home_fleet_results, 0.7, "--assumptions", "spreadsheet"
        )
        physics, _ = self._invoke_on_override(
            tmp_path, "physics", one_home_fleet_results, 0.7, "--assumptions", "physics"
        )

        assert spreadsheet.exit_code == 0, spreadsheet.output
        assert physics.exit_code == 0, physics.output
        assert spreadsheet.stdout.startswith(
            "Self-consumption assumption: **Spreadsheet (70% self-consumption)**\n"
        ), spreadsheet.stdout
        no_battery = "4.0 kWp / 0.0 kWh / 5.0 kW"
        spreadsheet_outlay = config_row(spreadsheet.stdout, TRADE_OFF, no_battery)["Baseline Outlay (£/yr)"]
        physics_outlay = config_row(physics.stdout, TRADE_OFF, no_battery)["Baseline Outlay (£/yr)"]
        simulated_own_use_kwh, generation_kwh = 2000.0, 2000.0 + 800.0
        own_use_moved_to_import_kwh = simulated_own_use_kwh - 0.7 * generation_kwh
        retail_pence, configured_own_use_pence, vat_rate = 30.0, 15.0, 0.05
        assert _pounds(spreadsheet_outlay) - _pounds(physics_outlay) == pytest.approx(
            own_use_moved_to_import_kwh * (retail_pence - configured_own_use_pence) / 100.0 * (1.0 + vat_rate),
            abs=0.011,
        ), spreadsheet.stdout

    @pytest.mark.parametrize(
        ("override", "label"),
        [(0.6, "Spreadsheet (60% self-consumption)"), (None, "Spreadsheet (70% self-consumption)")],
        ids=["the-scenarios-own", "the-default"],
    )
    def test_spreadsheet_keeps_the_scenarios_override_or_sets_the_default(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
        override: Optional[float],
        label: str,
    ) -> None:
        result, _ = self._invoke_on_override(
            tmp_path, "spreadsheet", one_home_fleet_results, override, "--assumptions", "spreadsheet"
        )

        assert result.exit_code == 0, result.output
        assert result.stdout.startswith(f"Self-consumption assumption: **{label}**\n"), result.stdout

    def test_spreadsheet_runs_the_sensitivity_panel_under_the_scenarios_override(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """The panel sweeps configs on the ranking's assumption: given configs on another than its baseline's, it would refuse them before reaching the report."""
        result, _ = _invoke_configs(
            tmp_path,
            one_home_fleet_results,
            ["--pv", "4", "--battery", "0", "--inverter", "5", "--assumptions", "spreadsheet",
             "--sensitivity", "retained_floor"],
            n_homes=1,
            finance_overrides={"self_consumption_override": 0.7},
        )

        assert result.exit_code == 0, result.output
        assert result.stdout.startswith(
            "Self-consumption assumption: **Spreadsheet (70% self-consumption)**\n"
        ), result.stdout
        assert _swept_values_by_axis(result.stdout) == {
            "retained_cash_floor_per_home_per_year_gbp": list(
                SENSITIVITY_BANDS[KNOBS["retained_cash_floor_per_home_per_year_gbp"]]
            )
        }, result.stdout

    def test_both_assumptions_are_refused_before_any_simulation(
        self,
        tmp_path: Path,
        one_home_fleet_results: FleetResults,
    ) -> None:
        """A ranking is computed under one assumption: --assumptions both, which names two, is a configuration error naming it."""
        result, simulated_fleets = self._invoke_on_override(
            tmp_path, "both", one_home_fleet_results, 0.7, "--assumptions", "both"
        )

        assert result.exit_code == 1, result.output
        refusal = stderr_text(result)
        assert refusal.startswith("Configuration error:"), refusal
        assert "both" in refusal, refusal
        assert simulated_fleets == []


# ---------------------------------------------------------------------------
# §C2 — --battery-kw sizes each battery's power, and --reference names what the marginal columns compare against
# ---------------------------------------------------------------------------


_REFERENCE_LINE = "Marginal columns compare each configuration against the reference **"
_SMALL = "4.0 kWp / 5.1 kWh at 2.4 kW / 3.7 kW"
_LARGE = "4.0 kWp / 10.2 kWh at 3.7 kW / 3.7 kW"
_EXTRA_CAPEX = "Extra CapEx vs Reference (£/home)"
_OUTLAY_CHANGE = "Outlay Change vs Reference (£/yr)"


class TestBatteryPowerAndReference:
    """`optimize configs --battery-kw` pairs a power with each --battery size, and --reference names the marginal columns' reference."""

    _GRID = ["--pv", "4", "--inverter", "3.68", "--sensitivity", "", "--battery", "5.12,10.24"]
    _PAIRED = [*_GRID, "--battery-kw", "2.4,3.68"]

    def test_each_battery_size_is_simulated_at_its_power(
        self, tmp_path: Path, optimize_fleet_results: FleetResults
    ) -> None:
        result, asked = _invoke_configs(tmp_path, optimize_fleet_results, self._PAIRED)

        assert result.exit_code == 0, result.output
        powers = {
            (battery.capacity_kwh, battery.max_charge_kw, battery.max_discharge_kw)
            for fleet in asked
            for home in fleet.homes
            if (battery := home.battery_config) is not None
        }
        assert powers == {(5.12, 2.4, 2.4), (10.24, 3.68, 3.68)}

    def test_a_power_count_other_than_the_size_count_is_refused_naming_both_flags_before_any_simulation(
        self, tmp_path: Path, optimize_fleet_results: FleetResults
    ) -> None:
        result, asked = _invoke_configs(tmp_path, optimize_fleet_results, [*self._GRID, "--battery-kw", "2.4"])

        stderr = " ".join(result.stderr.split())
        assert result.exit_code == 1, result.output
        assert "Configuration error:" in stderr
        assert re.search(r"--battery(?!-kw)", stderr)
        assert "--battery-kw" in stderr
        assert asked == []

    def test_without_a_reference_the_smallest_battery_at_the_smallest_pv_is_the_reference(
        self, tmp_path: Path, optimize_fleet_results: FleetResults
    ) -> None:
        result, _ = _invoke_configs(tmp_path, optimize_fleet_results, self._PAIRED)

        assert result.exit_code == 0, result.output
        assert f"{_REFERENCE_LINE}{_SMALL}**" in section_under(result.stdout, RANK)
        row = config_row(result.stdout, RANK, _SMALL)
        assert (row[_EXTRA_CAPEX], row[_OUTLAY_CHANGE]) == ("+£0", "+£0.00")

    def test_a_reference_names_the_configuration_every_row_is_compared_against(
        self, tmp_path: Path, optimize_fleet_results: FleetResults
    ) -> None:
        result, _ = _invoke_configs(tmp_path, optimize_fleet_results, [*self._PAIRED, "--reference", "4,10.24,3.68,3.68"])

        assert result.exit_code == 0, result.output
        assert f"{_REFERENCE_LINE}{_LARGE}**" in section_under(result.stdout, RANK)
        reference = config_row(result.stdout, RANK, _LARGE)
        other = config_row(result.stdout, RANK, _SMALL)
        change = _pounds(other[_OUTLAY_CHANGE])
        assert change == pytest.approx(
            _pounds(other["Rep Outlay (£)"]) - _pounds(reference["Rep Outlay (£)"]), abs=0.011
        )
        assert other["Pays For Itself"] == ("yes" if change <= 0 else "no")

    def test_a_reference_outside_the_grid_is_refused_listing_the_grid_before_any_simulation(
        self, tmp_path: Path, optimize_fleet_results: FleetResults
    ) -> None:
        result, asked = _invoke_configs(tmp_path, optimize_fleet_results, [*self._PAIRED, "--reference", "4,7,3.68,2.4"])

        stderr = " ".join(result.stderr.split())
        assert result.exit_code == 1, result.output
        assert "Configuration error:" in stderr
        assert "--reference" in stderr
        assert "4,5.12,3.68,2.4; 4,10.24,3.68,3.68" in stderr
        assert asked == []

    @pytest.mark.parametrize(
        ("battery_kw", "reference", "field"),
        [
            pytest.param(["--battery-kw", "2.4,3.68"], "4,0,3.68,2.4", "battery_kw", id="power-without-a-battery"),
            pytest.param([], "-1,5.12,3.68", "pv_kwp", id="negative-pv"),
        ],
    )
    def test_a_reference_that_is_no_configuration_is_refused_naming_it_before_any_simulation(
        self,
        tmp_path: Path,
        optimize_fleet_results: FleetResults,
        battery_kw: list[str],
        reference: str,
        field: str,
    ) -> None:
        result, asked = _invoke_configs(tmp_path, optimize_fleet_results, [*self._GRID, *battery_kw, "--reference", reference])

        stderr = " ".join(result.stderr.split())
        assert result.exit_code == 1, result.output
        assert stderr.startswith(f"Configuration error: --reference {reference}: "), stderr
        assert field in stderr
        assert asked == []

    def test_a_power_for_a_no_battery_size_is_refused_naming_both_flags_before_any_simulation(
        self, tmp_path: Path, optimize_fleet_results: FleetResults
    ) -> None:
        options = ["--pv", "4", "--inverter", "3.68", "--sensitivity", "", "--battery", "0,5.12", "--battery-kw", "2.4,3.68"]
        result, asked = _invoke_configs(tmp_path, optimize_fleet_results, options)

        stderr = " ".join(result.stderr.split())
        assert result.exit_code == 1, result.output
        assert stderr.startswith("Configuration error: --battery-kw"), stderr
        assert "--battery 0" in stderr
        assert asked == []

    @pytest.mark.parametrize(
        ("battery_kw", "reference"),
        [
            pytest.param(["--battery-kw", "2.4,3.68"], "4,5.12,3.68", id="three-values-with-battery-kw"),
            pytest.param([], "4,5.12,3.68,2.4", id="four-values-without-battery-kw"),
        ],
    )
    def test_a_reference_of_the_wrong_arity_is_refused_naming_its_form_before_any_simulation(
        self, tmp_path: Path, optimize_fleet_results: FleetResults, battery_kw: list[str], reference: str
    ) -> None:
        result, asked = _invoke_configs(tmp_path, optimize_fleet_results, [*self._GRID, *battery_kw, "--reference", reference])

        stderr = " ".join(result.stderr.split())
        assert result.exit_code == 1, result.output
        assert "Configuration error:" in stderr
        assert "--reference" in stderr
        assert "PV,BATTERY,INVERTER[,BATTERY_KW]" in stderr
        assert asked == []

    def test_the_help_lists_both_flags(self) -> None:
        result = CliRunner().invoke(app, ["optimize", "configs", "--help"])

        assert result.exit_code == 0, result.output
        assert "--battery-kw" in result.output
        assert "--reference" in result.output


# The asset life and loan term the Victron signal projects over: its projections simulate only these two ages.
_SHORT_ASSET_LIFE_YEARS = 2


def test_the_victron_sweep_prints_each_configurations_marginal_columns_against_the_smallest_battery(
    tmp_path: Path, weather_cache: WeatherCache
) -> None:
    """The signal: the Victron board scenario, cut to two 4 kWp homes, swept over four battery sizes and powers on the real engine for two winter weekdays.

    Two days, not one: the scenario meters delivery against the operational
    baseline, which needs an eligible day without an event.  A two-year asset
    life and loan term make each projection simulate two ages, not a 25-year
    life's five, so the run stays short enough for every verify.
    """
    document = yaml.safe_load((SCENARIOS_DIR / "bristol-phase1-victron.yaml").read_text(encoding="utf-8"))
    document["fleet_distribution"]["n_homes"] = 2
    document["fleet_distribution"]["pv"]["capacity_kw"] = 4.0
    document["finance"]["asset_life_years"] = _SHORT_ASSET_LIFE_YEARS
    document["finance"]["loan_term_years"] = _SHORT_ASSET_LIFE_YEARS
    path = tmp_path / "victron-two-homes.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    weather_cache.put(synthetic_tmy(), "tmy", load_scenario(path).get_location())

    result = invoke_cli(
        [
            "optimize", "configs", str(path),
            "--pv", "4", "--battery", "5.12,10.24,10.24,15.36", "--battery-kw", "2.4,2.4,3.68,3.68",
            "--inverter", "3.68", "--sensitivity", "", "--start", "2024-01-15", "--end", "2024-01-16",
        ],
        dataclasses.replace(default_runner(), parallel=False),
    )

    assert result.exit_code == 0, result.output
    rank = section_under(result.stdout, RANK)
    assert f"{_REFERENCE_LINE}{_SMALL}**" in rank
    reference = config_row(result.stdout, RANK, _SMALL)
    assert (reference[_EXTRA_CAPEX], reference[_OUTLAY_CHANGE]) == ("+£0", "+£0.00")
    header = next(line for line in rank.splitlines() if line.startswith("| Config"))
    for column in (_EXTRA_CAPEX, _OUTLAY_CHANGE, "Grid Services Income Yr 1 (£/home)", "Pays For Itself"):
        assert column in header
    rows = [line for line in rank.splitlines() if line.startswith("| ") and not line.startswith(("| Config", "|--"))]
    assert rows
    assert {line.strip("|").split("|")[-1].strip() for line in rows} <= {"yes", "no"}


# ---------------------------------------------------------------------------
# §D — `optimize configs` ignores no grid-services input under the events model
# ---------------------------------------------------------------------------


# `optimize configs` over one config of the committed board scenario, which prices grid services at events.
_ONE_BOARD_CONFIG: tuple[str, ...] = ("optimize", "configs", str(SCENARIO), "--pv", "4", "--battery", "5", "--inverter", "5")


def _invoke_configs_on_the_board(options: list[str]) -> tuple[Result, list[FleetConfig]]:
    """Run `optimize configs` over one config of the committed board scenario, which prices grid services at events, with *options*.

    Returns the CliRunner result and the fleet configs the injected simulator
    was asked to simulate, each answered with make_fleet_results over that
    fleet's own homes.
    """
    simulated_fleets: list[FleetConfig] = []

    def simulate(fleet_config, start, end):
        simulated_fleets.append(fleet_config)
        return make_fleet_results(homes=fleet_config.homes)

    result = invoke_cli([*_ONE_BOARD_CONFIG, *options], answering(simulate))
    return result, simulated_fleets


@pytest.mark.parametrize("grid_services_kw", ["0", "20"])
def test_grid_services_kw_under_the_events_model_is_refused_before_any_simulation(
    grid_services_kw: str,
) -> None:
    """C7: --grid-services-kw, whatever its value, sets a flat rate the events model does not read, so it is refused, naming the flag and the model."""
    result, simulated_fleets = _invoke_configs_on_the_board(["--grid-services-kw", grid_services_kw])

    stderr = " ".join(result.stderr.split())
    assert result.exit_code == 1, result.output
    assert "Configuration error:" in stderr
    assert "--grid-services-kw" in stderr
    assert "capacity_at_events" in stderr
    assert simulated_fleets == []


@pytest.mark.parametrize("sensitivity", ["grid_services", "retained_floor,grid_services"])
def test_an_explicit_grid_services_axis_under_the_events_model_is_refused_before_any_simulation(
    sensitivity: str,
) -> None:
    """C8: a grid_services axis sweeps a flat rate the events model does not read, so asking for it is refused before the sweep simulates, naming the flag and the model."""
    result, simulated_fleets = _invoke_configs_on_the_board(["--sensitivity", sensitivity])

    stderr = " ".join(result.stderr.split())
    assert result.exit_code == 1, result.output
    assert "Configuration error:" in stderr
    assert "--sensitivity" in stderr
    assert "capacity_at_events" in stderr
    assert simulated_fleets == []


def test_without_sensitivity_under_the_events_model_a_status_line_names_grid_services_as_left_out() -> None:
    """The default axes leave out grid_services, whose flat rate the events model does not read, and say so on stderr before the sweep's first simulation."""
    result = invoke_cli([*_ONE_BOARD_CONFIG], answering(simulate_reaching_the_sweep))

    stderr = " ".join(result.stderr.split())
    assert isinstance(result.exception, ReachedTheSweep), result.output
    assert (
        "Sensitivity axis grid_services omitted from the default: it sweeps the flat grid-services rate, "
        "grid_services_income_per_kw_per_year_gbp, which the scenario's capacity_at_events grid_services_model "
        "does not read."
    ) in stderr
    assert "Sensitivity axis retained_floor" not in stderr


# ---------------------------------------------------------------------------
# §E — `optimize configs` reads its file as `finance run` does, refusing before any simulation
# ---------------------------------------------------------------------------


def _edited_optimize_scenario(
    tmp_path: Path, edit: Callable[[dict[str, object]], dict[str, object]]
) -> Path:
    """_write_optimize_scenario's one-home scenario, its document replaced by what *edit* makes of it."""
    path = _write_optimize_scenario(tmp_path, n_homes=1)
    path.write_text(yaml.dump(edit(yaml.safe_load(path.read_text()))))
    return path


def test_a_file_with_no_finance_block_is_refused_as_finance_run_refuses_it_before_any_simulation(
    tmp_path: Path,
) -> None:
    scenario_file = _edited_optimize_scenario(
        tmp_path, lambda document: {key: value for key, value in document.items() if key != "finance"}
    )

    finance_run = invoke_cli(["finance", "run", str(scenario_file)], answering(simulate_reaching_the_sweep))
    optimize_configs = invoke_cli(
        ["optimize", "configs", str(scenario_file)], answering(simulate_reaching_the_sweep)
    )

    for result in (finance_run, optimize_configs):
        assert result.exit_code == 1, result.output
        assert not isinstance(result.exception, ReachedTheSweep), result.output
    assert stderr_text(optimize_configs) == stderr_text(finance_run)
    assert stderr_text(optimize_configs).startswith("Configuration error:"), optimize_configs.output


def test_a_scenario_flex_band_naming_no_band_is_refused_before_any_simulation(tmp_path: Path) -> None:
    scenario_file = _edited_optimize_scenario(tmp_path, lambda document: {**document, "flex_band": 1})

    result = invoke_cli(["optimize", "configs", str(scenario_file)], answering(simulate_reaching_the_sweep))

    assert result.exit_code == 1, result.output
    assert not isinstance(result.exception, ReachedTheSweep), result.output
    assert "Configuration error: flex_band must be one of low, central, high, got 1" in stderr_text(result)


def test_a_home_document_is_refused_as_no_fleet_before_any_simulation(tmp_path: Path) -> None:
    scenario_file = _edited_optimize_scenario(
        tmp_path,
        lambda document: {
            "home": {"pv": {"capacity_kw": 4.0}, "load": {"annual_consumption_kwh": 3500}},
            "finance": document["finance"],
        },
    )

    result = invoke_cli(
        ["optimize", "configs", str(scenario_file), "--pv", "4", "--battery", "0", "--inverter", "5"],
        answering(simulate_reaching_the_sweep),
    )

    assert result.exit_code == 1, result.output
    assert not isinstance(result.exception, ReachedTheSweep), result.output
    assert "requires a fleet scenario" in stderr_text(result), result.output
