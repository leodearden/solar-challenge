# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_required_environment.py, the .python-version pin's environment on this host and its declaration as a uv required environment."""

import base64
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from packaging.version import Version

from tests._collect_only import requires_uv
from tests._command_runner import describe_outcome
from tests._interpreters import minor_versions_where_marker_holds, python_version_pin
from tests._pyproject import load_project_table, load_pyproject, load_uv_lock, locked_versions
from tests._required_environment import declare_required_environment, pinned_environment
from tests._uv_env import isolated_uv_env

_UPLOADING = "uploading"


def _run_uv(args: list[str], project: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["uv", *args], cwd=project, env=env, capture_output=True, text=True, timeout=120)


def _record_line(path: str, content: bytes) -> str:
    """Return the RECORD line of the wheel's file *path*, holding *content*: its path, unpadded urlsafe SHA-256 and size."""
    digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
    return f"{path},sha256={digest},{len(content)}\n"


def _write_wheel(directory: Path, name: str, version: str, tag: str) -> Path:
    """Write into *directory* a minimal wheel of *name* at *version*, tagged *tag*, holding an empty package; return its path."""
    dist_info = f"{name}-{version}.dist-info"
    files = {
        f"{name}/__init__.py": b"",
        f"{dist_info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode(),
        f"{dist_info}/WHEEL": f"Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\nTag: {tag}\n".encode(),
    }
    record = "".join(_record_line(path, content) for path, content in files.items()) + f"{dist_info}/RECORD,,\n"
    wheel = directory / f"{name}-{version}-{tag}.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
        archive.writestr(f"{dist_info}/RECORD", record)
    return wheel


def _consumer_project(directory: Path, project_root: Path, oldest: Version) -> Path:
    """Write the project *directory*, pinned by *project_root*'s .python-version, requiring _UPLOADING from Python *oldest*."""
    directory.mkdir()
    shutil.copy2(project_root / ".python-version", directory / ".python-version")
    (directory / "pyproject.toml").write_text(
        f'[project]\nname = "consumer"\nversion = "0"\nrequires-python = ">={oldest}"\n'
        f'dependencies = ["{_UPLOADING}"]\n',
        encoding="utf-8",
    )
    return directory


def _offline_find_links_env(project_environment: Path, links: Path, cache: Path, python: Version) -> dict[str, str]:
    """Return an isolated_uv_env in which uv reads only the find-links *links*, offline, with *cache* its own, on *python*.

    UV_PYTHON overrides an inherited value: the interpreter-matrix lane runs this suite with UV_PYTHON set to its own
    minor.
    """
    return {
        **isolated_uv_env(project_environment),
        "UV_OFFLINE": "1",
        "UV_NO_INDEX": "1",
        "UV_FIND_LINKS": str(links),
        "UV_CACHE_DIR": str(cache),
        "UV_PYTHON": str(python),
        "UV_PYTHON_DOWNLOADS": "never",
    }


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


@requires_uv
def test_a_lock_declaring_the_pinned_environment_installs_there_the_newest_release_with_a_wheel_for_it(
    project_root: Path, tmp_path: Path
) -> None:
    """Release 2.0 of the project's one dependency has a wheel only for the minor before the pin, the oldest the
    project's requires-python admits, as a release can while its wheels are still being uploaded; 1.0 has one for any
    Python.
    """
    pin = python_version_pin(project_root)
    oldest = Version(f"{pin.major}.{pin.minor - 1}")
    links = tmp_path / "links"
    links.mkdir()
    _write_wheel(links, _UPLOADING, "1.0", "py3-none-any")
    _write_wheel(links, _UPLOADING, "2.0", f"cp{oldest.major}{oldest.minor}-none-any")
    project = _consumer_project(tmp_path / "project", project_root, oldest)
    venv = tmp_path / "venv"
    env = _offline_find_links_env(venv, links, tmp_path / "uv-cache", pin)

    locked = _run_uv(["lock"], project, env)
    assert locked.returncode == 0, describe_outcome(locked)
    assert locked_versions(load_uv_lock(project), _UPLOADING) == (Version("2.0"),), (
        "without the declaration, uv no longer pins the release the pin cannot install, so the fixture does not "
        "reproduce a half-uploaded release and this test proves nothing"
    )

    declare_required_environment(project, pinned_environment(project))

    relocked = _run_uv(["lock"], project, env)
    assert relocked.returncode == 0, describe_outcome(relocked)
    synced = _run_uv(["sync", "--locked", "--no-install-project"], project, env)
    assert synced.returncode == 0, describe_outcome(synced)
    listed = _run_uv(["pip", "list", "--format", "json", "--python", str(venv)], project, env)
    assert listed.returncode == 0, describe_outcome(listed)
    assert {row["name"]: row["version"] for row in json.loads(listed.stdout)} == {_UPLOADING: "1.0"}


def test_the_declaration_is_valid_toml_in_this_projects_pyproject(project_root: Path, tmp_path: Path) -> None:
    """The newest-releases check, tests/newest_releases/test_verify_suite_on_newest_releases.py, appends this
    [tool.uv] table to its copy of pyproject.toml.

    A [tool.uv] table added to pyproject.toml would therefore fail here, in the per-task verify, rather than in the
    post-merge lane, and the declaration would then have to move into that table.
    """
    copy = tmp_path / "project"
    copy.mkdir()
    for name in ("pyproject.toml", ".python-version"):
        shutil.copy2(project_root / name, copy / name)
    environment = pinned_environment(copy)

    declare_required_environment(copy, environment)

    assert load_pyproject(copy)["tool"]["uv"]["required-environments"] == [str(environment)]
    assert load_project_table(copy) == load_project_table(project_root)
