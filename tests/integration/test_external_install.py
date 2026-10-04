# SPDX-License-Identifier: AGPL-3.0-or-later
"""External-consumer boundary tests (H1 + H6).

These tests prove that an EXTERNAL consumer can:
  - Install the solar_challenge wheel into a project-free environment (H6).
  - Import every symbol in the frozen public surface (solar_challenge.__all__)
    and have each one resolve (H1); non-class/non-routine symbols are confirmed
    non-None (constants present).
  - Confirm the wheel ships solar_challenge/py.typed (PEP 561).
  - Confirm the wheel ships every file under solar_challenge/web/templates and
    solar_challenge/web/static, which the dashboard renders and serves.
  - Confirm the wheel's METADATA names its licenses by the PEP 639
    License-Expression AGPL-3.0-or-later AND MIT.

The wheel is built once, from a copy of the working tree (wheel_source), via a
module-scoped fixture shared by every test here.
The consumer-side proof runs inside an isolated uv env via _external_probe.py,
which is NOT collected by pytest (underscore-prefixed, matches _helpers.py).
Both uv commands run offline, reading everything they need from uv's cache.

Marked ``build`` (NOT ``slow``) to stay independently selectable
(``pytest -m build``).  Note: the project's default ``addopts`` does not
deselect ``build``, so a plain ``pytest`` run will execute these heavy tests
(timeouts: 300 s build + 600 s isolated install).  Tests skip automatically
when ``git`` or ``uv`` is absent from PATH, or when the tree is not a git checkout.
"""

from __future__ import annotations

import email
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

# Module-scoped fixtures cannot request the function-scoped project_root fixture.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EXTERNAL_PROBE = PROJECT_ROOT / "tests" / "integration" / "_external_probe.py"


def _offline_uv_environment(**overrides: str) -> dict[str, str]:
    """Return the environment of every uv command this module runs: this process's, with uv offline, then *overrides*.

    Offline, uv reads the package index, the build backend and the wheels from its
    cache alone. The offline guard (tests/conftest.py) refuses the network access of
    a test not marked slow, its child processes' included, and built_wheel's build
    runs in the window of the module's first test.
    """
    return {**os.environ, "UV_OFFLINE": "1", **overrides}


# ---------------------------------------------------------------------------
# Module-scoped shared fixtures: one copy of the working tree, one wheel build.
# ---------------------------------------------------------------------------


