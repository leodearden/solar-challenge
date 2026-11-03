# SPDX-License-Identifier: AGPL-3.0-or-later
"""The .python-version pin's environment on this host, and its declaration as a uv required environment.

uv locks universally. For a release with no source distribution, it asks only for
a wheel for the oldest Python requires-python admits, on any platform. So a release
whose wheels are still being uploaded can be locked though it has no wheel yet for
the pin on this host, and a sync of that lock here then fails. Declared as a uv
required environment in the project's pyproject.toml, the pinned environment makes
uv fork such a release: the pin on this host gets the newest release with a wheel
for it, and every other environment keeps the newest. The environment names the
Python minor as well as the OS and machine, because a wheel for another minor on
this platform would satisfy an OS and machine alone.

Two windows stay open. uv assumes a source distribution builds anywhere, so a
release whose sdist reaches the index before its wheel for the pin is still
pinned; and markers cannot tell glibc from musl, or one glibc floor from another.

Usage::

    from tests._required_environment import declare_required_environment, pinned_environment

    declare_required_environment(project, pinned_environment(project))
"""

import json
from pathlib import Path

from packaging.markers import Marker, default_environment

from tests._interpreters import python_version_pin


def pinned_environment(project_root: Path) -> Marker:
    """Return the environment the project's uv commands install into on this host: its .python-version pin's minor on this host's OS and machine."""
    pin = python_version_pin(project_root)
    host = default_environment()
    return Marker(
        f"python_version == '{pin.major}.{pin.minor}' and sys_platform == '{host['sys_platform']}' "
        f"and platform_machine == '{host['platform_machine']}'"
    )


def declare_required_environment(project: Path, environment: Marker) -> None:
    """Append to *project*'s pyproject.toml a [tool.uv] table declaring *environment* its uv required environment, so `uv lock` pins for that environment only releases with a wheel for it wherever a release has no source distribution."""
    with (project / "pyproject.toml").open("a", encoding="utf-8") as pyproject:
        pyproject.write(f"\n[tool.uv]\nrequired-environments = [{json.dumps(str(environment))}]\n")
