# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reader of boolean settings: a boolean setting is true or false, never a value read by its truthiness.

The module imports no package module but errors and whole_numbers, so any module can import it.
"""

from solar_challenge.errors import ConfigurationError
from solar_challenge.whole_numbers import is_boolean


def as_boolean(value: object, field: str) -> bool:
    """Return *value*, a bool, Python's or numpy's, as the Python bool it is.

    Raises:
        ConfigurationError: For any other value, None, a number, a string such as "false" and
            any container included, naming *field* and *value*.
    """
    if not is_boolean(value):
        raise ConfigurationError.must_be(field, "true or false", got=value)
    return bool(value)
