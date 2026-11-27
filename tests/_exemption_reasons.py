# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two reasons a guard's exemption table may give for an entry: the documented contract that keeps it for good, or the task or program stream that removes it.

Usage::

    from tests._exemption_reasons import Permanent, Transitional

    EXEMPT: dict[str, Permanent | Transitional] = {
        "solar_challenge.config.load_config": Permanent("its subject is a file path"),
    }
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Permanent:
    """The documented contract that keeps an exempted entry, such as an import inside a function, for good."""

    contract: str


@dataclass(frozen=True)
class Transitional:
    """The task or program stream that removes an exempted entry, such as one that moves an import to module top or deletes it."""

    owner: str
