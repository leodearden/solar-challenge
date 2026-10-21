# SPDX-License-Identifier: AGPL-3.0-or-later
"""PVConfig.module_efficiency and temperature_coefficient: None keeps the template module's own.

The template is custom_module_params, or DEFAULT_CEC_MODULE's row without them. A set value
derives the module from that template. docs/pv-module-settings.md records the decision and
its measurements.
"""

import dataclasses
import math
import re
from collections.abc import Callable

import pvlib
import pytest
from solar_challenge.pv import (
    DEFAULT_CEC_MODULE,
    PVConfig,
    cec_module_params,
    create_simple_module_params,
)

_CEC_SINGLE_DIODE_KEYS = ("alpha_sc", "a_ref", "I_L_ref", "I_o_ref", "R_sh_ref", "R_s", "Adjust")
_PVWATTS_KEYS = ("pdc0", "gamma_pdc")


@pytest.fixture
def sapm_module() -> dict[str, float]:
    """The first row of pvlib's SAPM module library (SandiaMod), in neither CEC single-diode nor PVWatts form."""
    return dict(pvlib.pvsystem.retrieve_sam("SandiaMod").iloc[:, 0])


@pytest.fixture
def pdc0_module_without_gamma_pdc() -> dict[str, float]:
    """A module rated by its pdc0 and STC that lacks gamma_pdc, so is not in PVWatts form."""
    return {"STC": 450.0, "pdc0": 450.0}


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
        with pytest.raises(ValueError) as refusal:
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

    @pytest.mark.parametrize("module", ["sapm_module", "pdc0_module_without_gamma_pdc"])
    def test_a_module_in_neither_form_is_refused_naming_the_keys_of_each(
        self, request: pytest.FixtureRequest, module: str
    ) -> None:
        with pytest.raises(ValueError) as refusal:
            PVConfig(
                capacity_kw=4.0,
                temperature_coefficient=-0.004,
                custom_module_params=request.getfixturevalue(module),
            )

        message = str(refusal.value)
        assert "temperature_coefficient" in message, message
        assert {*_CEC_SINGLE_DIODE_KEYS, *_PVWATTS_KEYS} <= set(re.findall(r"\w+", message)), message

    @pytest.mark.parametrize(
        "template",
        [
            pytest.param(lambda: None, id="DEFAULT_CEC_MODULE"),
            pytest.param(lambda: cec_module_params(DEFAULT_CEC_MODULE), id="a-CECMod-row"),
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

    def test_a_module_efficiency_has_no_form_rule(self, sapm_module: dict[str, float]) -> None:
        config = PVConfig(capacity_kw=4.0, module_efficiency=0.15, custom_module_params=sapm_module)

        assert config.module_efficiency == 0.15
