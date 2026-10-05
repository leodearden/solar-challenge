# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline smoke tests of the measurement scripts the docs say to re-measure with.

docs/pv-inverter-string-matching.md, docs/tmy-irradiation-scaling.md and
review/briefing.yaml's key_decisions say to re-measure their figures with
scripts/measure_mppt_window.py and scripts/measure_tmy_irradiation.py. scripts/ is
not a package, so each script is loaded from its file.
"""

import importlib.util
import statistics
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pytest

from solar_challenge.location import Location
from solar_challenge.pv import (
    PVConfig,
    candidate_cec_inverters,
    create_pv_system,
    simulate_pv_output,
    usable_cec_inverters,
)
from solar_challenge.weather import CLIMATE_YEARS, IRRADIANCE_COLUMNS, WeatherCache
from tests._synthetic_weather import synthetic_june_weather

_REPO_ROOT = Path(__file__).resolve().parents[2]

_QUIET_DIODE_SOLVER = pytest.mark.filterwarnings(
    "ignore:invalid value encountered:RuntimeWarning"
)
"""Silences the RuntimeWarnings pvlib's single-diode solver raises over the dark hours of a model chain's run."""


def _load_script(name: str) -> ModuleType:
    """Run scripts/<name>.py as a module called name, without registering it in sys.modules."""
    path = _REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        pytest.fail(f"{path} cannot be loaded as a module")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


@pytest.fixture(scope="module")
def mppt_window() -> ModuleType:
    """scripts/measure_mppt_window.py."""
    return _load_script("measure_mppt_window")


@pytest.fixture(scope="module")
def default_module() -> Mapping[str, Any]:
    """The default system's module parameters, the module measure_mppt_window.main measures with."""
    return create_pv_system(PVConfig.default_4kw()).arrays[0].module_parameters


@pytest.fixture(scope="module")
def one_day_tmy() -> pd.DataFrame:
    """One clear June day, 24 hourly rows, standing in for Bristol's TMY."""
    return synthetic_june_weather("1990-06-21")


@pytest.fixture(scope="module")
def census_rows(
    mppt_window: ModuleType,
    one_day_tmy: pd.DataFrame,
    tmp_path_factory: pytest.TempPathFactory,
) -> pd.DataFrame:
    """The CSV measure_mppt_window.main writes for 4 kW dc, reading one_day_tmy from a weather cache seeded with it.

    The cache holds Bristol's TMY, so main fetches nothing. The inverter_kw
    column is read as the labels in the script's COLUMNS.
    """
    cache_dir = tmp_path_factory.mktemp("weather-cache")
    WeatherCache(cache_dir).put(one_day_tmy, "tmy", Location.bristol())
    csv_path = tmp_path_factory.mktemp("census") / "mppt-window.csv"
    mppt_window.main(["--cache-dir", str(cache_dir), "--csv", str(csv_path), "--dc-kw", "4"])
    return pd.read_csv(csv_path, dtype={"inverter_kw": str})


