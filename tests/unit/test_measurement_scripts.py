# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline smoke tests of the measurement scripts the docs say to re-measure with.

docs/pv-inverter-string-matching.md, docs/tmy-irradiation-scaling.md,
docs/pv-system-losses.md, docs/scheduled-charge-windows.md,
docs/grid-charge-forecast.md, docs/battery-sizing-with-events.md and
review/briefing.yaml's key_decisions say to re-measure their figures with
scripts/measure_mppt_window.py, scripts/measure_tmy_irradiation.py,
scripts/measure_pv_performance_ratio.py, scripts/measure_charge_window_bills.py,
scripts/measure_grid_charge_forecast.py and scripts/measure_battery_sizing.py.
"""

import dataclasses
import re
import statistics
import warnings
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from pvlib.modelchain import ModelChain

import solar_challenge
from solar_challenge.config import ScenarioConfig, load_config, load_fleet_config, load_scenario
from solar_challenge.dispatch import GRID_CHARGE_FORECASTS
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import BillBreakdown, bill_distribution
from solar_challenge.fleet import FleetConfig, FleetResults, FleetRunner
from solar_challenge.home import SummaryStatistics, simulate_home
from solar_challenge.location import Location
from solar_challenge.pv import (
    PVConfig,
    candidate_cec_inverters,
    create_model_chain,
    create_pv_system,
    run_model_chain,
    simulate_pv_output,
    usable_cec_inverters,
    wired_dc_capacity_kw,
)
from solar_challenge.scenario_blocks import parse_finance_config, parse_seg_rate
from solar_challenge.seg import SEGTariff
from solar_challenge.weather import (
    CACHE_DIR_VARIABLE,
    CLIMATE_YEARS,
    DEFAULT_CACHE_DIR,
    IRRADIANCE_COLUMNS,
    PvgisTmy,
    WeatherCache,
)
from tests import _synthetic_weather
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._committed_weather_cache import COMMITTED_WEATHER_CACHE_DIR
from tests._markdown_tables import table_rows
from tests._repository_paths import SCENARIOS_DIR
from tests._scripts import load_script
from tests._seeded_tmy import ClearJuneDays
from tests._synthetic_weather import sunless_weather, synthetic_june_weather, weather_for

@pytest.fixture(scope="module")
def mppt_window() -> ModuleType:
    """scripts/measure_mppt_window.py."""
    return load_script("measure_mppt_window")


@pytest.fixture(scope="module")
def default_module() -> Mapping[str, Any]:
    """The default system's module parameters, the module measure_mppt_window.main measures with."""
    return dict(create_pv_system(PVConfig.default_4kw()).arrays[0].module_parameters)


_JUNE_DAYS = ClearJuneDays(first_day=pd.Timestamp("1990-06-21"), count=1)


@pytest.fixture(scope="module")
def one_day_tmy() -> pd.DataFrame:
    """One clear June day, 24 hourly rows, standing in for Bristol's TMY."""
    return _JUNE_DAYS.hourly_weather()


@pytest.fixture(scope="module")
def census_rows(
    mppt_window: ModuleType,
    tmp_path_factory: pytest.TempPathFactory,
) -> pd.DataFrame:
    """The CSV measure_mppt_window.main writes for 4 kW dc, reading _JUNE_DAYS from a weather cache.

    The cache holds them as Bristol's TMY, so main fetches nothing. The
    inverter_kw column is read as the labels in the script's COLUMNS.
    """
    cache_dir = tmp_path_factory.mktemp("weather-cache")
    _JUNE_DAYS.seed_as_bristol_tmy(WeatherCache(cache_dir))
    csv_path = tmp_path_factory.mktemp("census") / "mppt-window.csv"
    mppt_window.main(["--cache-dir", str(cache_dir), "--csv", str(csv_path), "--dc-kw", "4"])
    return pd.read_csv(csv_path, dtype={"inverter_kw": str})


def _default_array_on(inverter: dict[str, float]) -> ModelChain:
    """The default 4 kW array on custom inverter parameters, which wire all its modules as one string on one MPPT input."""
    config = dataclasses.replace(PVConfig.default_4kw(), custom_inverter_params=inverter)
    return create_model_chain(config, Location.bristol())


