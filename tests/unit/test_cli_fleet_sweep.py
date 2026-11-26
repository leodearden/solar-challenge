# SPDX-License-Identifier: AGPL-3.0-or-later
"""`fleet sweep`, on every sweep path (knob, variable and YAML), exports one CSV per point named after the swept parameter and a summary of every point, and creates no output directory when it refuses its period; on the --param path, each point simulates where its substituted location: block puts it, and a knob sweep reads each placeholder of its document at its default, refusing one without a default; a knob that edits no home is refused, and the help lists the knobs it sweeps."""

from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner, Result

from solar_challenge.cli.main import app
from solar_challenge.fleet_distribution import SweepSpec
from solar_challenge.location import Location
from solar_challenge.weather import WeatherCache
from tests._cli_table_text import table_text
from tests._fleet_sweep_paths import SWEEP_PATHS, SweepPath, two_home_fleet_distribution
from tests._seeded_tmy import ClearJuneDays
from tests._synthetic_weather import sunless_weather

runner = CliRunner()

_DAY = "2024-06-21"

_SUMMARY_COLUMNS = [
    "sweep_value",
    "param",
    "self_consumption_ratio",
    "total_generation_kwh",
    "total_consumption_kwh",
    "grid_import_kwh",
    "grid_export_kwh",
]

_SWEPT_KNOBS = (
    "the knobs fleet sweep sweeps, each with its aliases: pv_capacity_kw, inverter_capacity_kw, "
    "battery_capacity_kwh, annual_consumption_kwh, degradation_rate_per_year (degradation)"
)

_JUNE_DAYS = ClearJuneDays(first_day=pd.Timestamp(_DAY), count=1)
bristol_june_tmy = _JUNE_DAYS.bristol_tmy_fixture()


