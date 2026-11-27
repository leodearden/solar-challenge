# SPDX-License-Identifier: AGPL-3.0-or-later
"""What can name a run: a str holding a character other than whitespace.

It imports only solar_challenge.errors, the package's leaf, so a reader of a request and the
run store alike can check a name with it.
"""

from typing import TypeGuard

from solar_challenge.errors import ConfigurationError


def is_run_name(name: object) -> TypeGuard[str]:
    """Whether *name* can name a run: a str holding a character other than whitespace."""
    return isinstance(name, str) and name.strip() != ""


def require_run_name(name: object) -> str:
    """*name*, unchanged, when it can name a run (is_run_name): the run store's check of a name it holds.

    Raises:
        ValueError: *name* cannot name a run; the message starts "name is <name!r>". A stored
            name that cannot name a run is a defect, so this is not a ConfigurationError.
    """
    if is_run_name(name):
        return name
    raise ValueError(_not_a_run_name(name))


def read_run_name(name: object) -> str:
    """*name*, a request's run name, unchanged, when it can name a run (is_run_name).

    Raises:
        ConfigurationError: *name* cannot name a run, with require_run_name's message.
    """
    if is_run_name(name):
        return name
    raise ConfigurationError(_not_a_run_name(name))


def _not_a_run_name(name: object) -> str:
    return f"name is {name!r}, not a run's name: a run's name holds a character other than whitespace"
