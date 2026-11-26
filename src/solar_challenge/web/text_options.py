# SPDX-License-Identifier: AGPL-3.0-or-later
"""A value narrowed to the one of a closed set of text options it equals, such as a Literal's values.

one_of is a store's check of a value it holds, read_one_of a request reader's. It imports
only solar_challenge.errors, the package's leaf, so a reader of a request and a store's
record alike can check a value with it.
"""

from typing import TypeVar

from solar_challenge.errors import ConfigurationError

_Option = TypeVar("_Option", bound=str)


def one_of(value: object, options: tuple[_Option, ...], field: str) -> _Option:
    """The one of *options* that *value* equals, typed as the options are: a store's check of a value it holds, such as a row's, narrowed to its Literal.

    Raises:
        ValueError: *value* equals none of *options*; the message names *field*, *value* and
            each option. A stored value outside its options is a defect, so this is not a
            ConfigurationError.
    """
    option = _option_equal_to(value, options)
    if option is None:
        raise ValueError(_not_one_of(value, options, field))
    return option


def read_one_of(value: object, options: tuple[_Option, ...], field: str) -> _Option:
    """The one of *options* that *value*, a request's value, equals, typed as the options are: a request's text narrowed to its Literal.

    Raises:
        ConfigurationError: *value* equals none of *options*, with one_of's message.
    """
    option = _option_equal_to(value, options)
    if option is None:
        raise ConfigurationError(_not_one_of(value, options, field))
    return option


def _option_equal_to(value: object, options: tuple[_Option, ...]) -> _Option | None:
    for option in options:
        if value == option:
            return option
    return None


def _not_one_of(value: object, options: tuple[str, ...], field: str) -> str:
    return f"{field} is {value!r}, not one of {list(options)}"
