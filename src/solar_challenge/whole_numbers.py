# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rule a configured count is held to: a finite number with no fractional part, and never a bool."""

import math
from typing import Optional

import numpy as np


def whole_number(value: float) -> Optional[int]:
    """Return the int *value* equals, or None if it is a bool, Python's or numpy's, is not finite, or has a fractional part.

    A whole-number float such as 20.0, or a numpy integer, gives the plain int it equals.
    """
    if isinstance(value, (bool, np.bool_)) or not -math.inf < value < math.inf:
        return None
    whole = int(value)
    return whole if whole == value else None
