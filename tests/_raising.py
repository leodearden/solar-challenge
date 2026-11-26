# SPDX-License-Identifier: AGPL-3.0-or-later
"""raising: a stand-in for a function, which raises the one exception it is given whatever it is called with.

A test patches a boundary site's reader with it to reach a failure no input reaches
reliably, such as a ValueError that is not a ConfigurationError, or a TypeError.
"""

from collections.abc import Callable
from typing import NoReturn


def raising(error: Exception) -> Callable[..., NoReturn]:
    """A function that raises *error*, whatever arguments it is called with."""

    def raise_error(*_args: object, **_kwargs: object) -> NoReturn:
        raise error

    return raise_error
