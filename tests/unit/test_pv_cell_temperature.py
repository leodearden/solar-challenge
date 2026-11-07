# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each array's cells run at NOCT-SAM's temperature, from the array's own module.

The module's T_NOCT, and its rating over its area (A_c x 1000 W/m²) as its efficiency,
feed pvlib's noct_sam; a module lacking either key takes DEFAULT_CEC_MODULE's value.
docs/pv-cell-temperature.md records the decision and its measurements.
"""

import dataclasses
import math
from collections.abc import Callable

import numpy as np
import pandas as pd
import pvlib
import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.location import Location
from solar_challenge.pv import (
    PVConfig,
    create_model_chain,
    create_pv_system,
    create_simple_module_params,
    simulate_pv_output,
)
from tests._pv_modules import default_module, pvwatts_300_w_module
from tests._pv_refusals import one_refusal_at_construction_and_at_use
from tests._pv_runs import clear_day_kwh, clear_day_weather, per_array


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
        self, capacity_kw: float, array_count: int
    ) -> None:
        """Sunless hours compare equal: noct_sam's cell temperature is NaN in each of them."""
        clear_day = clear_day_weather()
        row = default_module()
        chain = create_model_chain(PVConfig(capacity_kw=capacity_kw), Location.bristol())
        assert len(chain.system.arrays) == array_count

        chain.run_model(clear_day)

        for cell_temperature, total_irrad, effective_irradiance in zip(
            per_array(chain.results.cell_temperature),
            per_array(chain.results.total_irrad),
            per_array(chain.results.effective_irradiance),
            strict=True,
        ):
            noct_sam = pvlib.temperature.noct_sam(
                total_irrad["poa_global"],
                clear_day["temp_air"],
                clear_day["wind_speed"],
                noct=row["T_NOCT"],
                module_efficiency=row["STC"] / (row["A_c"] * 1000),
                effective_irradiance=effective_irradiance,
            )
            pd.testing.assert_series_equal(cell_temperature, noct_sam, check_names=False)

    def test_the_default_4kw_clear_day_energy_is_noct_sams(self) -> None:
        """x1.031 the 26.0119 kWh of SAPM's generic open-rack glass/glass set (docs/pv-cell-temperature.md §3)."""
        assert clear_day_kwh(PVConfig.default_4kw()) == pytest.approx(26.819, rel=1e-3)

    def test_a_less_efficient_module_runs_hotter_so_yields_less(self) -> None:
        def kwh_at(efficiency: float) -> float:
            module = create_simple_module_params(efficiency=efficiency)
            return clear_day_kwh(PVConfig(capacity_kw=4.0, custom_module_params=module))

        kwh_at_10_percent, kwh_at_22_percent = kwh_at(0.10), kwh_at(0.22)

        assert kwh_at_10_percent <= 0.995 * kwh_at_22_percent, (
            f"4 kW of 10% efficient modules gave {kwh_at_10_percent:.4f} kWh, "
            f"and of 22% efficient modules {kwh_at_22_percent:.4f} kWh"
        )

    @pytest.mark.parametrize(
        "module_and_its_noct_and_efficiency",
        [
            pytest.param(
                lambda row: (pvwatts_300_w_module(), row["T_NOCT"], 300 / (row["A_c"] * 1000)),
                id="neither-key",
            ),
            pytest.param(
                lambda row: (
                    {**pvwatts_300_w_module(), "T_NOCT": 48.0},
                    48.0,
                    300 / (row["A_c"] * 1000),
                ),
                id="own-T_NOCT",
            ),
            pytest.param(
                lambda row: ({**pvwatts_300_w_module(), "A_c": 1.5}, row["T_NOCT"], 0.2),
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
    ) -> None:
        """Each case gives the module, then the noct and module_efficiency its arrays get, from DEFAULT_CEC_MODULE's row."""
        module, noct, efficiency = module_and_its_noct_and_efficiency(default_module())

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
    def test_the_ac_is_finite_every_hour_and_zero_without_sun(self, config: PVConfig) -> None:
        """Where noct_sam's cell temperature is NaN, pvlib fills the DC or AC with 0, so no NaN reaches an energy total."""
        clear_day = clear_day_weather()
        ac_kw = simulate_pv_output(config, Location.bristol(), clear_day)

        assert np.isfinite(ac_kw).all(), ac_kw[~np.isfinite(ac_kw)]
        assert (ac_kw[clear_day["ghi"] == 0] == 0).all(), ac_kw[clear_day["ghi"] == 0]


def _default_area_in_a_refusal() -> str:
    """How a refusal names the A_c that DEFAULT_CEC_MODULE gives a module with none."""
    return f"A_c={default_module()['A_c']} (DEFAULT_CEC_MODULE's, since the module gives none)"


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
    def test_at_construction_and_at_use_naming_its_key_and_value(
        self, key: str, value: float
    ) -> None:
        """A PVConfig keeps the caller's own module dict, so an edit after construction reaches use, which refuses it as construction does."""
        module = default_module()
        config = PVConfig(capacity_kw=4.0, custom_module_params=module)
        module[key] = value

        message = one_refusal_at_construction_and_at_use(config)
        assert f"{key}={value}" in message, message

    def test_naming_a_value_it_lacks_as_the_default_modules(self) -> None:
        """A 300 W PVWatts module, rerated after construction as one 4000 W module for a whole 4 kW array, lacks A_c, so takes the default module's: an efficiency of 4000 / 1990 = 2.0."""
        module = pvwatts_300_w_module()
        config = PVConfig(capacity_kw=4.0, custom_module_params=module)
        module["pdc0"] = 4000.0

        message = one_refusal_at_construction_and_at_use(config)
        assert _default_area_in_a_refusal() in message, message
        assert "Give the module its own A_c" in message, message


class TestASetModuleEfficiencyGivesTheCheckedArea:
    """Construction checks the module at the area A_c over which a set module_efficiency spreads its rating, rating / (efficiency × 1000 W/m²), the area its arrays are wired with."""

    def test_instead_of_the_default_modules_to_a_module_with_no_area(self) -> None:
        """A 4000 W module with no A_c would take DEFAULT_CEC_MODULE's 1.99 m², an efficiency of 2.0 that construction refuses; a module_efficiency of 0.2 spreads its 4000 W over 20 m², so construction accepts it and its cells run at 0.2."""
        config = PVConfig(
            capacity_kw=4.0,
            custom_module_params={"pdc0": 4000.0, "gamma_pdc": -0.004},
            module_efficiency=0.2,
        )

        with pytest.raises(ConfigurationError) as refusal:
            dataclasses.replace(config, module_efficiency=None)
        message = str(refusal.value)
        assert _default_area_in_a_refusal() in message, message

        for array in create_pv_system(config).arrays:
            assert array.temperature_model_parameters["module_efficiency"] == pytest.approx(0.2)

    @pytest.mark.parametrize(
        ("template", "rating_key", "coefficient_key", "coefficient_value"),
        [
            pytest.param(pvwatts_300_w_module, "pdc0", "gamma_pdc", -0.005, id="a-300-W-PVWatts-module"),
            pytest.param(default_module, "STC", "gamma_r", -0.5, id="DEFAULT_CEC_MODULE-row"),
        ],
    )
    def test_a_set_temperature_coefficient_keeps_the_area_a_set_efficiency_gives(
        self,
        template: Callable[[], dict[str, float]],
        rating_key: str,
        coefficient_key: str,
        coefficient_value: float,
    ) -> None:
        """Construction checks the module with a set module_efficiency's area but not a set temperature_coefficient, which changes none of the rating, T_NOCT and A_c NOCT-SAM reads: the module use wires takes both settings, and its cells run at the set efficiency."""
        module = template()
        config = PVConfig(
            capacity_kw=4.0,
            custom_module_params=module,
            module_efficiency=0.15,
            temperature_coefficient=-0.005,
        )

        for array in create_pv_system(config).arrays:
            assert array.module_parameters["A_c"] == pytest.approx(module[rating_key] / (0.15 * 1000))
            assert array.module_parameters[coefficient_key] == pytest.approx(coefficient_value)
            assert array.temperature_model_parameters["module_efficiency"] == pytest.approx(0.15)
