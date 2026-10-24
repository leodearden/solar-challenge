# SPDX-License-Identifier: AGPL-3.0-or-later
"""What can name a run: a str holding a character other than whitespace.

It imports nothing from solar_challenge, so a reader of a request and the run store alike
can check a name with it.
"""

from typing import TypeGuard


def is_run_name(name: object) -> TypeGuard[str]:
    """Whether *name* can name a run: a str holding a character other than whitespace."""
    return isinstance(name, str) and name.strip() != ""


def require_run_name(name: object) -> str:
    """*name*, unchanged, when it can name a run (is_run_name).

    Raises:
        ValueError: *name* cannot name a run; the message starts "name is <name!r>".
    """
    if is_run_name(name):
        return name
    raise ValueError(f"name is {name!r}, not a run's name: a run's name holds a character other than whitespace")
