# SPDX-License-Identifier: AGPL-3.0-or-later
"""The PV modules the PV tests build systems from, each a new dict of module parameters on every call, so no test's edit reaches another's.

Usage::

    from tests._pv_modules import default_module, pvwatts_300_w_module

    config = PVConfig(capacity_kw=4.0, custom_module_params=pvwatts_300_w_module())
    module_whose_cells_cannot_heat = {**default_module(), "T_NOCT": 20.0}
"""

import pvlib

from solar_challenge.pv import DEFAULT_CEC_MODULE, cec_module_params


def default_module() -> dict[str, float]:
    """DEFAULT_CEC_MODULE's row of pvlib's CEC module library, the module a PVConfig without custom_module_params wires."""
    return cec_module_params(DEFAULT_CEC_MODULE)


def default_module_beyond_every_mppt_window() -> dict[str, float]:
    """default_module() with a V_mp_ref that no CEC inverter's MPPT window admits, even as a one-module string."""
    return {**default_module(), "V_mp_ref": 1e6}


def pvwatts_300_w_module() -> dict[str, float]:
    """A 300 W module in PVWatts form, rated by its pdc0, with no STC, T_NOCT or A_c of its own."""
    return {"pdc0": 300.0, "gamma_pdc": -0.004}


def sapm_library_module() -> dict[str, float]:
    """The first row of pvlib's SAPM module library (SandiaMod), rated by neither a pdc0 nor an STC and in neither CEC single-diode nor PVWatts form."""
    return dict(pvlib.pvsystem.retrieve_sam("SandiaMod").iloc[:, 0])


def pvsyst_module() -> dict[str, float]:
    """A module in pvlib's PVsyst single-diode form, which pvlib infers as 'pvsyst', its STC and V_mp_ref its own P_mp (146.95 W) and V_mp (26.57 V) at 1000 W/m² and 25 °C; a 4 kW PVConfig of it wires a CEC inverter and simulates."""
    return {
        "gamma_ref": 1.05,
        "mu_gamma": 0.001,
        "I_L_ref": 6.0,
        "I_o_ref": 5e-9,
        "EgRef": 1.121,
        "R_sh_ref": 300.0,
        "R_sh_0": 1000.0,
        "R_s": 0.5,
        "R_sh_exp": 5.5,
        "cells_in_series": 60,
        "alpha_sc": 0.001,
        "STC": 147.0,
        "V_mp_ref": 26.6,
    }
