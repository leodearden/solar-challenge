# SPDX-License-Identifier: AGPL-3.0-or-later
"""scripts/measure_mppt_window.py's measurement (b): the power of strings held at an MPPT window edge on their IV curve.

docs/pv-inverter-string-matching.md §3 describes it and §4 records its figures.
tests/unit/test_measurement_scripts.py runs the rest of the script offline.
"""

import dataclasses

import pytest
from pvlib.modelchain import ModelChain

from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, create_model_chain, create_pv_system
from tests._scripts import load_script
from tests._synthetic_weather import synthetic_june_weather


def _default_array_on(inverter: dict[str, float]) -> ModelChain:
    """The default 4 kW array on custom inverter parameters, which wire all its modules as one string."""
    config = dataclasses.replace(PVConfig.default_4kw(), custom_inverter_params=inverter)
    return create_model_chain(config, Location.bristol())


def test_the_held_power_carries_the_system_losses_as_p_mp_does() -> None:
    """A string held 0.1% below its V_mp, where the IV curve's power is flat, keeps all but about 1e-5 of its p_mp, so the held AC is measurement (a)'s, the ceiling's voltage at the model's own DC power, to well within 1e-5 of the day's.

    p_mp already carries the chain's system losses, so the held power matches it
    only if it carries them too.
    """
    mppt_window = load_script("measure_mppt_window")
    day = synthetic_june_weather("1990-06-21")
    inverter = create_pv_system(PVConfig.default_4kw()).inverter_parameters
    in_window = _default_array_on(inverter)
    in_window.run_model(day)
    ceiling_v = 0.999 * in_window.results.dc["v_mp"].max()

    held_above = mppt_window.measure_year(
        _default_array_on({**inverter, "Mppt_high": ceiling_v}), day
    ).above_ceiling

    assert held_above.hours > 0
    assert held_above.ac_kwh_held == pytest.approx(held_above.ac_kwh_clipped, rel=1e-5)
