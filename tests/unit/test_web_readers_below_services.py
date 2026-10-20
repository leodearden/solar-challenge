# SPDX-License-Identifier: AGPL-3.0-or-later
"""The web's request readers sit below its Flask services (docs/prds/web-request-boundary.md, row G1).

Importing simulation_params, fleet_scenario or builder_form loads none of the service
modules web.database, web.jobs and web.storage, and importing request_boundary loads no
solar_challenge.web module but the package and itself.

Each case imports in a fresh ``python -I`` interpreter, so modules imported earlier
cannot hide what the import loads.
"""

import json
import subprocess
import sys

import pytest

pytest.importorskip("flask")

_SERVICE_MODULES = frozenset(
    {"solar_challenge.web.database", "solar_challenge.web.jobs", "solar_challenge.web.storage"}
)

_PROBE = """\
import importlib
import json
import sys

importlib.import_module(sys.argv[1])
print(json.dumps(sorted(
    name for name in sys.modules if name == "solar_challenge.web" or name.startswith("solar_challenge.web.")
)))
"""


def _web_modules_loaded_by_importing(module: str) -> set[str]:
    """The solar_challenge.web modules a fresh interpreter has loaded once it has imported *module*."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", _PROBE, module],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, f"importing {module} failed:\n{result.stderr}"
    loaded = set(json.loads(result.stdout))
    assert module in loaded, f"the probe reported {sorted(loaded)}, without {module} itself"
    return loaded


@pytest.mark.parametrize(
    "reader",
    [
        "solar_challenge.web.simulation_params",
        "solar_challenge.web.fleet_scenario",
        "solar_challenge.web.builder_form",
    ],
)
def test_importing_a_request_reader_loads_no_service_module(reader: str) -> None:
    loaded = _web_modules_loaded_by_importing(reader)

    assert _SERVICE_MODULES.isdisjoint(loaded), (
        f"importing {reader} loaded the services {sorted(_SERVICE_MODULES & loaded)}"
    )


def test_importing_request_boundary_loads_no_other_web_module() -> None:
    assert _web_modules_loaded_by_importing("solar_challenge.web.request_boundary") == {
        "solar_challenge.web",
        "solar_challenge.web.request_boundary",
    }
