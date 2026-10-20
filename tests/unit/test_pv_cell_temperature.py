# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each array's cells run at NOCT-SAM's temperature, from the array's own module.

The module's T_NOCT, and its rating over its area (A_c x 1000 W/m²) as its efficiency,
feed pvlib's noct_sam; a module lacking either key takes DEFAULT_CEC_MODULE's value.
docs/pv-cell-temperature.md records the decision and its measurements.
"""

import math
from collections.abc import Callable
from typing import TypeVar

import numpy as np
import pandas as pd
import pvlib
import pytest
from solar_challenge.location import Location
from solar_challenge.pv import (
    DEFAULT_CEC_MODULE,
    PVConfig,
    cec_module_params,
    create_model_chain,
    create_pv_system,
    create_simple_module_params,
    simulate_pv_output,
    wired_dc_capacity_kw,
)
from tests._synthetic_weather import synthetic_june_weather

_PerArray = TypeVar("_PerArray", pd.Series, pd.DataFrame)

_PVWATTS_300_W_MODULE = {"pdc0": 300.0, "gamma_pdc": -0.004}


@pytest.fixture
def clear_day() -> pd.DataFrame:
    return synthetic_june_weather("2024-06-21")


@pytest.fixture
def default_module() -> dict[str, float]:
    return cec_module_params(DEFAULT_CEC_MODULE)


def _per_array(result: _PerArray | tuple[_PerArray, ...]) -> tuple[_PerArray, ...]:
    """A run's result for each array: pvlib gives a tuple for several arrays and a bare value for one."""
    return result if isinstance(result, tuple) else (result,)


def _clear_day_kwh(config: PVConfig, clear_day: pd.DataFrame) -> float:
    return float(simulate_pv_output(config, Location.bristol(), clear_day).sum())


