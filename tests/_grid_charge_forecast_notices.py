# SPDX-License-Identifier: AGPL-3.0-or-later
"""The grid-charge forecast notices a report gives under its first heading, for the forecasts that sized its homes' grid charge.

Usage::

    from tests._grid_charge_forecast_notices import TRAILING_NOTICE

    report = generate_summary_report(replace(results, grid_charge_forecast="trailing_14_days"))
    assert report.startswith("# Simulation Report\\n\\n" + TRAILING_NOTICE + "## Simulation Period")
"""

from solar_challenge.grid_charge_forecast import GRID_CHARGE_FORECAST_LABELS

TRAILING_NOTICE = (
    "*Battery grid charging in cheap periods was sized by the trailing_14_days forecast: "
    f"{GRID_CHARGE_FORECAST_LABELS['trailing_14_days']}.*\n\n"
)
PV_BLIND_AND_TRAILING_NOTICE = (
    "*Battery grid charging in cheap periods was sized by the pv_blind forecast: "
    f"{GRID_CHARGE_FORECAST_LABELS['pv_blind']}; and by the trailing_14_days forecast: "
    f"{GRID_CHARGE_FORECAST_LABELS['trailing_14_days']}.*\n\n"
)
