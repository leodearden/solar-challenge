# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline smoke tests of the measurement scripts the docs say to re-measure with.

docs/pv-inverter-string-matching.md, docs/tmy-irradiation-scaling.md,
docs/pv-system-losses.md, docs/scheduled-charge-windows.md and
review/briefing.yaml's key_decisions say to re-measure their figures with
scripts/measure_mppt_window.py, scripts/measure_tmy_irradiation.py,
scripts/measure_pv_performance_ratio.py and scripts/measure_charge_window_bills.py.
"""

import dataclasses
import statistics
from collections.abc import Mapping
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pvlib.modelchain import ModelChain

import solar_challenge
from solar_challenge.finance import BillBreakdown
from solar_challenge.home import SummaryStatistics
from solar_challenge.location import Location
from solar_challenge.pv import (
    PVConfig,
    candidate_cec_inverters,
    create_model_chain,
    create_pv_system,
    simulate_pv_output,
    usable_cec_inverters,
    wired_dc_capacity_kw,
)
from solar_challenge.weather import CLIMATE_YEARS, IRRADIANCE_COLUMNS, WeatherCache
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._scripts import load_script
from tests._seeded_tmy import ClearJuneDays
from tests._synthetic_weather import sunless_weather, synthetic_june_weather, weather_for

_QUIET_DIODE_SOLVER = pytest.mark.filterwarnings(
    "ignore:invalid value encountered:RuntimeWarning"
)
"""Silences the RuntimeWarnings pvlib's single-diode solver raises over the dark hours of a model chain's run."""


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
    """The CSV measure_mppt_window.main writes for 4 kW dc, reading the day one_day_tmy holds from a weather cache seeded with it.

    The cache holds Bristol's TMY, so main fetches nothing. The inverter_kw
    column is read as the labels in the script's COLUMNS.
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
        in_window.run_model(one_day_tmy)
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
    utc_1990 = pd.date_range("1990-01-01", periods=8760, freq="h", tz="UTC")
    return synthetic_june_weather(
        "1990-01-01", irradiance_scale_per_day=np.linspace(0.2, 1.0, 365).tolist()
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

    @_QUIET_DIODE_SOLVER
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

    @_QUIET_DIODE_SOLVER
    def test_its_yields_are_per_wired_kwp_and_per_in_plane_irradiation(
        self, performance_site: Any, synthetic_tmy: pd.DataFrame
    ) -> None:
        chain = create_model_chain(PVConfig.default_4kw(), Location.bristol())
        chain.run_model(synthetic_tmy)
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

    @_QUIET_DIODE_SOLVER
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

    @_QUIET_DIODE_SOLVER
    def test_it_bills_the_four_arms_in_order_each_with_its_summary_and_bill(
        self, sunless_day_bills: list[Any]
    ) -> None:
        assert [arm.arm for arm in sunless_day_bills] == ["A", "B", "C", "D"]
        for arm in sunless_day_bills:
            assert isinstance(arm.summary, SummaryStatistics), arm.arm
            assert isinstance(arm.bill, BillBreakdown), arm.arm

    @_QUIET_DIODE_SOLVER
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

    @_QUIET_DIODE_SOLVER
    def test_every_arm_but_c_charges_from_the_grid(self, sunless_day_bills: list[Any]) -> None:
        grid_charge_kwh = {arm.arm: arm.summary.total_grid_charge_kwh for arm in sunless_day_bills}

        assert grid_charge_kwh["C"] == 0.0
        assert all(grid_charge_kwh[label] > 0.0 for label in "ABD"), grid_charge_kwh

    @_QUIET_DIODE_SOLVER
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