class TestCellTemperatureIsNoctSamFromTheModule:
    def test_the_default_chain_infers_noct_sam(self) -> None:
        chain = create_model_chain(PVConfig.default_4kw(), Location.bristol())

        assert chain.temperature_model == chain.noct_sam_temp, (
            f"the default chain runs {chain.temperature_model.__name__}"
        )

    def test_the_default_modules_arrays_carry_its_catalogue_noct_and_efficiency(self) -> None:
        """DEFAULT_CEC_MODULE's T_NOCT is 45.1 °C, and its 400.428 W at STC spread over 1.99 m² is its efficiency."""
        for array in create_pv_system(PVConfig.default_4kw()).arrays:
            assert array.temperature_model_parameters["noct"] == 45.1
            assert array.temperature_model_parameters["module_efficiency"] == pytest.approx(
                400.428 / 1990
            )

    @pytest.mark.parametrize(
        ("capacity_kw", "array_count"), [(4.0, 1), (7.6, 2)], ids=["one-array", "two-arrays"]
    )
    def test_each_arrays_cell_temperature_is_noct_sams(
        self,
        capacity_kw: float,
        array_count: int,
        clear_day: pd.DataFrame,
        default_module: dict[str, float],
    ) -> None:
        """Sunless hours compare equal: noct_sam's cell temperature is NaN in each of them."""
        chain = create_model_chain(PVConfig(capacity_kw=capacity_kw), Location.bristol())
        assert len(chain.system.arrays) == array_count

        chain.run_model(clear_day)

        for cell_temperature, total_irrad, effective_irradiance in zip(
            _per_array(chain.results.cell_temperature),
            _per_array(chain.results.total_irrad),
            _per_array(chain.results.effective_irradiance),
            strict=True,
        ):
            noct_sam = pvlib.temperature.noct_sam(
                total_irrad["poa_global"],
                clear_day["temp_air"],
                clear_day["wind_speed"],
                noct=default_module["T_NOCT"],
                module_efficiency=default_module["STC"] / (default_module["A_c"] * 1000),
                effective_irradiance=effective_irradiance,
            )
            pd.testing.assert_series_equal(cell_temperature, noct_sam, check_names=False)

    def test_the_default_4kw_clear_day_energy_is_noct_sams(self, clear_day: pd.DataFrame) -> None:
        """x1.031 the 26.0119 kWh of SAPM's generic open-rack glass/glass set (docs/pv-cell-temperature.md §3)."""
        assert _clear_day_kwh(PVConfig.default_4kw(), clear_day) == pytest.approx(26.819, rel=1e-3)

    def test_a_less_efficient_module_runs_hotter_so_yields_less(self, clear_day: pd.DataFrame) -> None:
        def kwh_at(efficiency: float) -> float:
            module = create_simple_module_params(efficiency=efficiency)
            return _clear_day_kwh(PVConfig(capacity_kw=4.0, custom_module_params=module), clear_day)

        kwh_at_10_percent, kwh_at_22_percent = kwh_at(0.10), kwh_at(0.22)

        assert kwh_at_10_percent <= 0.995 * kwh_at_22_percent, (
            f"4 kW of 10% efficient modules gave {kwh_at_10_percent:.4f} kWh, "
            f"and of 22% efficient modules {kwh_at_22_percent:.4f} kWh"
        )

    @pytest.mark.parametrize(
        "module_and_its_noct_and_efficiency",
        [
            pytest.param(
                lambda row: (_PVWATTS_300_W_MODULE, row["T_NOCT"], 300 / (row["A_c"] * 1000)),
                id="neither-key",
            ),
            pytest.param(
                lambda row: (
                    {**_PVWATTS_300_W_MODULE, "T_NOCT": 48.0},
                    48.0,
                    300 / (row["A_c"] * 1000),
                ),
                id="own-T_NOCT",
            ),
            pytest.param(
                lambda row: ({**_PVWATTS_300_W_MODULE, "A_c": 1.5}, row["T_NOCT"], 0.2),
                id="own-A_c",
            ),
            pytest.param(
                lambda row: ({**row, "T_NOCT": 50.0, "A_c": 2.2}, 50.0, row["STC"] / 2200),
                id="cec-row-with-own-T_NOCT-and-A_c",
            ),
        ],
    )
    def test_a_key_the_module_lacks_takes_the_default_modules_value(
        self,
        module_and_its_noct_and_efficiency: Callable[
            [dict[str, float]], tuple[dict[str, float], float, float]
        ],
        default_module: dict[str, float],
    ) -> None:
        """Each case gives the module, then the noct and module_efficiency its arrays get, from DEFAULT_CEC_MODULE's row."""
        module, noct, efficiency = module_and_its_noct_and_efficiency(default_module)

        for array in create_pv_system(PVConfig(capacity_kw=4.0, custom_module_params=module)).arrays:
            assert array.temperature_model_parameters["noct"] == noct
            assert array.temperature_model_parameters["module_efficiency"] == pytest.approx(
                efficiency
            )

    @pytest.mark.parametrize(
        "config",
        [
            pytest.param(PVConfig.default_4kw(), id="default-module"),
            pytest.param(
                PVConfig(capacity_kw=4.0, custom_module_params=create_simple_module_params()),
                id="create_simple_module_params",
            ),
        ],
    )
    def test_the_ac_is_finite_every_hour_and_zero_without_sun(
        self, config: PVConfig, clear_day: pd.DataFrame
    ) -> None:
        """Where noct_sam's cell temperature is NaN, pvlib fills the DC or AC with 0, so no NaN reaches an energy total."""
        ac_kw = simulate_pv_output(config, Location.bristol(), clear_day)

        assert np.isfinite(ac_kw).all(), ac_kw[~np.isfinite(ac_kw)]
        assert (ac_kw[clear_day["ghi"] == 0] == 0).all(), ac_kw[clear_day["ghi"] == 0]


class TestAModuleWhoseCellsCannotHeatIsRefused:
    """NOCT-SAM heats a sunlit cell above the air only for a T_NOCT above NOCT's 20 °C test air and an efficiency below its 0.9 transmittance-absorptance."""

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("T_NOCT", math.nan),
            ("T_NOCT", 20.0),
            ("A_c", math.nan),
            ("A_c", 0.0),
            pytest.param("A_c", 0.4, id="A_c-0.4-so-an-efficiency-of-1.0"),
        ],
    )
    def test_naming_its_key_and_value(
        self, key: str, value: float, default_module: dict[str, float]
    ) -> None:
        config = PVConfig(capacity_kw=4.0, custom_module_params={**default_module, key: value})

        with pytest.raises(ValueError) as building:
            create_pv_system(config)
        with pytest.raises(ValueError) as wiring:
            wired_dc_capacity_kw(config)

        message = str(building.value)
        assert f"{key}={value}" in message, message
        assert str(wiring.value) == message