class TestMeasureMpptWindow:
    """measure_mppt_window measures pv.py's own pick and model chain under each sizing (docs/pv-inverter-string-matching.md §3)."""

    @_QUIET_DIODE_SOLVER
    def test_main_measures_each_sizing_at_each_inverter_capacity_offline(
        self,
        mppt_window: ModuleType,
        default_module: Mapping[str, Any],
        census_rows: pd.DataFrame,
    ) -> None:
        sizing_and_column = sorted(
            (sizing.label, column)
            for sizing in mppt_window.sizings(default_module)
            for column in mppt_window.COLUMNS
        )

        assert sorted(zip(census_rows["sizing"], census_rows["inverter_kw"])) == sizing_and_column
        assert set(census_rows["dc_kw"]) == {4.0}

    @_QUIET_DIODE_SOLVER
    def test_the_stc_sizings_annual_ac_is_the_pv_models(
        self,
        mppt_window: ModuleType,
        one_day_tmy: pd.DataFrame,
        census_rows: pd.DataFrame,
    ) -> None:
        inverter_kw_by_column = dict(zip(mppt_window.COLUMNS, mppt_window.INVERTER_CAPACITIES_KW))
        stc_rows = census_rows[census_rows["sizing"] == mppt_window.STC.label]
        assert len(stc_rows) == len(mppt_window.COLUMNS)

        for row in stc_rows.itertuples():
            config = PVConfig(
                capacity_kw=row.dc_kw, inverter_capacity_kw=inverter_kw_by_column[row.inverter_kw]
            )
            model_kwh = simulate_pv_output(config, Location.bristol(), one_day_tmy).sum()
            assert row.ac_kwh == pytest.approx(model_kwh, rel=1e-9), (
                f"STC sizing, {row.dc_kw} kW dc in the {row.inverter_kw!r} inverter column"
            )

    @_QUIET_DIODE_SOLVER
    def test_each_sizing_keeps_its_strings_ceiling_headroom_under_mppt_high(
        self,
        mppt_window: ModuleType,
        default_module: Mapping[str, Any],
        census_rows: pd.DataFrame,
    ) -> None:
        ceiling_factor = {
            sizing.label: sizing.ceiling_factor for sizing in mppt_window.sizings(default_module)
        }

        for row in census_rows.itertuples():
            factor = ceiling_factor[row.sizing]
            assert row.longest_string_stc_v * factor <= row.mppt_high_v * (1 + 1e-9), (
                f"sizing {row.sizing!r}, {row.dc_kw} kW dc in the {row.inverter_kw!r} inverter "
                f"column, wired {row.wiring} to {row.inverter}: its longest string's "
                f"{row.longest_string_stc_v:.1f} V at STC times {factor:.4f} is above the "
                f"inverter's Mppt_high of {row.mppt_high_v:.1f} V"
            )

    def test_the_stc_sizing_picks_from_pvs_own_candidates(self, mppt_window: ModuleType) -> None:
        assert mppt_window.STC.candidates() == candidate_cec_inverters()

    def test_keeping_battery_inverter_chargers_picks_from_every_usable_inverter(
        self, mppt_window: ModuleType
    ) -> None:
        assert mppt_window.BATTERY_INVERTERS_KEPT.candidates() == usable_cec_inverters()

    def test_a_sizing_divides_each_window_edge_by_its_factor(self, mppt_window: ModuleType) -> None:
        sizing = mppt_window.Sizing("test", ceiling_factor=1.25, floor_factor=0.8)

        assert [
            (moved.name, moved.paco_w, moved.vdco_v, moved.mppt_low_v, moved.mppt_high_v)
            for moved in sizing.candidates()
        ] == [
            (
                candidate.name,
                candidate.paco_w,
                candidate.vdco_v,
                candidate.mppt_low_v / 0.8,
                candidate.mppt_high_v / 1.25,
            )
            for candidate in candidate_cec_inverters()
        ]


@pytest.fixture(scope="module")
def tmy_irradiation() -> ModuleType:
    """scripts/measure_tmy_irradiation.py."""
    return _load_script("measure_tmy_irradiation")


@pytest.fixture(scope="module")
def synthetic_tmy() -> pd.DataFrame:
    """A TMY shaped like PVGIS's as pvlib returns it: 1990's 8760 hours, indexed in UTC.

    Each day is the clear June day, its irradiance ramped from 0.2 on 1 January
    to 1.0 on 31 December.
    """
    utc_1990 = pd.date_range("1990-01-01", periods=8760, freq="h", tz="UTC")
    return synthetic_june_weather(
        "1990-01-01", irradiance_scale_per_day=np.linspace(0.2, 1.0, 365)
    ).set_axis(utc_1990)


@pytest.fixture(scope="module")
def year_factors() -> dict[int, float]:
    """Each climate year's irradiance over the synthetic TMY's, rising with the year, so the first year is the darkest."""
    return {year: 0.9 + 0.01 * (year - CLIMATE_YEARS[0]) for year in CLIMATE_YEARS}


