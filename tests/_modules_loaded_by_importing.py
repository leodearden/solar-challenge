# SPDX-License-Identifier: AGPL-3.0-or-later
"""The modules an import loads, for the tests that pin what importing one module costs.

The module is imported in a fresh ``python -I`` interpreter, so the modules the test process
has already imported cannot hide what the import loads. modules_loaded_by_importing answers
every module, third-party ones included; package_modules_loaded_by_importing only those of
solar_challenge, and web_modules_loaded_by_importing only those of the web package, for the
tests that pin how the web's modules layer.

Usage::

    from tests._modules_loaded_by_importing import (
        modules_loaded_by_importing,
        package_modules_loaded_by_importing,
        web_modules_loaded_by_importing,
    )

    assert "pvlib" not in modules_loaded_by_importing("solar_challenge.finance")
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
print(json.dumps(list(sys.modules)))
"""


def modules_loaded_by_importing(module: str) -> frozenset[str]:
    """The name of every module in a fresh interpreter's sys.modules once it has imported *module*."""
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


def package_modules_loaded_by_importing(module: str) -> frozenset[str]:
    """The solar_challenge modules, the package included, among those modules_loaded_by_importing answers for *module*."""
    return frozenset(
        name
        for name in modules_loaded_by_importing(module)
        if name == "solar_challenge" or name.startswith("solar_challenge.")
    )


def web_modules_loaded_by_importing(module: str) -> frozenset[str]:
    """The solar_challenge.web modules, the web package included, among those package_modules_loaded_by_importing answers for *module*."""
    return frozenset(
        name
        for name in package_modules_loaded_by_importing(module)
        if name == "solar_challenge.web" or name.startswith("solar_challenge.web.")
    )
