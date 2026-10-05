# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline smoke tests of the measurement scripts the docs say to re-measure with.

docs/pv-inverter-string-matching.md, docs/tmy-irradiation-scaling.md and
review/briefing.yaml's key_decisions say to re-measure their figures with
scripts/measure_mppt_window.py and scripts/measure_tmy_irradiation.py. scripts/ is
not a package, so each script is loaded from its file.
"""

import importlib.util
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

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
from solar_challenge.weather import WeatherCache
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
