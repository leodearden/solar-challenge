# SPDX-License-Identifier: AGPL-3.0-or-later
"""The measurement scripts under scripts/, loaded as modules for the tests that run them.

scripts/ is not a package, so each script is loaded from its file.

Usage::

    from tests._scripts import load_script

    performance_ratio = load_script("measure_pv_performance_ratio")
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name: str) -> ModuleType:
    """Run scripts/<name>.py as a module called name, without registering it in sys.modules."""
    path = _SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        pytest.fail(f"{path} cannot be loaded as a module")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script
