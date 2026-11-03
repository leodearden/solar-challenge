# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_required_environment.py, the .python-version pin's environment on this host and its declaration as a uv required environment."""

from pathlib import Path

import pytest

from tests._interpreters import minor_versions_where_marker_holds, python_version_pin
from tests._required_environment import pinned_environment


def test_the_pinned_environment_holds_on_the_pins_minor_alone(project_root: Path) -> None:
    pin = python_version_pin(project_root)

    assert minor_versions_where_marker_holds(pinned_environment(project_root)) == {(pin.major, pin.minor)}


@pytest.mark.parametrize(
    ("variable", "other_value"), [("sys_platform", "not-this-os"), ("platform_machine", "not-this-machine")]
)
def test_the_pinned_environment_holds_on_this_hosts_os_and_machine_alone(
    project_root: Path, variable: str, other_value: str
) -> None:
    """packaging fills each variable an evaluated environment leaves out with this host's value."""
    pin = python_version_pin(project_root)
    marker = pinned_environment(project_root)
    on_the_pin = {"python_version": f"{pin.major}.{pin.minor}", "python_full_version": f"{pin.major}.{pin.minor}.0"}

    assert marker.evaluate(on_the_pin)
    assert not marker.evaluate({**on_the_pin, variable: other_value})
