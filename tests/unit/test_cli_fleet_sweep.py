# SPDX-License-Identifier: AGPL-3.0-or-later
"""`fleet sweep`, on either sweep path, exports one CSV per point named after the swept parameter, and a summary of every point."""

from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner, Result

from solar_challenge.cli.main import app
from solar_challenge.weather import WeatherCache
from tests._seeded_tmy import ClearJuneDays

runner = CliRunner()

_DAY = "2024-06-21"

# Each way `fleet sweep` sweeps a fleet file's battery capacity: the file's capacity_kwh,
# the options that sweep it, the name of the swept parameter, and the values it takes.
_SWEEP_PATHS = (
    pytest.param(
        {
            "type": "proportional_to",
            "source": "pv.capacity_kw",
            "multiplier": {"type": "sweep", "min": 1.25, "max": 2.5, "steps": 2, "mode": "linear"},
        },
        (),
        "multiplier",
        (1.25, 2.5),
        id="yaml-sweep",
    ),
    pytest.param(
        "${CAP}",
        ("--param", "CAP", "--min", "5", "--max", "10", "--steps", "2", "--mode", "linear"),
        "CAP",
        (5.0, 10.0),
        id="param-sweep",
    ),
)

_SUMMARY_COLUMNS = [
    "sweep_value",
    "param",
    "self_consumption_ratio",
    "total_generation_kwh",
    "total_consumption_kwh",
    "grid_import_kwh",
    "grid_export_kwh",
]


@pytest.fixture(autouse=True)
def _clear_june_in_tmp_path(
    weather_cache: WeatherCache, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Serve a clear _DAY as the TMY of Bristol, where a config with no location simulates, and work in tmp_path, where each test writes its config and the sweep its output."""
    ClearJuneDays(first_day=pd.Timestamp(_DAY), count=1).seed_as_bristol_tmy(weather_cache)
    monkeypatch.chdir(tmp_path)


def _sweep(capacity_kwh: object, *options: str) -> Result:
    """Write fleet.yaml in the working directory: two homes with 4 kW of PV, a deterministic 3400 kWh a year of load and a battery of capacity_kwh. Run `fleet sweep` on it for _DAY into out, with options, simulating one home after another."""
    Path("fleet.yaml").write_text(
        yaml.safe_dump(
            {
                "fleet_distribution": {
                    "n_homes": 2,
                    "seed": 42,
                    "pv": {"capacity_kw": 4.0},
                    "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
                    "battery": {"capacity_kwh": capacity_kwh},
                }
            }
        )
    )

    return runner.invoke(
        app,
        [
            "fleet", "sweep", "fleet.yaml", "--output-dir", "out",
            "--start", _DAY, "--end", _DAY, "--sequential", *options,
        ],
        catch_exceptions=False,
    )


@pytest.mark.parametrize(("capacity_kwh", "options", "param_name", "values"), _SWEEP_PATHS)
def test_each_point_is_exported_to_a_csv_named_after_the_swept_parameter_and_its_value(
    capacity_kwh: object, options: tuple[str, ...], param_name: str, values: tuple[float, ...]
) -> None:
    result = _sweep(capacity_kwh, *options)

    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in Path("out").iterdir()) == sorted(
        [f"{param_name}_{value:.4f}.csv" for value in values] + ["sweep_summary.csv"]
    )


@pytest.mark.parametrize(("capacity_kwh", "options", "param_name", "values"), _SWEEP_PATHS)
def test_stderr_announces_the_swept_parameter_and_its_range(
    capacity_kwh: object, options: tuple[str, ...], param_name: str, values: tuple[float, ...]
) -> None:
    result = _sweep(capacity_kwh, *options)

    assert result.exit_code == 0, result.output
    announcement = f"sweep: {param_name} from {values[0]} to {values[-1]} (2 steps, linear)"
    assert announcement in " ".join(result.stderr.split())


@pytest.mark.parametrize(
    "bounds",
    [
        pytest.param(("--max", "10"), id="no-min"),
        pytest.param(("--min", "5"), id="no-max"),
    ],
)
def test_a_param_sweep_without_both_bounds_is_refused_before_it_simulates(
    bounds: tuple[str, ...],
) -> None:
    result = _sweep("${CAP}", "--param", "CAP", "--steps", "2", *bounds)

    assert result.exit_code == 1
    assert "CLI sweep requires --min and --max values" in " ".join(result.stderr.split())
    assert list(Path("out").glob("*.csv")) == []


@pytest.mark.parametrize(("capacity_kwh", "options", "param_name", "values"), _SWEEP_PATHS)
def test_the_summary_csv_has_each_points_totals_in_ascending_order(
    capacity_kwh: object, options: tuple[str, ...], param_name: str, values: tuple[float, ...]
) -> None:
    result = _sweep(capacity_kwh, *options)

    assert result.exit_code == 0, result.output
    summary = pd.read_csv(Path("out", "sweep_summary.csv"))
    assert list(summary.columns) == _SUMMARY_COLUMNS
    assert list(summary["sweep_value"]) == pytest.approx(values)
    assert list(summary["param"]) == [param_name] * len(values)
    for row in summary.itertuples():
        point = pd.read_csv(Path("out", f"{param_name}_{row.sweep_value:.4f}.csv"), index_col=0)
        energy_kwh = point.sum() / 60
        assert (
            row.self_consumption_ratio,
            row.total_generation_kwh,
            row.total_consumption_kwh,
            row.grid_import_kwh,
            row.grid_export_kwh,
        ) == pytest.approx(
            (
                energy_kwh["self_consumption_kw"] / energy_kwh["generation_kw"],
                energy_kwh["generation_kw"],
                energy_kwh["demand_kw"],
                energy_kwh["grid_import_kw"],
                energy_kwh["grid_export_kw"],
            ),
            rel=1e-9,
            abs=1e-9,
        )


@pytest.mark.parametrize(("capacity_kwh", "options", "param_name", "values"), _SWEEP_PATHS)
def test_the_summary_table_lists_every_point_in_ascending_order(
    capacity_kwh: object, options: tuple[str, ...], param_name: str, values: tuple[float, ...]
) -> None:
    result = _sweep(capacity_kwh, *options)

    body_rows = [line for line in result.stdout.splitlines() if line.startswith("│")]
    assert result.exit_code == 0, result.output
    assert [row.split("│")[1].strip() for row in body_rows] == [f"{value:.4f}" for value in values]


@pytest.mark.parametrize(("capacity_kwh", "options", "param_name", "values"), _SWEEP_PATHS)
def test_the_progress_bar_counts_every_home_of_every_point(
    capacity_kwh: object, options: tuple[str, ...], param_name: str, values: tuple[float, ...]
) -> None:
    """Two points of two homes each, so the bar ends at 4 of 4, the final frame Rich prints on stderr off a terminal."""
    result = _sweep(capacity_kwh, *options)

    assert result.exit_code == 0, result.output
    status = " ".join(result.stderr.split())
    assert "Simulating 2 sweeps (4 total homes)..." in status
    assert "4/4" in status
