# SPDX-License-Identifier: AGPL-3.0-or-later
"""pyproject.toml's mypy ignore_missing_imports override lists only packages that ship no types of their own.

docs/type-check.md §1 states the rule: mypy reads the types a package ships whether it is listed or not, so listing it
changes nothing. The check reads the environment pytest runs in, through sys.path.

A listed package that is not installed passes. mypy then finds no module at all and reports import-not-found, which
ignore_missing_imports also silences, so the entry is still needed there. plotly, which only the web extra installs,
is such a package wherever that extra is not installed.

The check looks for the markers through which mypy reads a package's own types; it does not run mypy. It looks at an
entry's top-level package only, so for an entry inside a namespace package, such as google.protobuf.*, it misses
google/protobuf/py.typed and counts a google-stubs directory whichever sub-packages it holds. A NAME-stubs directory
counts even when its py.typed marks it partial, though mypy then reads the modules it omits as untyped.
"""

import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from tests._pyproject import load_pyproject
from tests._repository_paths import REPOSITORY_ROOT


def _untyped_override_entries(pyproject: Mapping[str, Any]) -> list[str]:
    """Return the module entries, as written, of the [[tool.mypy.overrides]] tables that set ignore_missing_imports.

    mypy reads a table's module as one pattern or a list of them, so a string is one entry.
    """
    overrides = pyproject["tool"]["mypy"].get("overrides", [])
    modules = [table["module"] for table in overrides if table.get("ignore_missing_imports", False)]
    return [entry for module in modules for entry in ([module] if isinstance(module, str) else list(module))]


def _typing_markers(package: str, search_dirs: Iterable[Path]) -> list[Path]:
    """Return each <dir>/*package*/py.typed and <dir>/*package*-stubs that exists, taking *search_dirs* in order.

    These are the PEP 561 markers through which mypy reads a package's own types. The stubs are looked up as a
    NAME-stubs directory, whatever the distribution that installs it is called: types-PyYAML installs yaml-stubs.
    """
    return [
        marker
        for directory in search_dirs
        for marker in (directory / package / "py.typed", directory / f"{package}-stubs")
        if marker.exists()
    ]


def _assert_names_an_untyped_package(entry: str, search_dirs: Sequence[Path]) -> None:
    """Fail, naming each marker found, if the top-level package of override *entry* ships types in *search_dirs*."""
    package = entry.split(".", 1)[0]
    markers = _typing_markers(package, search_dirs)
    assert not markers, (
        f"pyproject.toml's mypy ignore_missing_imports override lists {entry!r}, but {package} ships its own types in "
        f"this environment: {', '.join(map(str, markers))}. mypy reads them whether it is listed or not "
        f"(docs/type-check.md §1), so the entry changes nothing: drop {entry!r} from that override's module list."
    )


@pytest.mark.parametrize(
    "entry", [pytest.param(entry, id=entry) for entry in _untyped_override_entries(load_pyproject(REPOSITORY_ROOT))]
)
def test_each_listed_package_ships_no_types(entry: str) -> None:
    """The listed package has no py.typed and no NAME-stubs in the environment pytest runs in.

    In the verify that is the locked dev+web environment. tests/_newest_releases_deselections.py names this test for
    the newest-releases check to deselect, because the override answers for the releases uv.lock pins, and the check's
    copy installs newer ones. tests/unit/test_newest_releases_lane.py fails until a rename of this test renames that
    entry too, and while another test of this module begins with this test's name.
    """
    _assert_names_an_untyped_package(entry, [Path(path) for path in sys.path])


def _site_packages(directory: Path, files: Iterable[str]) -> Path:
    """Make *directory* a site-packages tree holding each of *files*, empty, at its path relative to it; return it."""
    directory.mkdir(parents=True)
    for file in files:
        (directory / file).parent.mkdir(parents=True, exist_ok=True)
        (directory / file).write_text("", encoding="utf-8")
    return directory


@pytest.mark.parametrize(
    ("files", "entry", "marker"),
    [
        pytest.param(("pkg/__init__.py", "pkg/py.typed"), "pkg.*", "pkg/py.typed", id="py.typed"),
        pytest.param(("pkg/__init__.py", "pkg-stubs/__init__.pyi"), "pkg", "pkg-stubs", id="stubs"),
        pytest.param(
            ("pkg/__init__.py", "pkg/py.typed", "pkg/sub/__init__.py"),
            "pkg.sub.*",
            "pkg/py.typed",
            id="sub-package-entry",
        ),
    ],
)
def test_a_listed_package_that_ships_types_fails_naming_its_entry_and_marker(
    tmp_path: Path, files: tuple[str, ...], entry: str, marker: str
) -> None:
    site = _site_packages(tmp_path / "site", files)

    with pytest.raises(AssertionError) as failure:
        _assert_names_an_untyped_package(entry, [site])

    message = str(failure.value)
    assert entry in message
    assert str(site / marker) in message


def test_stubs_in_another_search_dir_than_the_packages_fail_naming_that_dir(tmp_path: Path) -> None:
    site_a = _site_packages(tmp_path / "site_a", ["pkg/__init__.py"])
    site_b = _site_packages(tmp_path / "site_b", ["pkg-stubs/__init__.pyi"])

    with pytest.raises(AssertionError) as failure:
        _assert_names_an_untyped_package("pkg", [site_a, site_b])

    assert str(site_b / "pkg-stubs") in str(failure.value)


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(("pkg/__init__.py",), id="untyped"),
        pytest.param((), id="not-installed"),
        pytest.param(("other/py.typed", "pkgx-stubs/__init__.pyi"), id="markers-of-other-names-only"),
    ],
)
def test_a_listed_package_that_ships_no_types_passes(tmp_path: Path, files: tuple[str, ...]) -> None:
    site = _site_packages(tmp_path / "site", files)

    _assert_names_an_untyped_package("pkg.*", [site])


@pytest.mark.parametrize(
    ("pyproject", "entries"),
    [
        pytest.param(
            {
                "tool": {
                    "mypy": {
                        "strict": True,
                        "overrides": [
                            {"module": ["a.*", "b"], "ignore_missing_imports": True},
                            {"module": ["web.*"], "disallow_untyped_decorators": False},
                            {"module": "c.*", "ignore_missing_imports": True},
                            {"module": ["d"], "ignore_missing_imports": False},
                        ],
                    }
                }
            },
            ["a.*", "b", "c.*"],
            id="overrides",
        ),
        pytest.param({"tool": {"mypy": {"strict": True}}}, [], id="no-overrides"),
    ],
)
def test_the_entries_read_are_those_of_the_override_tables_that_ignore_missing_imports(
    pyproject: dict[str, Any], entries: list[str]
) -> None:
    assert _untyped_override_entries(pyproject) == entries
