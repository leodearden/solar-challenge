# SPDX-License-Identifier: AGPL-3.0-or-later
"""Booleans as the package's settings hold them: a bool is Python's or numpy's, and a boolean setting is true or false, never a value read by its truthiness.

The module imports no package module but errors, so any module can import it.
"""

import numpy as np

from solar_challenge.errors import ConfigurationError


def is_boolean(value: object) -> bool:
    """Whether *value* is a bool, Python's or numpy's, which is never a number setting though it compares equal to 1 or 0."""
    return isinstance(value, (bool, np.bool_))


def as_boolean(value: object, field: str) -> bool:
    """Return *value*, a bool, Python's or numpy's, as the Python bool it is.

    Raises:
        ConfigurationError: For any other value, None, a number, a string such as "false" and
            any container included, naming *field* and *value*.
    """
    if not is_boolean(value):
        raise ConfigurationError.must_be(field, "true or false", got=value)
    return bool(value)
