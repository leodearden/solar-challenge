# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rule every module of this package follows; the package's __init__ docstring says why."""

import pathlib


def test_no_module_of_this_package_sits_beside_family_modules_that_extend_its_name() -> None:
    names = sorted(path.stem for path in pathlib.Path(__file__).parent.glob("test_*.py"))
    beside = [
        f"{name}.py beside {other}.py" for name in names for other in names if other.startswith(f"{name}_")
    ]

    assert beside == []
