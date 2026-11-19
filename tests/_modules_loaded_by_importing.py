# SPDX-License-Identifier: AGPL-3.0-or-later
"""The solar_challenge modules an import loads, for the tests that pin what importing one module costs.

The module is imported in a fresh ``python -I`` interpreter, so the modules the test process
has already imported cannot hide what the import loads. web_modules_loaded_by_importing
answers only those of the web package, for the tests that pin how the web's modules layer.

Usage::

    from tests._modules_loaded_by_importing import package_modules_loaded_by_importing, web_modules_loaded_by_importing

    assert package_modules_loaded_by_importing("solar_challenge.errors") == {
        "solar_challenge",
        "solar_challenge.errors",
    }
    assert "solar_challenge.web.storage" not in web_modules_loaded_by_importing("solar_challenge.web.charts")
"""

import json
import subprocess
import sys

_PROBE = """\
import importlib
import json
import sys

importlib.import_module(sys.argv[1])
print(json.dumps([name for name in sys.modules if name == "solar_challenge" or name.startswith("solar_challenge.")]))
"""


def package_modules_loaded_by_importing(module: str) -> frozenset[str]:
    """The solar_challenge modules, the package included, that a fresh interpreter has loaded once it has imported *module*."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", _PROBE, module],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, f"importing {module} failed:\n{result.stderr}"
    loaded = frozenset(json.loads(result.stdout))
    assert module in loaded, f"the probe reported {sorted(loaded)}, without {module} itself"
    return loaded


def web_modules_loaded_by_importing(module: str) -> frozenset[str]:
    """The solar_challenge.web modules, the web package included, among those package_modules_loaded_by_importing answers for *module*."""
    return frozenset(
        name
        for name in package_modules_loaded_by_importing(module)
        if name == "solar_challenge.web" or name.startswith("solar_challenge.web.")
    )
