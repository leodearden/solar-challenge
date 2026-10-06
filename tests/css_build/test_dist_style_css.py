# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check that the web package's static/dist/ holds what its committed sources and locked npm packages make.

Tailwind compiles static/dist/style.css from tailwind.config.js,
static/src/input.css, and the templates and scripts it scans.
tests/unit/test_web_compiled_css.py checks only class names, so a theme or
input edit committed without a rebuild passes it. This module rebuilds the
stylesheet in a scratch copy of the web package, with the committed
package-lock.json, and compares bytes.

The two license texts beside the stylesheet are verbatim copies of
tailwindcss's LICENSE and src/css/LICENSE. This module compares them byte for
byte with those files of the version package-lock.json locks, so a Tailwind
version change that leaves them stale fails. Both checks share one npm ci.

The orchestrator's offline lane runs this module after each merge to main, as
its css-build job. tests/conftest.py keeps this directory out of every default
collection, so it runs only when its path is passed explicitly. Its tests are
marked slow, the exemption from tests/conftest.py's offline guard, because npm
ci installs Tailwind from registry.npmjs.org.

Manual run::

    uv run --locked --extra dev pytest tests/css_build -p no:cacheprovider
"""

import difflib
import itertools
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

# Module-scoped fixtures cannot request the function-scoped project_root fixture.
_WEB_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "solar_challenge" / "web"

# Relative to the web package, in the checkout and in its scratch copies alike.
_DIST = Path("static", "dist")
_DIST_STYLESHEET = _DIST / "style.css"
_TAILWINDCSS_PACKAGE = Path("node_modules", "tailwindcss")

# Each license text in static/dist, beside the stylesheet tailwindcss compiles, and the package file it copies verbatim.
_TAILWINDCSS_LICENSE_COPIES: dict[str, Path] = {
    "LICENSE-tailwindcss.txt": Path("LICENSE"),
    "LICENSE-tailwindcss-preflight.txt": Path("src", "css", "LICENSE"),
}

# Only so a hung npm fails the tests by name: both npm steps' timeouts together fit inside the css-build
# lane job's `timeout` (dark-factory-orchestrator.yaml), whose kill would file css-build::nonzero-exit.
_NPM_TIMEOUT_SECS = 120

# The most lines of the rule diff a failure shows.
_DIFF_LINES = 40


def _npm(args: list[str], cwd: Path, cache: Path) -> None:
    """Run npm with *args* in *cwd*, with *cache* as its cache, and fail unless it succeeds.

    npm_config_cache reaches both npm calls and the npx that build:css runs, so
    nothing writes ~/.npm, which a sandboxed agent cannot write. A missing npm
    raises FileNotFoundError, which fails the tests: a skip would leave the lane
    green with the stylesheet and its license texts unchecked.
    """
    command = shlex.join(["npm", *args])
    result = subprocess.run(
        ["npm", *args],
        cwd=cwd,
        env={**os.environ, "npm_config_cache": str(cache)},
        capture_output=True,
        text=True,
        timeout=_NPM_TIMEOUT_SECS,
    )
    assert result.returncode == 0, (
        f"`{command}` exited {result.returncode} in a scratch copy of the web package; "
        f"npm's stderr:\n{result.stderr}\nnpm's stdout:\n{result.stdout}"
    )


def _rule_diff(committed: str, rebuilt: str) -> str:
    """Return the first _DIFF_LINES lines of a diff of two stylesheets, split into rules at each '}'.

    Minified CSS is one line, so a plain diff is useless.
    """
    diff = difflib.unified_diff(committed.split("}"), rebuilt.split("}"), "committed", "rebuilt", lineterm="", n=0)
    return "\n".join(itertools.islice(diff, _DIFF_LINES))


def _copy_web_package(destination: Path) -> Path:
    """Copy the checkout's web package, without its node_modules, to destination/web and return the copy."""
    # "web" is the root package name package-lock.json records, which npm takes from the directory.
    web_package = destination / "web"
    shutil.copytree(_WEB_PACKAGE, web_package, ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
    return web_package


@pytest.fixture(scope="module")
def scratch_web_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a scratch copy of the web package in which `npm ci` installed what package-lock.json locks.

    It is made once and shared by every test in this module, so no test writes to it.
    """
    scratch = tmp_path_factory.mktemp("css-build")
    web_package = _copy_web_package(scratch)
    _npm(["ci", "--no-audit", "--no-fund"], web_package, scratch / "npm-cache")
    return web_package


def test_dist_style_css_matches_a_fresh_build_of_its_sources(scratch_web_package: Path, tmp_path: Path) -> None:
    """static/dist/style.css is byte for byte what `npm run build:css` makes of its committed sources."""
    # The build writes into the package it runs in, so it gets its own copy; only the installed node_modules is shared.
    web_package = _copy_web_package(tmp_path)
    (web_package / "node_modules").symlink_to(scratch_web_package / "node_modules")
    rebuilt_stylesheet = web_package / _DIST_STYLESHEET
    # A build that stops writing the stylesheet must not pass by comparing the committed copy with itself.
    rebuilt_stylesheet.unlink()

    _npm(["run", "build:css"], web_package, tmp_path / "npm-cache")

    assert rebuilt_stylesheet.is_file(), (
        "`npm run build:css` no longer writes static/dist/style.css, the stylesheet base.html links"
    )
    committed = (_WEB_PACKAGE / _DIST_STYLESHEET).read_bytes()
    rebuilt = rebuilt_stylesheet.read_bytes()
    assert rebuilt == committed, (
        "static/dist/style.css is not what its sources build to: a tailwind.config.js, "
        "static/src/input.css, template or script change was committed without a rebuild. Rebuild "
        "with `cd src/solar_challenge/web && npm ci && npm run build:css` and commit "
        f"static/dist/style.css. The rules that differ:\n{_rule_diff(committed.decode(), rebuilt.decode())}"
    )


@pytest.mark.parametrize("license_copy", list(_TAILWINDCSS_LICENSE_COPIES))
def test_dist_license_text_matches_the_locked_tailwindcss_package(scratch_web_package: Path, license_copy: str) -> None:
    """static/dist/<license_copy> is byte for byte the file it copies from the locked tailwindcss package."""
    tailwindcss = scratch_web_package / _TAILWINDCSS_PACKAGE
    version = json.loads((tailwindcss / "package.json").read_text(encoding="utf-8"))["version"]
    licensed_file = _TAILWINDCSS_LICENSE_COPIES[license_copy]
    upstream = tailwindcss / licensed_file
    committed_copy = (_DIST / license_copy).as_posix()
    installed_file = (_TAILWINDCSS_PACKAGE / licensed_file).as_posix()
    assert upstream.is_file(), (
        f"tailwindcss {version}, which package-lock.json locks, installs no {installed_file}, the file "
        f"{committed_copy} copies: this version moved or dropped that license, so a plain copy cannot refresh "
        "it. Find where this version keeps the license of the code it compiles into style.css, copy that file, "
        "and update this module's _TAILWINDCSS_LICENSE_COPIES to name it."
    )
    assert (_WEB_PACKAGE / _DIST / license_copy).read_bytes() == upstream.read_bytes(), (
        f"{committed_copy} is not byte for byte tailwindcss {version}'s {licensed_file.as_posix()}: a Tailwind "
        "version change was committed without refreshing the license texts beside the stylesheet. Refresh it "
        f"with `cd src/solar_challenge/web && npm ci && cp {installed_file} {committed_copy}` and commit the copy."
    )
