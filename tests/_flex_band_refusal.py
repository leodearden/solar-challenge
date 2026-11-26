# SPDX-License-Identifier: AGPL-3.0-or-later
"""The refusal of a scenario's flex_band that names no band, as GridServicesBand.parse writes it."""

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.gridservices import GridServicesBand


def flex_band_refusal(value: object, what: str = "flex_band") -> str:
    """The message GridServicesBand.parse refuses *value* with, for *what*."""
    with pytest.raises(ConfigurationError) as refusal:
        GridServicesBand.parse(value, what=what)
    return str(refusal.value)
