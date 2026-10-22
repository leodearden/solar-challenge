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


def pvwatts_300_w_module() -> dict[str, float]:
    """A 300 W module in PVWatts form, rated by its pdc0, with no STC, T_NOCT or A_c of its own.

    test_pv.py's without-STC cases and test_pv_cell_temperature.py's neither-key, own-T_NOCT and own-A_c cases read
    those absences.
    """
    return {"pdc0": 300.0, "gamma_pdc": -0.004}


def sapm_library_module() -> dict[str, float]:
    """The first row of pvlib's SAPM module library (SandiaMod), rated by neither a pdc0 nor an STC and in neither CEC single-diode nor PVWatts form."""
    return dict(pvlib.pvsystem.retrieve_sam("SandiaMod").iloc[:, 0])