class TestMeasureMpptWindow:
    """measure_mppt_window measures pv.py's own pick and model chain under each sizing (docs/pv-inverter-string-matching.md §3)."""

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

    def test_main_without_cache_dir_reads_the_tmy_from_the_cache_the_variable_names(
        self,
        mppt_window: ModuleType,
        one_day_tmy: pd.DataFrame,
        census_rows: pd.DataFrame,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Its CSV is census_rows', which main wrote reading one_day_tmy through --cache-dir."""
        WeatherCache(tmp_path / "weather").put(one_day_tmy, "tmy", Location.bristol())
        working = tmp_path / "working"
        working.mkdir()
        monkeypatch.chdir(working)
        monkeypatch.setenv(CACHE_DIR_VARIABLE, str(tmp_path / "weather"))
        csv_path = tmp_path / "mppt-window.csv"

        mppt_window.main(["--csv", str(csv_path), "--dc-kw", "4"])

        pd.testing.assert_frame_equal(
            pd.read_csv(csv_path, dtype={"inverter_kw": str}), census_rows, check_exact=True
        )
        assert not (working / DEFAULT_CACHE_DIR).exists()

    @pytest.mark.filterwarnings("error::RuntimeWarning")
    def test_measure_year_runs_with_no_runtime_warning_though_main_has_not_run(
        self, mppt_window: ModuleType, one_day_tmy: pd.DataFrame
    ) -> None:
        config = PVConfig.default_4kw()

        year = mppt_window.measure_year(create_model_chain(config, Location.bristol()), one_day_tmy)

        assert year.ac_kwh == pytest.approx(
            simulate_pv_output(config, Location.bristol(), one_day_tmy).sum(), rel=1e-9
        )

    def test_main_leaves_the_process_warning_filters_as_it_found_them(
        self, mppt_window: ModuleType, tmp_path: Path
    ) -> None:
        """A first run inside catch_warnings makes every import main makes, so no first import adds a filter of its own to the run measured."""
        cache_dir = tmp_path / "weather-cache"
        _JUNE_DAYS.seed_as_bristol_tmy(WeatherCache(cache_dir))
        argv = ["--cache-dir", str(cache_dir), "--dc-kw", "4"]
        with warnings.catch_warnings():
            mppt_window.main(argv)
        before = list(warnings.filters)

        mppt_window.main(argv)

        assert warnings.filters == before

    def test_strings_held_at_either_edge_keep_at_most_their_maximum_power_less_the_same_losses(
        self, mppt_window: ModuleType, one_day_tmy: pd.DataFrame
    ) -> None:
        """Each edge sits 0.1% inside the day's string V_mp, where the IV curve's power is flat, so a string held at it keeps all but about 1e-5 of its p_mp, and never more.

        (a) feeds the inverter the same edge voltage at p_mp itself, and
        sandia_multi's AC from one MPPT input rises with its DC power, so (b)'s
        held AC is at most (a)'s clipped AC. It comes within 1e-5 of the clipped AC
        only if the held power carries the system losses that p_mp carries.
        """
        inverter = create_pv_system(PVConfig.default_4kw()).inverter_parameters
        in_window = _default_array_on(inverter)
        run_model_chain(in_window, one_day_tmy)
        v_mp = in_window.results.dc["v_mp"]
        producing_v_mp = v_mp[v_mp > 0]
        narrowed = {
            **inverter,
            "Mppt_low": 1.001 * producing_v_mp.min(),
            "Mppt_high": 0.999 * producing_v_mp.max(),
        }

        year = mppt_window.measure_year(_default_array_on(narrowed), one_day_tmy)

        for edge, held in (("ceiling", year.above_ceiling), ("floor", year.below_floor)):
            assert held.hours > 0, edge
            assert held.ac_kwh_held <= held.ac_kwh_clipped, edge
            assert held.ac_kwh_held == pytest.approx(held.ac_kwh_clipped, rel=1e-5), edge

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
    return load_script("measure_tmy_irradiation")


@pytest.fixture(scope="module")
def synthetic_tmy() -> pd.DataFrame:
    """A TMY shaped like PVGIS's as pvlib returns it: 1990's 8760 hours, indexed in UTC.

    Each day is the clear June day, its irradiance ramped from 0.2 on 1 January
    to 1.0 on 31 December.
    """
    return _synthetic_weather.synthetic_tmy(
        irradiance_scale_per_day=np.linspace(0.2, 1.0, _synthetic_weather.TMY_DAYS).tolist()
    )


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

    def test_the_tmys_factor_is_the_real_years_mean_ghi_over_its_own(
        self, site: Any, year_factors: dict[int, float]
    ) -> None:
        """Every real year is the TMY scaled, so scaling by month and by year agree."""
        mean_factor = statistics.fmean(year_factors.values())

        assert site.factor == pytest.approx(mean_factor)
        assert site.peak_by_tmy["annual"] == pytest.approx(site.peak_by_tmy["raw"] * mean_factor)
        assert site.peak_by_tmy["monthly"] == pytest.approx(site.peak_by_tmy["raw"] * mean_factor)

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

    def test_a_measured_site_prints_its_name_and_factor(
        self, tmy_irradiation: ModuleType, site: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Each prints the site's factor: print_site to five places, print_summary to the three of docs/tmy-irradiation-scaling.md §4's k column."""
        tmy_irradiation.print_site(site)
        site_lines = capsys.readouterr().out
        tmy_irradiation.print_summary([site])
        summary_lines = capsys.readouterr().out

        assert site.name in site_lines
        assert f"factor k {site.factor:.5f}" in site_lines
        assert site.name in summary_lines
        assert f"| {site.factor:.3f} |" in summary_lines


@pytest.fixture(scope="module")
def pv_performance_ratio() -> ModuleType:
    """scripts/measure_pv_performance_ratio.py."""
    return load_script("measure_pv_performance_ratio")


@pytest.fixture(scope="module")
def performance_site(pv_performance_ratio: ModuleType, synthetic_tmy: pd.DataFrame) -> Any:
    """measure_pv_performance_ratio's measurement of the default system over the synthetic TMY, at Bristol."""
    return pv_performance_ratio.measure("Synthetic", Location.bristol(), synthetic_tmy)


class TestMeasurePvPerformanceRatio:
    """measure_pv_performance_ratio measures the default system's yield and performance ratio with and without its system losses (docs/pv-system-losses.md §1)."""

    def test_its_ac_is_the_pv_models_with_and_without_the_system_losses(
        self, performance_site: Any, synthetic_tmy: pd.DataFrame
    ) -> None:
        default = PVConfig.default_4kw()
        lossless = dataclasses.replace(default, system_losses=0.0)

        assert performance_site.with_losses.ac_kwh == pytest.approx(
            simulate_pv_output(default, Location.bristol(), synthetic_tmy).sum()
        )
        assert performance_site.lossless.ac_kwh == pytest.approx(
            simulate_pv_output(lossless, Location.bristol(), synthetic_tmy).sum()
        )

    def test_its_yields_are_per_wired_kwp_and_per_in_plane_irradiation(
        self, performance_site: Any, synthetic_tmy: pd.DataFrame
    ) -> None:
        chain = run_model_chain(
            create_model_chain(PVConfig.default_4kw(), Location.bristol()), synthetic_tmy
        )
        in_plane = chain.results.total_irrad
        first_array = in_plane[0] if isinstance(in_plane, tuple) else in_plane

        assert performance_site.wired_kwp == pytest.approx(wired_dc_capacity_kw(PVConfig.default_4kw()))
        assert performance_site.ghi_kwh_per_m2 == pytest.approx(synthetic_tmy["ghi"].sum() / 1000)
        assert performance_site.poa_kwh_per_m2 == pytest.approx(
            first_array["poa_global"].sum() / 1000
        )
        for year in (performance_site.lossless, performance_site.with_losses):
            assert year.kwh_per_kwp == pytest.approx(year.ac_kwh / performance_site.wired_kwp)
            assert year.performance_ratio == pytest.approx(
                year.kwh_per_kwp / performance_site.poa_kwh_per_m2
            )

    def test_a_measured_site_prints_its_name_and_performance_ratios(
        self,
        pv_performance_ratio: ModuleType,
        performance_site: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        estimate = pv_performance_ratio.PvgisEstimate(kwh_per_kwp=1000.0, poa_kwh_per_m2=1250.0)

        pv_performance_ratio.print_table([(performance_site, estimate)])
        table = capsys.readouterr().out

        assert performance_site.name in table
        assert f"{performance_site.with_losses.performance_ratio:.3f}" in table
        assert f"{performance_site.lossless.performance_ratio:.3f}" in table
        assert "0.800" in table


@pytest.fixture(scope="module")
def charge_window_bills() -> ModuleType:
    """scripts/measure_charge_window_bills.py."""
    return load_script("measure_charge_window_bills")


@pytest.fixture(scope="module")
def sunless_day_bills(charge_window_bills: ModuleType) -> list[Any]:
    """measure_charge_window_bills' bills of bristol-arbitrage's home under each arm over one sunless January day."""
    home = bristol_arbitrage_home()
    day = pd.Timestamp("2024-01-15")
    weather = weather_for(home, sunless_weather("2024-01-15", temp_air=5.0))
    return list(charge_window_bills.measure(home, day, day, weather=weather))


class TestMeasureChargeWindowBills:
    """measure_charge_window_bills bills bristol-arbitrage's home under each of its four arms (scripts/measure_charge_window_bills.py, docs/scheduled-charge-windows.md)."""

    def test_it_bills_the_four_arms_in_order_each_with_its_summary_and_bill(
        self, sunless_day_bills: list[Any]
    ) -> None:
        assert [arm.arm for arm in sunless_day_bills] == ["A", "B", "C", "D"]
        for arm in sunless_day_bills:
            assert isinstance(arm.summary, SummaryStatistics), arm.arm
            assert isinstance(arm.bill, BillBreakdown), arm.arm

    def test_each_bill_is_its_runs_import_cost_basis_c_own_use_and_standing_charge(
        self, charge_window_bills: ModuleType, sunless_day_bills: list[Any]
    ) -> None:
        """Basis-C own-use is demand less import (docs/cost-recovery-finance-model.md)."""
        finance = charge_window_bills.FINANCE

        for arm in sunless_day_bills:
            summary, bill = arm.summary, arm.bill
            assert bill.import_cost_gbp == summary.total_import_cost_gbp, arm.arm
            assert bill.own_use_payment_gbp == pytest.approx(
                finance.own_use_rate_pence_per_kwh * (summary.total_demand_kwh - summary.total_grid_import_kwh) / 100
            ), arm.arm
            assert bill.standing_charge_gbp == pytest.approx(
                finance.standing_charge_pence_per_day * summary.simulation_days / 100
            ), arm.arm

    def test_every_arm_but_c_charges_from_the_grid(self, sunless_day_bills: list[Any]) -> None:
        grid_charge_kwh = {arm.arm: arm.summary.total_grid_charge_kwh for arm in sunless_day_bills}

        assert grid_charge_kwh["C"] == 0.0
        assert all(grid_charge_kwh[label] > 0.0 for label in "ABD"), grid_charge_kwh

    def test_main_prints_each_arms_bill_and_what_it_was_measured_on_offline(
        self,
        charge_window_bills: ModuleType,
        tmp_path_factory: pytest.TempPathFactory,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The cache holds one clear June day as Bristol's TMY, so main fetches nothing."""
        home = bristol_arbitrage_home()
        cache_dir = tmp_path_factory.mktemp("weather-cache")
        _JUNE_DAYS.seed_as_bristol_tmy(WeatherCache(cache_dir))

        charge_window_bills.main(["--cache-dir", str(cache_dir), "--start", "2024-06-21", "--end", "2024-06-21"])
        report = capsys.readouterr().out

        assert solar_challenge.__version__ in report
        assert home.tariff_config is not None
        for period in home.tariff_config.periods:
            assert f"{period.name} {period.start_time}-{period.end_time}" in report
        for window in charge_window_bills.WINDOWS:
            assert f"from {window.start:%H:%M}" in report
        assert "from 00:30" in report
        rows = report.splitlines()
        for label in "ABCD":
            assert sum(row.startswith(f"| {label} |") for row in rows) == 1, label

    def test_main_without_cache_dir_reads_the_tmy_from_the_cache_the_variable_names(
        self,
        charge_window_bills: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The test runs offline, so main returns only if it read the TMY there: a miss is refused at PVGIS."""
        home = bristol_arbitrage_home()
        WeatherCache(tmp_path / "weather").put(synthetic_june_weather("1990-06-21"), "tmy", home.location)
        working = tmp_path / "working"
        working.mkdir()
        monkeypatch.chdir(working)
        monkeypatch.setenv(CACHE_DIR_VARIABLE, str(tmp_path / "weather"))

        charge_window_bills.main(["--start", "2024-06-21", "--end", "2024-06-21"])

        assert f"read from the cache in {tmp_path / 'weather'}" in capsys.readouterr().out
        assert not (working / DEFAULT_CACHE_DIR).exists()


_FLEX_SCENARIO = SCENARIOS_DIR / "bristol-phase1-flex.yaml"

_FORECAST_FIRST_DAY = pd.Timestamp("2024-05-31")
_FORECAST_LAST_DAY = pd.Timestamp("2024-06-01")
"""The last day of spring and the first of summer, so the figures have a MAM and a JJA column; both lie in the trailing forecast's 14-day warm-up."""

_FORECAST_HOMES = 2


@pytest.fixture(scope="module")
def grid_charge_forecast() -> ModuleType:
    """scripts/measure_grid_charge_forecast.py."""
    return load_script("measure_grid_charge_forecast")


@pytest.fixture(scope="module")
def flex_weather_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A weather cache holding a TMY of clear June days as the TMY at the board scenario's location, so the script fetches nothing."""
    location = load_fleet_config(_FLEX_SCENARIO).homes[0].location
    cache_dir = tmp_path_factory.mktemp("weather-cache")
    WeatherCache(cache_dir).put(_synthetic_weather.synthetic_tmy(), "tmy", location)
    return cache_dir


@pytest.fixture(scope="module")
def forecast_arms(grid_charge_forecast: ModuleType, flex_weather_cache: Path) -> list[Any]:
    """measure_grid_charge_forecast's arms for the board scenario's first two homes over the two days, run in turn on flex_weather_cache's TMY."""
    scenario = grid_charge_forecast.read_scenario(
        _FLEX_SCENARIO, start=_FORECAST_FIRST_DAY, end=_FORECAST_LAST_DAY, homes=_FORECAST_HOMES
    )
    weather = PvgisTmy(WeatherCache(flex_weather_cache))
    return list(grid_charge_forecast.measure(scenario, FleetRunner(weather, simulate_home, parallel=False)))


def _per_home_means(arm: Any) -> dict[str, float | None]:
    """Each figure the report gives arm, by its column: the mean over arm's homes, and None for a householder bill finance refused."""
    summaries = [home.summary for home in arm.homes]
    bill = arm.householder_bill
    return {
        "MAM net £": statistics.fmean(home.net_cost_by_season_gbp["MAM"] for home in arm.homes),
        "JJA net £": statistics.fmean(home.net_cost_by_season_gbp["JJA"] for home in arm.homes),
        "Window net £": statistics.fmean(summary.net_cost_gbp for summary in summaries),
        "Grid charge kWh": statistics.fmean(summary.total_grid_charge_kwh for summary in summaries),
        "Export kWh": statistics.fmean(summary.total_grid_export_kwh for summary in summaries),
        "Householder bill £/yr": bill if isinstance(bill, float) else None,
    }


def _cell(value: float | None, sign: str = "") -> str:
    """value as the report prints it, to two places, with a + on a positive delta when sign is '+'; 'refused' for None."""
    return "refused" if value is None else f"{value:{sign}.2f}"


def _markdown_tables(report: str) -> list[list[dict[str, str]]]:
    """Each markdown table of report, in order, as its rows, each cell keyed by its column's header."""
    tables: list[list[dict[str, str]]] = []
    block: list[list[str]] = []
    for line in [*report.splitlines(), ""]:
        if line.startswith("|"):
            block.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif block:
            header, _separator, *rows = block
            tables.append([dict(zip(header, row, strict=True)) for row in rows])
            block = []
    return tables


class TestMeasureGridChargeForecast:
    """measure_grid_charge_forecast runs the board fleet under each grid-charge forecast (scripts/measure_grid_charge_forecast.py, docs/grid-charge-forecast.md)."""

    def test_it_reads_the_homes_the_finance_cli_simulates_and_bills_for_the_scenario(
        self, grid_charge_forecast: ModuleType
    ) -> None:
        """solar-challenge finance run simulates the fleet's homes each exporting at the scenario's SEG rate, and bills them under its finance: block."""
        raw = load_config(_FLEX_SCENARIO)
        seg_rate = parse_seg_rate(raw["seg"])
        assert seg_rate is not None
        seg_tariff = SEGTariff(name="", rate_pence_per_kwh=seg_rate)

        scenario = grid_charge_forecast.read_scenario(
            _FLEX_SCENARIO, start=_FORECAST_FIRST_DAY, end=_FORECAST_LAST_DAY, homes=_FORECAST_HOMES
        )

        assert scenario.simulated_homes() == tuple(
            dataclasses.replace(home, seg_tariff=seg_tariff)
            for home in load_fleet_config(_FLEX_SCENARIO).homes[:_FORECAST_HOMES]
        )
        assert scenario.finance == parse_finance_config(raw["finance"])
        assert scenario.simulation_bounds() == (
            pd.Timestamp("2024-05-31", tz="Europe/London"),
            pd.Timestamp("2024-06-01", tz="Europe/London"),
        )

    def test_it_runs_every_home_under_each_forecast_in_order(self, forecast_arms: list[Any]) -> None:
        assert [arm.forecast for arm in forecast_arms] == list(GRID_CHARGE_FORECASTS)
        for arm in forecast_arms:
            assert [home.summary.grid_charge_forecast for home in arm.homes] == [arm.forecast] * _FORECAST_HOMES

    def test_each_homes_net_cost_in_each_season_adds_up_to_its_net_cost_over_the_window(
        self, forecast_arms: list[Any]
    ) -> None:
        """Net cost is import cost less export revenue, as calculate_summary's net_cost_gbp is."""
        for arm in forecast_arms:
            for home in arm.homes:
                assert list(home.net_cost_by_season_gbp) == ["MAM", "JJA"], arm.forecast
                assert sum(home.net_cost_by_season_gbp.values()) == pytest.approx(
                    home.summary.net_cost_gbp, rel=1e-9, abs=1e-9
                ), arm.forecast

    def test_the_householder_bill_is_bill_distributions_mean_which_finance_refuses_perfect_foresight(
        self, grid_charge_forecast: ModuleType, forecast_arms: list[Any]
    ) -> None:
        finance = parse_finance_config(load_config(_FLEX_SCENARIO)["finance"])
        assert finance is not None

        for arm in forecast_arms:
            summaries = [home.summary for home in arm.homes]
            if arm.forecast == "perfect_foresight":
                with pytest.raises(ConfigurationError, match="perfect_foresight") as refusal:
                    bill_distribution(summaries, finance)
                assert arm.householder_bill == grid_charge_forecast.Refused(str(refusal.value))
            else:
                assert arm.householder_bill == bill_distribution(
                    summaries, finance
                ).mean_gbp, arm.forecast

    def test_trailing_14_days_runs_as_pv_blind_until_it_has_14_days_of_history(
        self, forecast_arms: list[Any]
    ) -> None:
        arms = {arm.forecast: arm for arm in forecast_arms}

        for pv_blind, trailing in zip(arms["pv_blind"].homes, arms["trailing_14_days"].homes, strict=True):
            assert dataclasses.replace(trailing.summary, grid_charge_forecast="pv_blind") == pv_blind.summary
            assert trailing.net_cost_by_season_gbp == pv_blind.net_cost_by_season_gbp

    def test_perfect_foresight_grid_charges_less_than_pv_blind_on_sunny_days(self, forecast_arms: list[Any]) -> None:
        """The clear days' PV refills the battery, stranding grid charge that perfect foresight leaves out."""
        arms = {arm.forecast: arm for arm in forecast_arms}

        for pv_blind, foresight in zip(arms["pv_blind"].homes, arms["perfect_foresight"].homes, strict=True):
            assert foresight.summary.total_grid_charge_kwh < pv_blind.summary.total_grid_charge_kwh

    def test_main_prints_each_forecasts_per_home_means_and_their_deltas_and_what_they_were_measured_on_offline(
        self,
        grid_charge_forecast: ModuleType,
        flex_weather_cache: Path,
        forecast_arms: list[Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """main's runs are forecast_arms' runs, which are deterministic, so its tables are their figures."""
        grid_charge_forecast.main(
            [
                "--cache-dir", str(flex_weather_cache),
                "--start", "2024-05-31",
                "--end", "2024-06-01",
                "--homes", str(_FORECAST_HOMES),
                "--no-parallel",
            ]
        )
        report = capsys.readouterr().out

        assert solar_challenge.__version__ in report
        assert f"read from the cache in {flex_weather_cache}" in report
        assert "2024-05-31 to 2024-06-01" in report
        means, deltas = _markdown_tables(report)
        figures = {arm.forecast: _per_home_means(arm) for arm in forecast_arms}
        baseline = figures["pv_blind"]
        assert means == [
            {"Forecast": forecast, **{column: _cell(value) for column, value in figures[forecast].items()}}
            for forecast in GRID_CHARGE_FORECASTS
        ]
        assert deltas == [
            {
                "Forecast": forecast,
                **{
                    column: _cell(None if value is None or baseline[column] is None else value - baseline[column], "+")
                    for column, value in figures[forecast].items()
                },
            }
            for forecast in GRID_CHARGE_FORECASTS
        ]
        refused = {arm.forecast: arm.householder_bill for arm in forecast_arms}["perfect_foresight"]
        assert refused.reason in report


_VICTRON_SCENARIO = SCENARIOS_DIR / "bristol-phase1-victron.yaml"


@pytest.fixture(scope="module")
def battery_sizing() -> ModuleType:
    """scripts/measure_battery_sizing.py."""
    return load_script("measure_battery_sizing")


@pytest.fixture(scope="module")
def victron() -> ScenarioConfig:
    """The Victron board scenario, its 100 homes over 2024, as the script reads it by default."""
    return load_scenario(_VICTRON_SCENARIO)


def _short_life_victron(directory: Path) -> Path:
    """A copy of the Victron scenario in directory on a two-year asset life and loan term, as ε's Victron signal runs it."""
    document = yaml.safe_load(_VICTRON_SCENARIO.read_text(encoding="utf-8"))
    document["finance"]["asset_life_years"] = 2
    document["finance"]["loan_term_years"] = 2
    path = directory / "victron-short-life.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


class TestMeasureBatterySizing:
    """measure_battery_sizing prices the Victron sweep enrolled and not at each band (scripts/measure_battery_sizing.py, docs/battery-sizing-with-events.md)."""

    def test_first_homes_keeps_the_scenarios_first_n_homes_and_scales_its_grant_to_their_share(
        self, battery_sizing: ModuleType, victron: ScenarioConfig
    ) -> None:
        """The grant is the one project total in FinanceConfig, so a cut of the fleet carries its homes' share of it."""
        assert victron.finance is not None

        cut = battery_sizing.first_homes(victron, 20)

        assert cut.homes == victron.homes[:20]
        assert cut.finance is not None
        assert cut.finance.grant_gbp == victron.finance.grant_gbp * 20 / 100
        assert dataclasses.replace(cut.finance, grant_gbp=victron.finance.grant_gbp) == victron.finance
        assert cut.period == victron.period
        assert dataclasses.replace(cut, homes=victron.homes, finance=victron.finance) == victron

    def test_first_homes_of_the_whole_fleet_is_the_scenario_itself(
        self, battery_sizing: ModuleType, victron: ScenarioConfig
    ) -> None:
        assert battery_sizing.first_homes(victron, len(victron.homes)) == victron

    @pytest.mark.parametrize("count", [0, 101])
    def test_first_homes_refuses_a_count_outside_the_fleet(
        self, battery_sizing: ModuleType, victron: ScenarioConfig, count: int
    ) -> None:
        with pytest.raises(ValueError, match=rf"\b{count}\b.*\b100 homes\b"):
            battery_sizing.first_homes(victron, count)

    def test_by_default_the_script_reads_the_committed_bristol_tmy(self, battery_sizing: ModuleType) -> None:
        """The script cannot import tests/, so it names the committed cache itself; this pins the two to one directory."""
        assert battery_sizing.COMMITTED_WEATHER_CACHE_DIR == COMMITTED_WEATHER_CACHE_DIR

    def test_main_prints_one_ranked_table_per_band_and_what_it_was_measured_on_offline(
        self, battery_sizing: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """One home over two winter weekdays, on a two-year life so each projection simulates two ages; the cache holds synthetic weather at the scenario's location, so main fetches nothing."""
        scenario_path = _short_life_victron(tmp_path)
        cache_dir = tmp_path / "weather-cache"
        WeatherCache(cache_dir).put(_synthetic_weather.synthetic_tmy(), "tmy", load_scenario(scenario_path).get_location())

        battery_sizing.main(
            [
                "--scenario", str(scenario_path),
                "--cache-dir", str(cache_dir),
                "--homes", "1",
                "--start", "2024-01-15",
                "--end", "2024-01-16",
                "--no-parallel",
            ]
        )
        report = capsys.readouterr().out

        lines = report.splitlines()
        assert solar_challenge.__version__ in report
        assert sum(line.startswith("Commit: ") for line in lines) == 1
        assert any("first 1 of 100 homes" in line and "£2,500" in line for line in lines), report
        assert any("2024-01-15 to 2024-01-16" in line for line in lines), report
        reference_kwh, reference_kw = (f"{figure:g}" for figure in battery_sizing.BATTERIES[0])
        for heading in ("### Low band", "### Central band", "### High band"):
            header, *rows = table_rows(report, heading)
            assert len(rows) == 8, heading
            cells = [dict(zip(header, row, strict=True)) for row in rows]
            assert [row["Participation"] for row in cells] == ["dispatched"] * 4 + ["observed"] * 4, heading
            assert {row["Pays for itself"] for row in cells} <= {"yes", "no"}, heading
            references = [
                row for row in cells if (row["Battery kWh"], row["Battery kW"]) == (reference_kwh, reference_kw)
            ]
            assert [row["Extra capex/home £"] for row in references] == ["+£0", "+£0"], heading

    def test_main_refuses_a_homes_count_beyond_the_fleet(self, battery_sizing: ModuleType, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match=r"\b101\b.*\b100 homes\b"):
            battery_sizing.main(
                ["--scenario", str(_short_life_victron(tmp_path)), "--cache-dir", str(tmp_path), "--homes", "101"]
            )

    def test_main_refuses_a_weather_cache_without_the_tmy_at_the_scenarios_location(
        self, battery_sizing: ModuleType, tmp_path: Path
    ) -> None:
        """So it fetches nothing from PVGIS, and puts nothing into the cache it is given, by default the committed one."""
        cache_dir = tmp_path / "weather-cache"

        with pytest.raises(ConfigurationError, match=rf"{re.escape(str(cache_dir))}.*\bBristol\b"):
            battery_sizing.main(
                [
                    "--scenario", str(_short_life_victron(tmp_path)),
                    "--cache-dir", str(cache_dir),
                    "--homes", "1",
                    "--start", "2024-01-15",
                    "--end", "2024-01-16",
                    "--no-parallel",
                ]
            )
        assert not cache_dir.exists()

    @pytest.mark.parametrize("rate", ["availability_gbp_per_kw_per_event", "utilisation_gbp_per_mwh"])
    def test_measure_refuses_an_events_rate_of_the_scenarios_own_before_it_simulates(
        self, battery_sizing: ModuleType, tmp_path: Path, rate: str
    ) -> None:
        """Such a rate overrides every band's, so the low, central and high tables would print the same figures."""
        document = yaml.safe_load(_VICTRON_SCENARIO.read_text(encoding="utf-8"))
        document["finance"]["grid_services_model"][rate] = 1.5
        path = tmp_path / "victron-own-rate.yaml"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")

        def simulate(fleet: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
            raise AssertionError(f"simulated {fleet.name}")

        with pytest.raises(ConfigurationError, match=rf"\bfinance\.grid_services_model\.{rate} to 1\.5\b.*\bband"):
            battery_sizing.measure(load_scenario(path), simulate=simulate)