@pytest.fixture(autouse=True)
def _clear_june_in_tmp_path(
    bristol_june_tmy: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Work in tmp_path, where each test writes its config and the sweep its output."""
    monkeypatch.chdir(tmp_path)


def _sweep_document(document: dict[str, object], *options: str, start: str = _DAY) -> Result:
    """Write document as fleet.yaml in the working directory. Run `fleet sweep` on it from start to _DAY into out, with options, simulating one home after another."""
    Path("fleet.yaml").write_text(yaml.safe_dump(document))

    return runner.invoke(
        app,
        [
            "--sequential", "fleet", "sweep", "fleet.yaml", "--output-dir", "out",
            "--start", start, "--end", _DAY, *options,
        ],
        catch_exceptions=False,
    )


def _sweep(capacity_kwh: object, *options: str, start: str = _DAY) -> Result:
    """Run `fleet sweep`, with options, from start to _DAY, on two homes with 4 kW of PV, a deterministic 3400 kWh a year of load and a battery of capacity_kwh."""
    return _sweep_document(
        {"fleet_distribution": two_home_fleet_distribution(battery={"capacity_kwh": capacity_kwh})},
        *options,
        start=start,
    )


@pytest.mark.parametrize("path", SWEEP_PATHS)
def test_each_point_is_exported_to_a_csv_named_after_the_swept_parameter_and_its_value(
    path: SweepPath,
) -> None:
    result = _sweep(path.capacity_kwh, *path.options)

    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in Path("out").iterdir()) == sorted(
        [f"{path.param_name}_{value:.4f}.csv" for value in path.values] + ["sweep_summary.csv"]
    )


@pytest.mark.parametrize("path", SWEEP_PATHS)
def test_stderr_announces_the_swept_parameter_and_its_range(
    path: SweepPath,
) -> None:
    result = _sweep(path.capacity_kwh, *path.options)

    assert result.exit_code == 0, result.output
    announcement = f"sweep: {path.param_name} from {path.values[0]} to {path.values[-1]} (2 steps, linear)"
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


@pytest.mark.parametrize("path", SWEEP_PATHS)
def test_flags_that_leave_no_window_are_refused_without_creating_the_output_directory(
    path: SweepPath,
) -> None:
    result = _sweep(path.capacity_kwh, *path.options, start="2024-06-22")

    assert result.exit_code == 1
    assert "Configuration error: --start 2024-06-22" in " ".join(result.stderr.split())
    assert not Path("out").exists()


@pytest.mark.parametrize("path", SWEEP_PATHS)
def test_the_summary_csv_has_each_points_totals_in_ascending_order(
    path: SweepPath,
) -> None:
    result = _sweep(path.capacity_kwh, *path.options)

    assert result.exit_code == 0, result.output
    summary = pd.read_csv(Path("out", "sweep_summary.csv"))
    assert list(summary.columns) == _SUMMARY_COLUMNS
    assert list(summary["sweep_value"]) == pytest.approx(path.values)
    assert list(summary["param"]) == [path.param_name] * len(path.values)
    for row in summary.itertuples():
        point = pd.read_csv(Path("out", f"{path.param_name}_{row.sweep_value:.4f}.csv"), index_col=0)
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


@pytest.mark.parametrize("path", SWEEP_PATHS)
def test_the_summary_table_lists_every_point_in_ascending_order(
    path: SweepPath,
) -> None:
    result = _sweep(path.capacity_kwh, *path.options)

    body_rows = [line for line in result.stdout.splitlines() if line.startswith("│")]
    assert result.exit_code == 0, result.output
    assert [row.split("│")[1].strip() for row in body_rows] == [f"{value:.4f}" for value in path.values]


@pytest.mark.parametrize("path", SWEEP_PATHS)
def test_the_progress_bar_counts_every_home_of_every_point(
    path: SweepPath,
) -> None:
    """Two points of two homes each, so the bar ends at 4 of 4, the final frame Rich prints on stderr off a terminal."""
    result = _sweep(path.capacity_kwh, *path.options)

    assert result.exit_code == 0, result.output
    status = " ".join(result.stderr.split())
    assert "Simulating 2 sweeps (4 total homes)..." in status
    assert "4/4" in status


def test_a_knob_given_by_an_alias_labels_its_points_by_the_knobs_canonical_name() -> None:
    result = _sweep(
        2.0, "--param", "degradation", "--min", "0.005", "--max", "0.01", "--steps", "2", "--mode", "linear"
    )

    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in Path("out").iterdir()) == [
        "degradation_rate_per_year_0.0050.csv",
        "degradation_rate_per_year_0.0100.csv",
        "sweep_summary.csv",
    ]
    assert list(pd.read_csv(Path("out", "sweep_summary.csv"))["param"]) == ["degradation_rate_per_year"] * 2


def test_points_that_share_a_four_decimal_label_are_each_exported_and_listed_under_a_wider_one() -> None:
    """Three degradation rates 2.5e-5 apart all read 0.0001 at four decimals, so each point is labelled at five."""
    result = _sweep(
        2.0, "--param", "degradation", "--min", "0.0001", "--max", "0.00015", "--steps", "3", "--mode", "linear"
    )

    body_rows = [line for line in result.stdout.splitlines() if line.startswith("│")]
    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in Path("out").iterdir()) == [
        "degradation_rate_per_year_0.00010.csv",
        "degradation_rate_per_year_0.00013.csv",
        "degradation_rate_per_year_0.00015.csv",
        "sweep_summary.csv",
    ]
    assert len(pd.read_csv(Path("out", "sweep_summary.csv"))) == 3
    assert [row.split("│")[1].strip() for row in body_rows] == ["0.00010", "0.00013", "0.00015"]


@pytest.mark.parametrize(
    ("name", "canonical"),
    [
        ("battery_cost", "battery_cost_per_kwh_gbp"),
        ("grant_gbp", "grant_gbp"),
        ("retained_floor", "retained_cash_floor_per_home_per_year_gbp"),
        ("self_consumption_override", "self_consumption_override"),
        ("own_use_rate_pence_per_kwh", "own_use_rate_pence_per_kwh"),
        ("seg", "seg_tariff_pence_per_kwh"),
        ("grid_services", "grid_services_income_per_kw_per_year_gbp"),
    ],
)
def test_a_knob_that_edits_no_home_is_refused_naming_it_and_the_knobs_it_sweeps(name: str, canonical: str) -> None:
    """Such a knob leaves every home's simulation as it was, so every point would simulate the same fleet."""
    result = _sweep(2.0, "--param", name, "--min", "0.1", "--max", "0.2", "--steps", "2", "--mode", "linear")

    refusal = " ".join(result.stderr.split())
    assert result.exit_code == 1
    assert f"--param '{name}' names the knob '{canonical}', which sets" in refusal
    assert f"and no home's simulation, so every point would simulate the same fleet; {_SWEPT_KNOBS}" in refusal
    assert not Path("out").exists()


def test_the_param_help_lists_only_the_knobs_it_sweeps() -> None:
    result = runner.invoke(app, ["fleet", "sweep", "--help"], catch_exceptions=False)

    text = table_text(result.stdout)
    assert result.exit_code == 0
    assert _SWEPT_KNOBS in text
    assert [
        name
        for name in (
            "seg_tariff_pence_per_kwh",
            "battery_cost_per_kwh_gbp",
            "grant_gbp",
            "retained_cash_floor_per_home_per_year_gbp",
            "grid_services_income_per_kw_per_year_gbp",
            "own_use_rate_pence_per_kwh",
            "self_consumption_override",
            "battery_cost",
            "retained_floor",
        )
        if name in text
    ] == []


def _battery_ratio_fleet(multiplier: object) -> dict[str, object]:
    """A document of the two-home fleet whose battery capacity is multiplier times its PV capacity."""
    return {
        "fleet_distribution": two_home_fleet_distribution(
            battery={"capacity_kwh": {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": multiplier}}
        )
    }


_PV_CAPACITY_SWEEP = ("--param", "pv_capacity_kw", "--min", "3", "--max", "5", "--steps", "2", "--mode", "linear")


def test_a_knob_sweep_reads_each_placeholder_of_the_document_at_its_default() -> None:
    """Each point exports the frame of the same sweep of the document holding the placeholder's default in its place."""
    literal = _sweep_document(_battery_ratio_fleet(1.0), *_PV_CAPACITY_SWEEP)
    Path("out").rename("literal")

    result = _sweep_document(_battery_ratio_fleet("${BATTERY_RATIO:1.0}"), *_PV_CAPACITY_SWEEP)

    assert literal.exit_code == 0, literal.output
    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in Path("out").iterdir()) == [
        "pv_capacity_kw_3.0000.csv",
        "pv_capacity_kw_5.0000.csv",
        "sweep_summary.csv",
    ]
    for point in ("pv_capacity_kw_3.0000.csv", "pv_capacity_kw_5.0000.csv"):
        pd.testing.assert_frame_equal(
            pd.read_csv(Path("out", point)), pd.read_csv(Path("literal", point)), check_exact=True
        )


def test_a_knob_sweep_of_a_document_holding_a_placeholder_without_a_default_is_refused_naming_its_path() -> None:
    result = _sweep_document(_battery_ratio_fleet("${BATTERY_RATIO}"), *_PV_CAPACITY_SWEEP)

    assert result.exit_code == 1
    assert (
        "fleet_distribution.battery.capacity_kwh.multiplier: variable 'BATTERY_RATIO' is not supplied and has no default"
        in " ".join(result.stderr.split())
    )
    assert not Path("out").exists()


def test_a_sweep_given_no_mode_spaces_its_points_as_sweepspecs_default_mode_does() -> None:
    result = _sweep(2.0, "--param", "battery_capacity_kwh", "--min", "5", "--max", "20", "--steps", "3")

    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in Path("out").iterdir()) == sorted(
        [f"battery_capacity_kwh_{value:.4f}.csv" for value in SweepSpec(min=5.0, max=20.0, steps=3).get_values()]
        + ["sweep_summary.csv"]
    )


def test_a_mode_no_sweep_mode_names_is_refused_by_the_option_naming_both_modes() -> None:
    result = _sweep("${CAP}", "--param", "CAP", "--min", "5", "--max", "10", "--steps", "2", "--mode", "log")

    text = table_text(result.stderr)
    assert result.exit_code == 2
    assert "Invalid value for '--mode':" in text
    assert "'log' is not one of 'linear', 'geometric'." in text
    assert not Path("out").exists()


def test_a_param_sweep_of_a_placeholder_in_the_location_block_simulates_each_point_at_its_latitude(
    weather_cache: WeatherCache,
) -> None:
    """Latitude 50 is served the clear _DAY and latitude 52 a sunless one, so a point generates only if its homes simulate at the latitude its sweep value gives."""
    weather_cache.put(
        _JUNE_DAYS.hourly_weather(),
        "tmy",
        Location(latitude=50.0, longitude=Location.BRISTOL_LON),
    )
    weather_cache.put(
        sunless_weather(_DAY, temp_air=15.0),
        "tmy",
        Location(latitude=52.0, longitude=Location.BRISTOL_LON),
    )

    result = _sweep_document(
        {
            "location": {"latitude": "${LAT:51.45}", "longitude": Location.BRISTOL_LON},
            "fleet_distribution": two_home_fleet_distribution(),
        },
        "--param", "LAT", "--min", "50", "--max", "52", "--steps", "2", "--mode", "linear",
    )

    assert result.exit_code == 0, result.output
    generation_kwh = pd.read_csv(Path("out", "sweep_summary.csv")).set_index("sweep_value")["total_generation_kwh"]
    assert generation_kwh.loc[50.0] > 0
    assert generation_kwh.loc[52.0] == 0
