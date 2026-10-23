# SPDX-License-Identifier: AGPL-3.0-or-later
"""one_of: a value narrowed to the one of a closed set of text options it equals, such as a Literal's values.

It imports nothing from solar_challenge, so a reader of a request and a store's record alike
can check a value with it.
"""

from typing import TypeVar

_Option = TypeVar("_Option", bound=str)


def one_of(value: object, options: tuple[_Option, ...], field: str) -> _Option:
    """The one of *options* that *value* equals, typed as the options are: a text read from a request or a row narrows to its Literal.

    Raises:
        ValueError: *value* equals none of *options*; the message names *field*, *value* and each option.
    """
    for option in options:
        if value == option:
            return option
    raise ValueError(f"{field} is {value!r}, not one of {list(options)}")
