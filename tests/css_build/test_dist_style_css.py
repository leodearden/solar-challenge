# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check that the web package's static/dist/style.css is what its committed sources build to.

Tailwind compiles static/dist/style.css from tailwind.config.js,
static/src/input.css, and the templates and scripts it scans.
tests/unit/test_web_compiled_css.py checks only class names, so a theme or
input edit committed without a rebuild passes it. This module rebuilds the
stylesheet in a scratch copy of the web package, with the committed
package-lock.json, and compares bytes.

The orchestrator's offline lane runs this module after each merge to main, as
its css-build job. tests/conftest.py keeps this directory out of every default
collection, so it runs only when its path is passed explicitly. Its test is
marked slow, the exemption from tests/conftest.py's offline guard, because npm
ci installs Tailwind from registry.npmjs.org.

Manual run::

    uv run --locked --extra dev pytest tests/css_build -p no:cacheprovider
"""

import difflib
import itertools
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

# Relative to the web package, in the checkout and in the scratch copy alike.
_DIST_STYLESHEET = Path("static", "dist", "style.css")

# About 30x the slowest measured npm step (npm ci from a cold cache, 4 s). It exists only so a hung
# npm fails this test by name; two such timeouts stay inside the css-build job's 600 s timeout.
_NPM_TIMEOUT_SECS = 120

# The most lines of the rule diff a failure shows.
_DIFF_LINES = 40


def _npm(args: list[str], cwd: Path, cache: Path) -> None:
    """Run npm with *args* in *cwd*, with *cache* as its cache, and fail unless it succeeds.

    npm_config_cache reaches both npm calls and the npx that build:css runs, so
    nothing writes ~/.npm, which a sandboxed agent cannot write. A missing npm
    raises FileNotFoundError and fails the test: a skip would leave the lane
    green with the stylesheet unchecked.
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
        f"`{command}` exited {result.returncode}, so static/dist/style.css could not be rebuilt; "
        f"npm's stderr:\n{result.stderr}\nnpm's stdout:\n{result.stdout}"
    )


def _rule_diff(committed: str, rebuilt: str) -> str:
    """Return the first _DIFF_LINES lines of a diff of two stylesheets, split into rules at each '}'.

    Minified CSS is one line, so a plain diff is useless.
    """
    diff = difflib.unified_diff(committed.split("}"), rebuilt.split("}"), "committed", "rebuilt", lineterm="", n=0)
    return "\n".join(itertools.islice(diff, _DIFF_LINES))


def test_dist_style_css_matches_a_fresh_build_of_its_sources(project_root: Path, tmp_path: Path) -> None:
    """static/dist/style.css is byte for byte what `npm run build:css` makes of its committed sources."""
    web_dir = project_root / "src" / "solar_challenge" / "web"
    # "web" is the root package name package-lock.json records, which npm takes from the directory.
    build_dir = tmp_path / "web"
    shutil.copytree(web_dir, build_dir, ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
    # A build that stops writing the stylesheet must not pass by comparing the committed copy with itself.
    (build_dir / _DIST_STYLESHEET).unlink()
    npm_cache = tmp_path / "npm-cache"

    _npm(["ci", "--no-audit", "--no-fund"], build_dir, npm_cache)
    _npm(["run", "build:css"], build_dir, npm_cache)

    rebuilt_stylesheet = build_dir / _DIST_STYLESHEET
    assert rebuilt_stylesheet.is_file(), (
        "`npm run build:css` no longer writes static/dist/style.css, the stylesheet base.html links"
    )
    committed = (web_dir / _DIST_STYLESHEET).read_bytes()
    rebuilt = rebuilt_stylesheet.read_bytes()
    assert rebuilt == committed, (
        "static/dist/style.css is not what its sources build to: a tailwind.config.js, "
        "static/src/input.css, template or script change was committed without a rebuild. Rebuild "
        "with `cd src/solar_challenge/web && npm ci && npm run build:css` and commit "
        f"static/dist/style.css. The rules that differ:\n{_rule_diff(committed.decode(), rebuilt.decode())}"
    )
