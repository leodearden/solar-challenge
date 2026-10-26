# SPDX-License-Identifier: AGPL-3.0-or-later
"""PVConfig.module_efficiency and temperature_coefficient: None keeps the template module's own.

The template is custom_module_params, or DEFAULT_CEC_MODULE's row without them. A set value
derives the module from that template. docs/pv-module-settings.md records the decision and
its measurements.
"""

import dataclasses
import math
import re
from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd
import pvlib
import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.pv import (
    PVConfig,
    create_pv_system,
    create_pvwatts_inverter_params,
    create_simple_module_params,
    wired_dc_capacity_kw,
)
from tests._pv_modules import default_module, pvwatts_300_w_module, sapm_library_module
from tests._pv_runs import clear_day_kwh

_CEC_SINGLE_DIODE_KEYS = ("alpha_sc", "a_ref", "I_L_ref", "I_o_ref", "R_sh_ref", "R_s", "Adjust")
_PVWATTS_KEYS = ("pdc0", "gamma_pdc")


def pdc0_module_without_gamma_pdc() -> dict[str, float]:
    """A module rated by its pdc0 and STC that lacks gamma_pdc, so is not in PVWatts form."""
    return {"STC": 450.0, "pdc0": 450.0}


def cec_module_without_alpha_sc() -> dict[str, float]:
    """DEFAULT_CEC_MODULE's row with no short-circuit current temperature coefficient: Adjust scales only alpha_sc, so no Adjust moves the modelled coefficient."""
    return {**default_module(), "alpha_sc": 0.0}


def cec_module_with_a_wide_band_gap() -> dict[str, float]:
    """DEFAULT_CEC_MODULE's row at a 3.0 eV band gap: the Adjusts that keep its photocurrent positive from -40 to 85 °C reach a modelled coefficient only from -0.0908 to -3.1151 %/K (measured), so not -0.05 %/K."""
    return {**default_module(), "EgRef": 3.0}


@pytest.fixture(scope="module")
def default_clear_day_kwh() -> float:
    """The default 4 kW's energy on the clear day: 26.8194 kWh."""
    return clear_day_kwh(PVConfig(capacity_kw=4.0))


def _p_mp_w(module: Mapping[str, float], cell_temperatures_c: list[float]) -> np.ndarray:
    """The module's maximum power at 1000 W/m² at each cell temperature, from pvlib's CEC single-diode model."""
    diode = pvlib.pvsystem.PVSystem(module_parameters=dict(module)).calcparams_cec(
        np.full(len(cell_temperatures_c), 1000.0), np.array(cell_temperatures_c)
    )
    return np.asarray(pvlib.pvsystem.singlediode(*diode)["p_mp"])


def _modelled_gamma_per_k(module: Mapping[str, float], half_width_k: float = 0.1) -> float:
    """dP_mp/dT / P_mp at 1000 W/m² and 25 °C, a central difference over 25 ± half_width_k °C."""
    p_cold, p_stc, p_hot = _p_mp_w(module, [25 - half_width_k, 25.0, 25 + half_width_k])
    return float((p_hot - p_cold) / (2 * half_width_k * p_stc))


def _p_mp_at_stc_w(module: Mapping[str, float]) -> float:
    return float(_p_mp_w(module, [25.0])[0])


def _assert_equal_apart_from(
    module: Mapping[str, object], template: Mapping[str, object], keys: set[str]
) -> None:
    """Assert the module holds the template's keys and values, but for keys, comparing as pandas does, so a NaN equals a NaN."""
    pd.testing.assert_series_equal(
        pd.Series({key: value for key, value in module.items() if key not in keys}, dtype=object),
        pd.Series({key: value for key, value in template.items() if key not in keys}, dtype=object),
    )


class TestUnsetMeansTheModulesOwn:
    def test_neither_field_is_set_by_default(self) -> None:
        config = PVConfig(capacity_kw=4.0)

        assert config.module_efficiency is None
        assert config.temperature_coefficient is None


