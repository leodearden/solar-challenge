# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for task-70: --flex-band CLI flag wiring into finance run.

All tests are offline (the fleet simulator is injected through Click's context
object) and run without @pytest.mark.slow so they execute in the offline verify
loop.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NoReturn

import pytest
import yaml
from typer.testing import CliRunner

from solar_challenge.cli.main import app
from solar_challenge.fleet import FleetResults
from tests._cli_fleet_simulator import invoke_cli, invoke_finance_run
from tests._finance_builders import make_fleet_results


# ---------------------------------------------------------------------------
# §A — The patched CLI tests' scenario writer
# ---------------------------------------------------------------------------


def _write_scenario(
    tmp_path: Path,
    *,
    name: str = "Flex CLI Test",
    flex_band: object = None,
    grid_services_events: dict[str, object] | None = None,
    n_homes: int = 5,
) -> Path:
    """Write a minimal fleet scenario YAML to tmp_path.

    When flex_band is not None, the top-level ``flex_band`` key is written so
    the CLI can pick it up as the scenario-level default.  When
    grid_services_events is not None, the finance block prices grid services
    at events (``grid_services_model: capacity_at_events``) with that block.
    """
    finance: dict[str, object] = {"standing_charge_pence_per_day": 28.0}
    if grid_services_events is not None:
        finance["grid_services_model"] = "capacity_at_events"
        finance["grid_services_events"] = grid_services_events
    scenario: dict = {  # type: ignore[type-arg]
        "name": name,
        "location": {
            "latitude": 51.45,
            "longitude": -2.58,
            "timezone": "Europe/London",
        },
        "fleet_distribution": {
            "n_homes": n_homes,
            "seed": 42,
            "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
            "battery": {"capacity_kwh": 5.0},
            "load": {"annual_consumption_kwh": 3500},
        },
        "finance": finance,
    }
    if flex_band is not None:
        scenario["flex_band"] = flex_band

    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "test_scenario.yaml"
    path.write_text(yaml.dump(scenario))
    return path


# ---------------------------------------------------------------------------
# §B — Module-scoped fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def flex_fleet_results() -> FleetResults:
    """Five default homes, each self-consuming 2,000 kWh, exporting 800 and importing 1,200 a year."""
    return make_fleet_results(n_homes=5, self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0)


# ---------------------------------------------------------------------------
# §C — Help test (step-1 RED driver)
# ---------------------------------------------------------------------------