def _skip_unless_a_clean_wheel_can_be_built() -> None:
    """Skip unless git is on PATH with a checkout to list, and uv is on PATH to build the copy."""
    for tool in ("git", "uv"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not available on PATH — skipping build-marker tests")
    work_tree_check = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if work_tree_check.returncode != 0:
        pytest.skip(
            f"git does not recognise {PROJECT_ROOT} as a checkout, so it cannot list the files to "
            f"build the wheel from: {work_tree_check.stderr.strip()}"
        )


@pytest.fixture(scope="module")
def wheel_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a copy of what a fresh clone plus uncommitted new files would hold.

    The wheel is built from it because a build in the checkout reuses the ignored build/ and
    src/solar_challenge.egg-info, whose stale entries setuptools keeps shipping after pyproject
    stops declaring them.
    """
    _skip_unless_a_clean_wheel_can_be_built()
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    copy_root = tmp_path_factory.mktemp("wheel_source")
    for relative_path in filter(None, listing.stdout.split("\0")):
        source = PROJECT_ROOT / relative_path
        if source.is_file():
            destination = copy_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    return copy_root


def _build_wheel(source: Path, out_dir: Path, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    """Build a wheel of the project in *source* into *out_dir* with uv, its environment overridden by *env_overrides*."""
    return subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=str(source),
        capture_output=True,
        text=True,
        timeout=300,
        env=_offline_uv_environment(**env_overrides),
    )


@pytest.fixture(scope="module")
def built_wheel(wheel_source: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the solar_challenge wheel once, from the wheel_source copy, and return its path.

    The build and its output both stay under tmp, so the checkout gains no build/,
    egg-info or dist/.
    """
    out_dir = tmp_path_factory.mktemp("wheel_out")

    result = _build_wheel(wheel_source, out_dir)
    assert result.returncode == 0, (
        f"uv build --wheel failed (returncode={result.returncode}). If uv says the network is disabled, "
        "its cache lacks the build backend: run `uv build --wheel --out-dir <a temporary directory>` once "
        "in the checkout, with network access. In a verify, the outer `uv run`'s editable build fills "
        "that cache first.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    wheels = sorted(out_dir.glob("*.whl"))
    assert len(wheels) == 1, (
        f"Expected exactly one .whl file in {out_dir}, got: {wheels}\n"
        f"uv stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    return wheels[0]


# ---------------------------------------------------------------------------
# H6: wheel ships py.typed (pairs with T1)
# ---------------------------------------------------------------------------


@pytest.mark.build
def test_built_wheel_is_typed(built_wheel: Path) -> None:
    """The built wheel ZIP archive must contain solar_challenge/py.typed (PEP 561 / H6).

    This pairs with T1 (task 77) which landed py.typed in the source tree and
    wired it into pyproject.toml's package-data.  This boundary test confirms
    the packaging contract survives the build step: an external consumer running
    ``pip install solar_challenge`` will get the py.typed marker and be able to
    enable ``--check-untyped-defs`` for this library.
    """
    with zipfile.ZipFile(built_wheel) as zf:
        names = zf.namelist()

    assert "solar_challenge/py.typed" in names, (
        "The built wheel does not contain solar_challenge/py.typed.\n"
        "Ensure src/solar_challenge/py.typed exists (empty file, PEP 561)\n"
        "and that pyproject.toml has:\n\n"
        "    [tool.setuptools.package-data]\n"
        '    solar_challenge = ["py.typed"]\n\n'
        f"Wheel members:\n" + "\n".join(f"  {n}" for n in sorted(names))
    )


# ---------------------------------------------------------------------------
# Dashboard assets: the wheel ships every file create_app renders or serves
# ---------------------------------------------------------------------------


@pytest.mark.build
@pytest.mark.parametrize("folder", ["templates", "static"])
def test_built_wheel_ships_every_file_of_the_dashboard_folder(
    folder: str, wheel_source: Path, built_wheel: Path
) -> None:
    """create_app renders pages from web/templates and serves web/static, both resolved beside
    web/app.py, so a wheel without them fails every page with TemplateNotFound.
    """
    package_root = wheel_source / "src"
    in_source = sorted(
        path.relative_to(package_root).as_posix()
        for path in (package_root / "solar_challenge" / "web" / folder).rglob("*")
        if path.is_file()
    )
    assert in_source, (
        f"found no files under src/solar_challenge/web/{folder} in the copy of the working tree, "
        "so this test would pass vacuously"
    )

    with zipfile.ZipFile(built_wheel) as zf:
        members = set(zf.namelist())
    missing = [name for name in in_source if name not in members]

    listing = "".join(f"\n  {name}" for name in missing)
    assert missing == [], (
        f"The built wheel lacks these dashboard files, so a wheel install cannot render or "
        f"serve them:{listing}\n"
        'Ship them with a pattern under [tool.setuptools.package-data] "solar_challenge.web" '
        "in pyproject.toml. setuptools' globs skip names starting with \".\", so a dot-file "
        "needs its own pattern."
    )


# ---------------------------------------------------------------------------
# License: the wheel names its licenses by a PEP 639 SPDX expression
# ---------------------------------------------------------------------------


def _metadata_member(wheel: zipfile.ZipFile) -> str:
    """Return the name of the one .dist-info/METADATA member of the open *wheel*."""
    [metadata_member] = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
    return metadata_member


def _wheel_metadata(wheel: zipfile.ZipFile) -> email.message.Message:
    """Return the core metadata of the open *wheel*, parsed from its METADATA member's email-header format."""
    return email.message_from_bytes(wheel.read(_metadata_member(wheel)))


@pytest.mark.build
def test_built_wheel_declares_the_agpl_and_mit_license_expression(built_wheel: Path) -> None:
    """Installers, PyPI and license scanners read a wheel's license from its METADATA, where
    PEP 639 makes License-Expression the field that names it.

    The project's own code is AGPL-3.0-or-later. The third-party code the dashboard bundles is
    MIT-licensed: the scripts vendored under web/static/vendor/, and Tailwind's preflight compiled
    into static/dist/style.css. AND says both apply.
    """
    with zipfile.ZipFile(built_wheel) as wheel:
        metadata = _wheel_metadata(wheel)

    expressions = metadata.get_all("License-Expression")
    assert expressions == ["AGPL-3.0-or-later AND MIT"], (
        f"The built wheel's METADATA carries License-Expression {expressions} and the legacy "
        f"License {metadata.get_all('License')}, so it does not name its licenses by the PEP 639 "
        "SPDX expression AGPL-3.0-or-later AND MIT. Declare [project] "
        'license = "AGPL-3.0-or-later AND MIT" in pyproject.toml: an SPDX expression string, '
        "not a TOML table."
    )


# ---------------------------------------------------------------------------
# H1: every public symbol resolves and is callable/present in an isolated install
# ---------------------------------------------------------------------------


def _run_isolated_install(wheel: Path, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    """Run _external_probe.py in a project-free uv environment holding *wheel*, its environment overridden by *env_overrides*."""
    return subprocess.run(
        ["uv", "run", "--no-project", "--isolated", "--with", str(wheel), "python", str(_EXTERNAL_PROBE)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=600,
        env=_offline_uv_environment(**env_overrides),
    )


@pytest.mark.build
def test_isolated_install_resolves_and_calls_every_symbol(built_wheel: Path) -> None:
    """Install the wheel in a project-free env and resolve every __all__ symbol (H1).

    Runs tests/integration/_external_probe.py inside a ``uv run --no-project
    --isolated --with <wheel>`` environment.  The probe:
      - Asserts the package loaded from site-packages (not the worktree src/).
      - Iterates solar_challenge.__all__ and getattr-resolves each name.
      - Classifies: classes/routines → resolution is the assertion (callable() is
        always True for them by the Python data model, so it is intentionally
        omitted); else → assert not None (constant present).
      - Prints ``EXTERNAL-INSTALL-OK n/n`` and exits 0 on success.

    The test asserts returncode==0 AND the sentinel is in stdout.
    stdout+stderr are embedded in the failure message for debuggability.

    Design: ``--no-project --isolated`` gives a project-free ephemeral env
    (ignores the worktree's pyproject and venv); ``--with <wheel>`` installs
    the built wheel, and uv resolves and installs its declared deps offline,
    from its cache alone.
    """
    result = _run_isolated_install(built_wheel)

    assert result.returncode == 0 and "EXTERNAL-INSTALL-OK" in result.stdout, (
        f"External-consumer boundary test FAILED.\n"
        f"returncode: {result.returncode}\n"
        "If uv says packages were unavailable because the network was disabled, its cache lacks what "
        f"this resolution reads: run `uv run --no-project --isolated --with {built_wheel} python "
        "tests/integration/_external_probe.py` once in the checkout, with network access. Any wheel "
        "built from this tree serves.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Offline: each uv command reads the package index, the build backend and the
# wheels from uv's cache alone, so an empty cache fails it
# ---------------------------------------------------------------------------


@pytest.mark.build
def test_the_wheel_build_reads_its_build_backend_only_from_uv_s_cache(wheel_source: Path, tmp_path: Path) -> None:
    """uv build exits 2 offline and when refused alike; the offline guard tells them apart, failing this test if the build reached the network."""
    result = _build_wheel(wheel_source, tmp_path / "wheel", UV_CACHE_DIR=str(tmp_path / "empty-uv-cache"))

    assert result.returncode != 0, (
        "uv build succeeded with an empty cache, so it found setuptools outside uv's cache\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@pytest.mark.build
def test_the_isolated_install_resolves_from_uv_s_cache_alone(built_wheel: Path, tmp_path: Path) -> None:
    """With an empty cache, the isolated install fails; the offline guard, not uv's exit code, catches a fetch, failing this test if the install reached the network."""
    result = _run_isolated_install(built_wheel, UV_CACHE_DIR=str(tmp_path / "empty-uv-cache"))

    assert result.returncode != 0, (
        "the isolated install succeeded with an empty cache, so it found the wheel's dependencies outside uv's cache\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