@pytest.fixture(scope="module")
def real_years(synthetic_tmy: pd.DataFrame, year_factors: dict[int, float]) -> pd.DataFrame:
    """The climate years' hourly weather: for each year, the synthetic TMY's hours re-dated to that year, its ghi, dni and dhi times the year's factor.

    Every month of a real year is then the TMY's month scaled exactly.
    """
    tmy_year = synthetic_tmy.index[0].year
    return pd.concat(
        synthetic_tmy.assign(
            **{column: synthetic_tmy[column] * factor for column in IRRADIANCE_COLUMNS}
        ).set_axis(synthetic_tmy.index + pd.DateOffset(years=year - tmy_year))
        for year, factor in year_factors.items()
    )


@pytest.fixture(scope="module")
def source_years() -> dict[int, int]:
    """The real year each month of the synthetic TMY comes from: month m from the m-th climate year."""
    return {month: CLIMATE_YEARS[month - 1] for month in range(1, 13)}


@pytest.fixture(scope="module")
def site(
    tmy_irradiation: ModuleType,
    synthetic_tmy: pd.DataFrame,
    source_years: dict[int, int],
    real_years: pd.DataFrame,
) -> Any:
    """measure_tmy_irradiation's measurement of the synthetic TMY against the synthetic real years, at Bristol."""
    return tmy_irradiation.measure(
        "Synthetic", Location.bristol(), synthetic_tmy, source_years, real_years
    )


class TestMeasureTmyIrradiation:
    """measure_tmy_irradiation measures a TMY against the real years its months come from (docs/tmy-irradiation-scaling.md §3)."""

    @_QUIET_DIODE_SOLVER
    def test_the_tmys_factor_is_the_real_years_mean_ghi_over_its_own(
        self, site: Any, year_factors: dict[int, float]
    ) -> None:
        """Every real year is the TMY scaled, so scaling by month and by year agree."""
        mean_factor = statistics.fmean(year_factors.values())

        assert site.factor == pytest.approx(mean_factor)
        assert site.peak_by_tmy["annual"] == pytest.approx(site.peak_by_tmy["raw"] * mean_factor)
        assert site.peak_by_tmy["monthly"] == pytest.approx(site.peak_by_tmy["raw"] * mean_factor)

    @_QUIET_DIODE_SOLVER
    def test_each_tmy_month_ranks_its_source_year_among_the_real_years(
        self, site: Any, year_factors: dict[int, float]
    ) -> None:
        mean_factor = statistics.fmean(year_factors.values())

        assert [month.month for month in site.months] == list(range(1, 13))
        assert [month.source_year for month in site.months] == list(CLIMATE_YEARS[:12])
        assert [month.rank for month in site.months] == list(range(1, 13))
        assert [month.vs_mean for month in site.months] == pytest.approx(
            [1 / mean_factor - 1] * 12
        )

    @_QUIET_DIODE_SOLVER
    def test_its_ac_is_the_default_systems_from_the_pv_model(
        self, site: Any, synthetic_tmy: pd.DataFrame, real_years: pd.DataFrame
    ) -> None:
        first_year = CLIMATE_YEARS[0]
        first_year_weather = real_years[real_years.index.year == first_year]

        assert list(site.year_ac.index) == list(CLIMATE_YEARS)
        assert site.year_ac[first_year] == pytest.approx(
            simulate_pv_output(PVConfig.default_4kw(), Location.bristol(), first_year_weather).sum()
        )
        assert site.ac_by_tmy["raw"] == pytest.approx(
            simulate_pv_output(PVConfig.default_4kw(), Location.bristol(), synthetic_tmy).sum()
        )

    @_QUIET_DIODE_SOLVER
    def test_a_measured_site_prints(
        self, tmy_irradiation: ModuleType, site: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tmy_irradiation.print_site(site)
        site_lines = capsys.readouterr().out
        tmy_irradiation.print_summary([site])
        summary_lines = capsys.readouterr().out

        assert site.name in site_lines
        assert site.name in summary_lines