class TestFinanceFlexCLIHelp:
    """Verify the --flex-band option is advertised in the finance run help."""

    def test_help_lists_flex_band_option(self) -> None:
        """finance run --help must mention --flex-band."""
        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])

        assert result.exit_code == 0, (
            f"Expected exit 0 from --help, got {result.exit_code}.\n{result.output}"
        )
        assert "--flex-band" in result.output, (
            f"--flex-band not found in finance run --help:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# §D — Behaviour tests (step-3 RED drivers)
# ---------------------------------------------------------------------------


class TestFinanceFlexCLIBehaviour:
    """CLI-level behaviour tests for --flex-band wiring (offline, injected fleet simulator)."""

    def test_flex_band_central_renders_block(
        self, tmp_path: Path, flex_fleet_results: FleetResults
    ) -> None:
        """--flex-band central must render the Flexibility Value block with central figures.

        (a) Checks heading token, band name, and a central-specific monetary amount.
        """
        scenario_file = _write_scenario(tmp_path / "a")
        fr = flex_fleet_results

        result = invoke_finance_run(["--flex-band", "central", str(scenario_file)], fr)

        assert result.exit_code == 0, (
            f"Exit {result.exit_code}. Output:\n{result.output}"
        )
        assert "Flexibility Value" in result.output, (
            f"Expected 'Flexibility Value' heading in output:\n{result.output}"
        )
        assert "central" in result.output, (
            f"Expected 'central' band name in output:\n{result.output}"
        )
        # Central band: time_shift_gbp = 250.0
        assert "£250" in result.output or "250" in result.output, (
            f"Expected central time-shift figure in output:\n{result.output}"
        )

    def test_flex_band_cli_flag_overrides_scenario_key(
        self, tmp_path: Path, flex_fleet_results: FleetResults
    ) -> None:
        """CLI --flex-band flag must take precedence over scenario-level flex_band key.

        (b) Scenario says 'low'; CLI says 'high' → high wins.
        """
        # Scenario has flex_band: low
        scenario_file = _write_scenario(tmp_path / "b", flex_band="low")
        fr = flex_fleet_results

        result = invoke_finance_run(["--flex-band", "high", str(scenario_file)], fr)

        assert result.exit_code == 0, (
            f"Exit {result.exit_code}. Output:\n{result.output}"
        )
        # High band: time_shift_gbp = 330.0
        assert "£330" in result.output or "330" in result.output, (
            f"Expected high time-shift '£330' in output:\n{result.output}"
        )
        # Low band: time_shift_gbp = 100.0 — must NOT appear
        assert "£100" not in result.output, (
            f"Low band '£100' should NOT appear when CLI flag='high':\n{result.output}"
        )

    def test_no_flex_band_omits_block(
        self, tmp_path: Path, flex_fleet_results: FleetResults
    ) -> None:
        """Default (no --flex-band, no scenario flex_band key) must omit the flex block.

        (c) Additive default: the block is absent when neither source provides a band.
        """
        # No flex_band key in scenario, no CLI flag
        scenario_file = _write_scenario(tmp_path / "c")
        fr = flex_fleet_results

        result = invoke_finance_run([str(scenario_file)], fr)

        assert result.exit_code == 0, (
            f"Exit {result.exit_code}. Output:\n{result.output}"
        )
        assert "Flexibility Value" not in result.output, (
            f"'Flexibility Value' should NOT appear when no band is set:\n{result.output}"
        )

    def test_invalid_flex_band_exits_nonzero(
        self, tmp_path: Path, flex_fleet_results: FleetResults
    ) -> None:
        """--flex-band bogus must exit with a non-zero code.

        (d) --flex-band is typed GridServicesBand, so Typer refuses the value
        itself; CliRunner must report exit != 0.
        """
        scenario_file = _write_scenario(tmp_path / "d")

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["finance", "run", "--flex-band", "bogus", str(scenario_file)],
        )

        assert result.exit_code != 0, (
            f"Expected non-zero exit for invalid band, got {result.exit_code}.\n{result.output}"
        )

    def test_invalid_scenario_flex_band_exits_nonzero(
        self, tmp_path: Path, flex_fleet_results: FleetResults
    ) -> None:
        """A scenario-level flex_band with an unknown value must exit 1 with a configuration error.

        This validates the scenario-key rejection path (goes via GridServicesBand.parse →
        ConfigurationError → handle_errors → Exit(1)), which is distinct from the typer-enum
        rejection of an invalid CLI flag.
        """
        # Scenario has flex_band: bogus (not low/central/high)
        scenario_file = _write_scenario(tmp_path / "e_bad", flex_band="bogus")
        fr = flex_fleet_results

        result = invoke_finance_run([str(scenario_file)], fr)

        assert result.exit_code == 1, (
            f"Expected exit 1 for invalid scenario flex_band 'bogus', "
            f"got {result.exit_code}.\n{result.output}"
        )
        assert "Configuration error:" in result.output, result.output

    def test_scenario_flex_band_case_insensitive(
        self, tmp_path: Path, flex_fleet_results: FleetResults
    ) -> None:
        """Scenario-level flex_band with mixed case (e.g. 'Central') must work.

        A string key is lower-cased, then parsed through GridServicesBand,
        matching the case-insensitive --flex-band flag.
        """
        # Scenario has flex_band: Central (capital C)
        scenario_file = _write_scenario(tmp_path / "e_case", flex_band="Central")
        fr = flex_fleet_results

        result = invoke_finance_run([str(scenario_file)], fr)

        assert result.exit_code == 0, (
            f"Expected exit 0 for scenario flex_band='Central' (case-normalised), "
            f"got {result.exit_code}.\n{result.output}"
        )
        assert "Flexibility Value" in result.output, (
            f"Expected 'Flexibility Value' in output for case-normalised 'Central':\n{result.output}"
        )
        assert "central" in result.output, (
            f"Expected 'central' band name in output:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# §D2 — Every band entry point refuses in the one vocabulary's words
# (docs/prds/grid-services-pricing-model.md §9 C10)
# ---------------------------------------------------------------------------


def _whitespace_normalised(output: str) -> str:
    """*output* with every run of whitespace one space, so Rich's line wrapping cannot split a message."""
    return " ".join(output.split())


def _simulate_must_not_run(fleet_config: object, start: object, end: object) -> NoReturn:
    pytest.fail("finance run simulated a fleet before refusing its band")


class TestFinanceFlexCLIBandEntryPoints:
    """The scenario's flex_band key, an events block's band and --flex-band each refuse a non-band naming low, central, high."""

    def test_scenario_flex_band_medium_is_refused_before_any_simulation(self, tmp_path: Path) -> None:
        scenario_file = _write_scenario(tmp_path, flex_band="medium")

        result = invoke_cli(["finance", "run", str(scenario_file)], _simulate_must_not_run)

        assert result.exit_code == 1, result.output
        assert (
            "Configuration error: flex_band must be one of low, central, high, got 'medium'"
            in _whitespace_normalised(result.output)
        ), result.output

    def test_a_scenario_flex_band_that_is_not_a_string_is_refused(
        self, tmp_path: Path, flex_fleet_results: FleetResults
    ) -> None:
        scenario_file = _write_scenario(tmp_path, flex_band=5)

        result = invoke_finance_run([str(scenario_file)], flex_fleet_results)

        assert result.exit_code == 1, result.output
        assert (
            "Configuration error: flex_band must be one of low, central, high, got 5"
            in _whitespace_normalised(result.output)
        ), result.output

    def test_an_events_band_medium_is_refused(
        self, tmp_path: Path, flex_fleet_results: FleetResults
    ) -> None:
        scenario_file = _write_scenario(tmp_path, grid_services_events={"band": "medium"})

        result = invoke_finance_run([str(scenario_file)], flex_fleet_results)

        assert result.exit_code == 1, result.output
        assert (
            "Configuration error: GridServicesEventsConfig.band must be one of low, central, high, "
            "got 'medium'"
        ) in _whitespace_normalised(result.output), result.output

    def test_flex_band_flag_medium_lists_the_bands(self, tmp_path: Path) -> None:
        """Typer refuses --flex-band medium as a usage error naming it and each band, in whatever words Typer chooses."""
        scenario_file = _write_scenario(tmp_path)

        result = CliRunner().invoke(
            app,
            ["finance", "run", "--flex-band", "medium", str(scenario_file)],
            env={"COLUMNS": "200"},
        )

        assert result.exit_code == 2, result.output
        words = set(re.findall(r"\w+", result.output))
        assert {"medium", "low", "central", "high"} <= words, result.output

    def test_flex_band_flag_high_labels_the_block_with_the_bands_value(
        self, tmp_path: Path, flex_fleet_results: FleetResults
    ) -> None:
        """The block names the band by its value, never its repr, and quotes the rate table's high flat rate."""
        scenario_file = _write_scenario(tmp_path)

        result = invoke_finance_run(["--flex-band", "high", str(scenario_file)], flex_fleet_results)

        assert result.exit_code == 0, result.output
        assert "Band: **high**" in result.output, result.output
        assert "£48.0/kW-discharge/yr" in result.output, result.output


# ---------------------------------------------------------------------------
# §E — Named user-observable signal test (step-5 RED driver)
# ---------------------------------------------------------------------------


class TestFinanceFlexNamedScenario:
    """finance run scenarios/bristol-phase1-flex.yaml renders the central flex block.

    This is the named user-observable signal: the board scenario must show the
    Flexibility Value section by default (no --flex-band flag needed) once
    scenarios/bristol-phase1-flex.yaml carries a flex_band: central key.
    """

    def test_bristol_flex_scenario_renders_central_block(
        self, tmp_path: Path, flex_fleet_results: FleetResults
    ) -> None:
        """finance run scenarios/bristol-phase1-flex.yaml → Flexibility Value block with 'central'."""
        scenario_path = Path("scenarios/bristol-phase1-flex.yaml")

        result = invoke_finance_run([str(scenario_path)], flex_fleet_results)

        assert result.exit_code == 0, (
            f"Exit {result.exit_code}. Output:\n{result.output}"
        )
        assert "Flexibility Value" in result.output, (
            f"Expected 'Flexibility Value' heading in output (scenario default):\n{result.output}"
        )
        assert "central" in result.output, (
            f"Expected 'central' band name in output (scenario default):\n{result.output}"
        )
