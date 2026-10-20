# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which submodules the package's lazy loader maps public names to import pvlib.

The first access of a public name imports the submodule the lazy loader maps it to, so a
name costs the consumer pvlib exactly when that submodule imports it. The 'Lazy pvlib
dependency' caveat in docs/domain-library-consumption.md tells consumers which submodules
those are. Each case runs in a fresh ``python -I`` interpreter that imported only
solar_challenge, so the modules that earlier tests imported cannot hide what a name loads.
"""

import json
import subprocess
import sys

import pytest

import solar_challenge

PVLIB_IMPORTING_SUBMODULES = frozenset({"config", "fleet", "home", "pv", "weather"})

_PROBE = """\
import json
import sys

import solar_challenge

getattr(solar_challenge, sys.argv[1])
print(json.dumps("pvlib" in sys.modules))
"""


def _a_public_name_per_lazily_mapped_submodule() -> dict[str, str]:
    """Return each submodule the lazy loader maps public names to, with one of those names."""
    return {submodule: name for name, submodule in solar_challenge._SYMBOL_MODULE.items()}


def _first_access_loads_pvlib(public_name: str) -> bool:
    """Return whether the first access of solar_challenge.<public_name> loads pvlib, in a fresh interpreter that imported only solar_challenge."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", _PROBE, public_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, f"the probe of solar_challenge.{public_name} failed:\n{result.stderr}"
    loads_pvlib: bool = json.loads(result.stdout)
    return loads_pvlib


@pytest.mark.parametrize(
    ("submodule", "public_name"),
    [
        pytest.param(submodule, public_name, id=submodule)
        for submodule, public_name in sorted(_a_public_name_per_lazily_mapped_submodule().items())
    ],
)
def test_the_first_access_of_a_public_name_loads_pvlib_exactly_for_the_listed_submodules(
    submodule: str, public_name: str
) -> None:
    loads_pvlib = _first_access_loads_pvlib(public_name)

    assert loads_pvlib == (submodule in PVLIB_IMPORTING_SUBMODULES), (
        f"the first access of solar_challenge.{public_name} {'loads' if loads_pvlib else 'leaves unloaded'} pvlib, "
        f"and PVLIB_IMPORTING_SUBMODULES in tests/unit/test_lazy_pvlib_submodules.py "
        f"{'omits' if loads_pvlib else 'lists'} {submodule}. Change that set and the 'Lazy pvlib dependency' "
        "caveat in docs/domain-library-consumption.md together, so consumers learn what the name now costs"
    )


def test_every_listed_submodule_still_has_public_names() -> None:
    stale = PVLIB_IMPORTING_SUBMODULES - set(_a_public_name_per_lazily_mapped_submodule())

    assert not stale, (
        f"the lazy loader maps no public name to {sorted(stale)} any more, so they go from "
        "PVLIB_IMPORTING_SUBMODULES in tests/unit/test_lazy_pvlib_submodules.py and from the "
        "'Lazy pvlib dependency' caveat in docs/domain-library-consumption.md"
    )