class TestASettingOutsideItsDomainIsRefused:
    """A module efficiency lies above 0 and below NOCT-SAM's 0.9 transmittance-absorptance; a temperature coefficient from -0.01 per K to below 0."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("module_efficiency", value)
            for value in (0.0, -0.1, 0.9, 0.95, 1.0, math.nan, math.inf)
        ]
        + [
            ("temperature_coefficient", value)
            for value in (-0.02, -0.0100001, 0.0, 0.001, math.nan, -math.inf)
        ],
    )
    def test_naming_the_field_and_its_value(self, field: str, value: float) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            dataclasses.replace(PVConfig(capacity_kw=4.0), **{field: value})

        message = str(refusal.value)
        assert field in message, message
        assert f"got {value}" in message, message

    @pytest.mark.parametrize(
        ("field", "value"),
        [("module_efficiency", value) for value in (0.01, 0.2, 0.89)]
        + [("temperature_coefficient", value) for value in (-0.01, -0.005, -1e-6)],
    )
    def test_a_setting_inside_its_domain_is_kept_as_given(self, field: str, value: float) -> None:
        config = dataclasses.replace(PVConfig(capacity_kw=4.0), **{field: value})

        assert getattr(config, field) == value


class TestATemperatureCoefficientNeedsAModuleFormThatTakesIt:
    """A set coefficient solves a CEC single-diode module's Adjust or sets a PVWatts module's gamma_pdc, so a module in neither form cannot take it."""

    @pytest.mark.parametrize(
        "module",
        [
            pytest.param(sapm_library_module, id="sapm_module"),
            pytest.param(pdc0_module_without_gamma_pdc, id="pdc0_module_without_gamma_pdc"),
        ],
    )
    def test_a_module_in_neither_form_is_refused_naming_the_keys_of_each(
        self, module: Callable[[], dict[str, float]]
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            PVConfig(
                capacity_kw=4.0,
                temperature_coefficient=-0.004,
                custom_module_params=module(),
            )

        message = str(refusal.value)
        assert "temperature_coefficient" in message, message
        assert {*_CEC_SINGLE_DIODE_KEYS, *_PVWATTS_KEYS} <= set(re.findall(r"\w+", message)), message

    @pytest.mark.parametrize(
        "template",
        [
            pytest.param(lambda: None, id="DEFAULT_CEC_MODULE"),
            pytest.param(default_module, id="a-CECMod-row"),
            pytest.param(create_simple_module_params, id="create_simple_module_params"),
        ],
    )
    def test_a_cec_single_diode_or_pvwatts_module_takes_it(
        self, template: Callable[[], dict[str, float] | None]
    ) -> None:
        config = PVConfig(
            capacity_kw=4.0, temperature_coefficient=-0.004, custom_module_params=template()
        )

        assert config.temperature_coefficient == -0.004

    def test_a_module_efficiency_has_no_form_rule(self) -> None:
        """A module in neither form takes an efficiency over its rating, its STC; it has no V_mp_ref to voltage-match a CEC inverter to, so it takes custom inverter parameters."""
        module = pdc0_module_without_gamma_pdc()
        efficiency = 0.15
        config = PVConfig(
            capacity_kw=4.0,
            module_efficiency=efficiency,
            custom_module_params=module,
            custom_inverter_params=create_pvwatts_inverter_params(),
        )

        for array in create_pv_system(config).arrays:
            assert array.module_parameters["A_c"] == pytest.approx(
                module["STC"] / (efficiency * 1000)
            )
            assert array.temperature_model_parameters["module_efficiency"] == pytest.approx(
                efficiency
            )
            _assert_equal_apart_from(array.module_parameters, module, {"A_c"})


class TestASetEfficiencySetsTheModulesArea:
    """A set module_efficiency sets the template's A_c to its rating over efficiency x 1000 W/m², so it acts through NOCT-SAM's cell temperature."""

    @pytest.mark.parametrize("efficiency", [0.10, 0.22])
    @pytest.mark.parametrize(
        "template",
        [
            pytest.param(lambda: None, id="DEFAULT_CEC_MODULE"),
            pytest.param(pvwatts_300_w_module, id="a-300-W-PVWatts-module"),
        ],
    )
    def test_every_array_takes_the_area_at_which_its_rating_is_that_efficiency(
        self, template: Callable[[], dict[str, float] | None], efficiency: float
    ) -> None:
        custom_module_params = template()
        module = default_module() if custom_module_params is None else custom_module_params
        rating_w = module["STC"] if custom_module_params is None else module["pdc0"]
        config = PVConfig(
            capacity_kw=4.0, module_efficiency=efficiency, custom_module_params=custom_module_params
        )

        for array in create_pv_system(config).arrays:
            assert array.module_parameters["A_c"] == pytest.approx(rating_w / (efficiency * 1000))
            assert array.temperature_model_parameters["module_efficiency"] == pytest.approx(
                efficiency
            )
            _assert_equal_apart_from(array.module_parameters, module, {"A_c"})

    @pytest.mark.parametrize(
        "module",
        [
            pytest.param(create_simple_module_params(), id="create_simple_module_params"),
            pytest.param(pvwatts_300_w_module(), id="a-300-W-PVWatts-module"),
        ],
    )
    def test_with_neither_field_set_every_array_wires_the_template_as_it_is(
        self, module: dict[str, float]
    ) -> None:
        for array in create_pv_system(PVConfig(capacity_kw=4.0, custom_module_params=module)).arrays:
            assert array.module_parameters == module

    def test_a_less_efficient_module_runs_hotter_so_yields_less_on_a_clear_day(
        self, default_clear_day_kwh: float
    ) -> None:
        """Measured x0.990086 of the default's 26.8194 kWh."""
        kwh = clear_day_kwh(PVConfig(capacity_kw=4.0, module_efficiency=0.10))

        assert kwh <= 0.995 * default_clear_day_kwh, (
            f"4 kW at a module efficiency of 0.10 gave {kwh:.4f} kWh, "
            f"the default {default_clear_day_kwh:.4f} kWh"
        )


