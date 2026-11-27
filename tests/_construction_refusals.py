# SPDX-License-Identifier: AGPL-3.0-or-later
"""The refusal a scenario block's reader is expected to give for a value its type refuses: the type's own message, computed by constructing the type, after the block's path.

The wording after the path belongs to the type, so a test computes it rather than typing it,
and pins only the composition "<block path>: <the type's own message>".

Usage::

    from tests._construction_refusals import prefixed_construction_refusal

    with pytest.raises(ConfigurationError) as refusal:
        parse_home_block({"pv": {"capacity_kw": True}}, Location.bristol())
    assert str(refusal.value) == prefixed_construction_refusal(
        "home.pv", lambda: PVConfig(capacity_kw=True)
    )
"""

from typing import Callable

import pytest

from solar_challenge.errors import ConfigurationError


def construction_refusal(build: Callable[[], object]) -> str:
    """The message of the ConfigurationError that calling *build* raises, asserting that it raises one."""
    with pytest.raises(ConfigurationError) as refusal:
        build()
    return str(refusal.value)


def prefixed_construction_refusal(label: str, build: Callable[[], object]) -> str:
    """The refusal of *build*, as construction_refusal gives it, after *label*, the refusing block's name: "<label>: <message>"."""
    return f"{label}: {construction_refusal(build)}"