class TestASetTemperatureCoefficientOnACecModule:
    """A set coefficient solves a CEC single-diode template's Adjust, which scales only alpha_sc's temperature term, so the STC point stays the row's, and sets its gamma_r."""

    @pytest.mark.parametrize("coefficient", [-0.003, -0.005, -0.01, -1e-6])
    @pytest.mark.parametrize(
        "as_custom_params", [False, True], ids=["DEFAULT_CEC_MODULE", "its-row-as-custom-params"]
    )
    def test_the_derived_module_has_that_coefficient_at_the_rows_stc_point(
        self, coefficient: float, as_custom_params: bool
    ) -> None:
        row = default_module()
        config = PVConfig(
            capacity_kw=4.0,
            temperature_coefficient=coefficient,
            custom_module_params=row if as_custom_params else None,
        )

        for array in create_pv_system(config).arrays:
            module = array.module_parameters
            modelled = _modelled_gamma_per_k(module)
            assert abs(modelled - coefficient) <= 1e-6, f"modelled {modelled} per K"
            assert module["gamma_r"] == pytest.approx(100 * coefficient)
            assert _p_mp_at_stc_w(module) == pytest.approx(_p_mp_at_stc_w(row), rel=1e-9)
            _assert_equal_apart_from(module, row, {"Adjust", "gamma_r"})

    def test_the_rows_own_coefficient_gives_back_the_row(
        self, default_clear_day_kwh: float
    ) -> None:
        """The row's own modelled coefficient at a 0.5 K half-width is -0.34730 %/K, beside its catalogue gamma_r of -0.3448."""
        row = default_module()
        config = PVConfig(
            capacity_kw=4.0,
            temperature_coefficient=_modelled_gamma_per_k(row, half_width_k=0.5),
        )

        for array in create_pv_system(config).arrays:
            assert array.module_parameters["Adjust"] == pytest.approx(
                row["Adjust"], abs=1e-6
            )
        assert clear_day_kwh(config) == pytest.approx(default_clear_day_kwh, rel=1e-9)


class TestASetTemperatureCoefficientOnAPvwattsModule:
    def test_sets_its_gamma_pdc(self) -> None:
        module = pvwatts_300_w_module()
        config = PVConfig(
            capacity_kw=4.0, temperature_coefficient=-0.005, custom_module_params=module
        )

        for array in create_pv_system(config).arrays:
            assert array.module_parameters["gamma_pdc"] == -0.005
            _assert_equal_apart_from(array.module_parameters, module, {"gamma_pdc"})


class TestASetTemperatureCoefficientActsOnAClearDay:
    """The clear day's cells run above 25 °C, so a steeper coefficient yields less; over a Bristol year they run mostly below it, so no annual direction holds (docs/pv-module-settings.md)."""

    def test_a_steeper_coefficient_yields_less(self, default_clear_day_kwh: float) -> None:
        """Measured x0.978618 of the default's 26.8194 kWh at -0.005 per K."""
        kwh = clear_day_kwh(PVConfig(capacity_kw=4.0, temperature_coefficient=-0.005))

        assert kwh <= 0.985 * default_clear_day_kwh, (
            f"-0.005 per K gave {kwh:.4f} kWh, the default {default_clear_day_kwh:.4f} kWh"
        )

    def test_a_shallower_coefficient_yields_more(self, default_clear_day_kwh: float) -> None:
        """Measured x1.006607 of the default's at -0.003 per K."""
        kwh = clear_day_kwh(PVConfig(capacity_kw=4.0, temperature_coefficient=-0.003))

        assert kwh > default_clear_day_kwh, (
            f"-0.003 per K gave {kwh:.4f} kWh, the default {default_clear_day_kwh:.4f} kWh"
        )


class TestACoefficientNoAdjustReachesIsRefusedAtUse:
    @pytest.mark.parametrize(
        ("module", "coefficient"),
        [
            pytest.param(
                cec_module_without_alpha_sc, -0.004, id="cec_module_without_alpha_sc--0.004"
            ),
            pytest.param(
                cec_module_with_a_wide_band_gap,
                -0.0005,
                id="cec_module_with_a_wide_band_gap--0.0005",
            ),
        ],
    )
    def test_naming_the_field_and_its_value(
        self, module: Callable[[], dict[str, float]], coefficient: float
    ) -> None:
        config = PVConfig(
            capacity_kw=4.0,
            temperature_coefficient=coefficient,
            custom_module_params=module(),
        )

        with pytest.raises(ValueError) as building:
            create_pv_system(config)
        with pytest.raises(ValueError) as wiring:
            wired_dc_capacity_kw(config)

        message = str(building.value)
        assert f"temperature_coefficient={coefficient}" in message, message
        assert str(wiring.value) == message
