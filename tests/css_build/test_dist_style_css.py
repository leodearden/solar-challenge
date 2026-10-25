# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check that the web package's static/dist/ holds what its committed sources and locked npm packages make.

Tailwind compiles static/dist/style.css from tailwind.config.js, the
tailwind section of static/src/theme-tokens.json that it reads,
static/src/input.css, and the templates and scripts it scans.
tests/unit/test_web_compiled_css.py checks only class names, so a theme or
input edit committed without a rebuild passes it. This module rebuilds the
stylesheet in a scratch copy of the web package, with the committed
package-lock.json, and compares bytes. It also checks that a token file whose
tailwind role names no built-in Tailwind palette fails the stylesheet build,
naming the role.

build-favicon.js draws static/dist/favicon.svg, the brand sun, in the theme's
primary-500, so the browser tab's icon follows the accent. This module rebuilds
it the same way and compares bytes. It also checks that an accent token edit
redraws every mark, and that a theme without primary-500 fails the build.

Each license text beside the stylesheet is a verbatim copy of the tailwindcss
file tests/_tailwindcss_license_copies.py names. This module compares each copy
byte for byte with that file of the version package-lock.json locks, so a
Tailwind version change that leaves a copy stale fails. Every check shares one
npm ci.

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
from xml.etree import ElementTree

import pytest

from tests._tailwindcss_license_copies import TAILWINDCSS_LICENSE_COPIES

pytestmark = pytest.mark.slow

# Module-scoped fixtures cannot request the function-scoped project_root fixture.
_WEB_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "solar_challenge" / "web"

# Relative to the web package, in the checkout and in its scratch copies alike.
_DIST = Path("static", "dist")
_DIST_STYLESHEET = _DIST / "style.css"
_DIST_FAVICON = _DIST / "favicon.svg"
_THEME_TOKENS = Path("static", "src", "theme-tokens.json")
_TAILWINDCSS_PACKAGE = Path("node_modules", "tailwindcss")

# The built-in palette the recolour test names as the accent.
_RECOLOURED_ACCENT = "blue"

# Only so a hung npm or node fails the tests by name. npm ci downloads every package the lock records, while a
# run, such as a build or a palette read, only runs installed ones, so each has its own bound. npm ci's bound and
# every run's together fit inside the css-build lane job's `timeout -k 60 600` (dark-factory-orchestrator.yaml),
# whose kill would file css-build::nonzero-exit.
_NPM_CI_TIMEOUT_SECS = 240
_RUN_TIMEOUT_SECS = 40

# The most lines of a diff a failure shows.
_DIFF_LINES = 40


def _npm_run(
    args: list[str], cwd: Path, cache: Path, *, timeout_secs: float = _RUN_TIMEOUT_SECS
) -> subprocess.CompletedProcess[str]:
    """Run npm with *args* in *cwd*, with *cache* as its cache, for at most *timeout_secs*.

    Return the finished run, its output as text.
    """
    return subprocess.run(
        ["npm", *args],
        cwd=cwd,
        env={**os.environ, "npm_config_cache": str(cache)},
        capture_output=True,
        text=True,
        timeout=timeout_secs,
    )


def _npm(args: list[str], cwd: Path, cache: Path, *, timeout_secs: float = _RUN_TIMEOUT_SECS) -> None:
    """Run npm with *args* in *cwd*, with *cache* as its cache, and fail unless it succeeds within *timeout_secs*.

    npm_config_cache reaches every npm call and the npx that build:css runs, so
    nothing writes ~/.npm, which a sandboxed agent cannot write. A missing npm
    raises FileNotFoundError, which fails the tests: a skip would leave the lane
    green with static/dist unchecked.
    """
    command = shlex.join(["npm", *args])
    result = _npm_run(args, cwd, cache, timeout_secs=timeout_secs)
    assert result.returncode == 0, (
        f"`{command}` exited {result.returncode} in a scratch copy of the web package; "
        f"npm's stderr:\n{result.stderr}\nnpm's stdout:\n{result.stdout}"
    )


def _diff(committed: list[str], rebuilt: list[str]) -> str:
    """Return the first _DIFF_LINES lines of a unified diff of a committed file's pieces with its rebuild's."""
    diff = difflib.unified_diff(committed, rebuilt, "committed", "rebuilt", lineterm="", n=0)
    return "\n".join(itertools.islice(diff, _DIFF_LINES))


def _rule_diff(committed: str, rebuilt: str) -> str:
    """Return the first _DIFF_LINES lines of a diff of two stylesheets, split into rules at each '}'.

    Minified CSS is one line, so a plain diff is useless.
    """
    return _diff(committed.split("}"), rebuilt.split("}"))


def _drawn_colours(svg: Path) -> set[str]:
    """Every fill and stroke attribute value of *svg*'s elements, but "none".

    A colour set through style or CSS is not read, so such a favicon fails the recolour test rather than passing it.
    """
    return {
        colour
        for element in ElementTree.parse(svg).iter()
        for attribute in ("fill", "stroke")
        if (colour := element.get(attribute, "none")) != "none"
    }


def _built_in_palette_500(palette: str, web_package: Path) -> str:
    """Return the 500 shade of Tailwind's built-in *palette*, read from the tailwindcss installed in *web_package*."""
    command = ["node", "--print", f'require("tailwindcss/colors")[{json.dumps(palette)}][500]']
    result = subprocess.run(command, cwd=web_package, capture_output=True, text=True, timeout=_RUN_TIMEOUT_SECS)
    assert result.returncode == 0, (
        f"`{shlex.join(command)}` exited {result.returncode} in a scratch copy of the web package; "
        f"node's stderr:\n{result.stderr}"
    )
    return result.stdout.strip()


def _copy_web_package(destination: Path) -> Path:
    """Copy the checkout's web package, without its node_modules, to destination/web and return the copy."""
    # "web" is the root package name package-lock.json records, which npm takes from the directory.
    web_package = destination / "web"
    shutil.copytree(_WEB_PACKAGE, web_package, ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
    return web_package


def _build_copy(scratch_web_package: Path, destination: Path) -> Path:
    """Copy the web package to destination/web for one build, linking *scratch_web_package*'s node_modules.

    A build writes into the package it runs in, so each build gets its own copy and
    shares only the installed node_modules. Never build in the fixture's copy.
    """
    web_package = _copy_web_package(destination)
    (web_package / "node_modules").symlink_to(scratch_web_package / "node_modules")
    return web_package


@pytest.fixture(scope="module")
def scratch_web_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a scratch copy of the web package in which `npm ci` installed what package-lock.json locks.

    It is made once and shared by every test in this module, so no test writes to it.
    """
    scratch = tmp_path_factory.mktemp("css-build")
    web_package = _copy_web_package(scratch)
    _npm(["ci", "--no-audit", "--no-fund"], web_package, scratch / "npm-cache", timeout_secs=_NPM_CI_TIMEOUT_SECS)
    return web_package


def test_dist_style_css_matches_a_fresh_build_of_its_sources(scratch_web_package: Path, tmp_path: Path) -> None:
    """static/dist/style.css is byte for byte what `npm run build:css` makes of its committed sources."""
    web_package = _build_copy(scratch_web_package, tmp_path)
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
        "static/src/theme-tokens.json (its tailwind section), static/src/input.css, template or "
        "script change was committed without a rebuild. Rebuild "
        "with `cd src/solar_challenge/web && npm ci && npm run build:css` and commit "
        f"static/dist/style.css. The rules that differ:\n{_rule_diff(committed.decode(), rebuilt.decode())}"
    )


@pytest.mark.parametrize(
    ("tailwind_key", "written", "role", "name"),
    [
        pytest.param("status", {"running": "ambr"}, "status.running", "ambr", id="status-running-ambr"),
        pytest.param("warning", "black", "warning", "black", id="warning-black"),
    ],
)
def test_a_tailwind_role_naming_no_built_in_palette_fails_the_build_naming_the_role_and_the_name(
    scratch_web_package: Path, tmp_path: Path, tailwind_key: str, written: str | dict[str, str], role: str, name: str
) -> None:
    """A token file whose tailwind *role* names *name*, no built-in Tailwind palette, fails the build, naming both.

    *name* is either no Tailwind colour at all, as in a grouped role naming "ambr", or a single colour with no
    shades, such as black.
    """
    web_package = _build_copy(scratch_web_package, tmp_path)
    token_file = web_package / _THEME_TOKENS
    tokens = json.loads(token_file.read_text(encoding="utf-8"))
    tokens["tailwind"][tailwind_key] = written
    token_file.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
    stylesheet = web_package / _DIST_STYLESHEET
    stylesheet.unlink()

    result = _npm_run(["run", "build:css"], web_package, tmp_path / "npm-cache")

    assert result.returncode != 0 and f"tailwind.{role}" in result.stderr and name in result.stderr, (
        f"`npm run build:css` exited {result.returncode} for a token file whose tailwind.{role} names {name!r}, "
        "which is no built-in Tailwind palette, where it must fail naming the role and the name: Tailwind silently "
        "drops a palette it cannot resolve, and every class that names it, so tailwind.config.js must refuse such "
        f"a token file. npm's stderr:\n{result.stderr}"
    )
    assert not stylesheet.exists(), (
        f"`npm run build:css` wrote static/dist/style.css for a token file whose tailwind.{role} names {name!r}"
    )


def test_dist_favicon_svg_matches_a_fresh_build_of_its_sources(scratch_web_package: Path, tmp_path: Path) -> None:
    """static/dist/favicon.svg is byte for byte what `npm run build:favicon` draws from the committed theme."""
    web_package = _build_copy(scratch_web_package, tmp_path)
    rebuilt_favicon = web_package / _DIST_FAVICON
    # A build that stops writing the favicon must not pass by comparing the committed copy with itself.
    rebuilt_favicon.unlink(missing_ok=True)

    _npm(["run", "build:favicon"], web_package, tmp_path / "npm-cache")

    assert rebuilt_favicon.is_file(), (
        "`npm run build:favicon` no longer writes static/dist/favicon.svg, the icon base.html links"
    )
    committed = (_WEB_PACKAGE / _DIST_FAVICON).read_bytes()
    rebuilt = rebuilt_favicon.read_bytes()
    assert rebuilt == committed, (
        "static/dist/favicon.svg is not what build-favicon.js draws from the committed theme: the theme's "
        "primary palette (static/src/theme-tokens.json's tailwind.primary, through tailwind.config.js) or "
        "build-favicon.js changed without a rebuild. Rebuild with "
        "`cd src/solar_challenge/web && npm ci && npm run build:favicon` and commit static/dist/favicon.svg. "
        f"The lines that differ:\n{_diff(committed.decode().splitlines(), rebuilt.decode().splitlines())}"
    )


def test_an_accent_token_edit_redraws_every_mark_of_the_favicon_in_the_new_accent(
    scratch_web_package: Path, tmp_path: Path
) -> None:
    """Naming another built-in palette as the token file's accent draws every mark of the favicon in its 500 shade."""
    web_package = _build_copy(scratch_web_package, tmp_path)
    token_file = web_package / _THEME_TOKENS
    tokens = json.loads(token_file.read_text(encoding="utf-8"))
    assert tokens["tailwind"]["primary"] != _RECOLOURED_ACCENT, (
        f"{_THEME_TOKENS.as_posix()} already names {_RECOLOURED_ACCENT} as the accent, so this recolour would "
        "prove nothing: name another built-in palette in _RECOLOURED_ACCENT"
    )
    tokens["tailwind"]["primary"] = _RECOLOURED_ACCENT
    token_file.write_text(json.dumps(tokens, indent=2), encoding="utf-8")

    _npm(["run", "build:favicon"], web_package, tmp_path / "npm-cache")

    drawn = _drawn_colours(web_package / _DIST_FAVICON)
    accent_500 = _built_in_palette_500(_RECOLOURED_ACCENT, web_package)
    assert drawn == {accent_500}, (
        f"with {_RECOLOURED_ACCENT} as the accent, the favicon draws {sorted(drawn)}, where every mark must be "
        f"{_RECOLOURED_ACCENT}-500, {accent_500} in the installed tailwindcss: build-favicon.js must draw every "
        "mark in the theme's primary-500, so that an accent change reaches the browser tab's icon"
    )


def test_the_favicon_build_refuses_a_theme_without_primary_500(scratch_web_package: Path, tmp_path: Path) -> None:
    """A theme whose resolved colours have no primary-500 fails the favicon build, naming primary-500."""
    web_package = _build_copy(scratch_web_package, tmp_path)
    # Tailwind's default colours, which this config resolves to, have no primary palette.
    (web_package / "tailwind.config.js").write_text("module.exports = {content: [], theme: {}};\n", encoding="utf-8")
    favicon = web_package / _DIST_FAVICON
    favicon.unlink(missing_ok=True)

    result = _npm_run(["run", "build:favicon"], web_package, tmp_path / "npm-cache")

    assert result.returncode != 0 and "primary-500" in result.stderr, (
        f"`npm run build:favicon` exited {result.returncode} for a theme without primary-500, where it must fail "
        f"naming primary-500, the colour it draws the favicon in; npm's stderr:\n{result.stderr}"
    )
    assert not favicon.exists(), "`npm run build:favicon` wrote static/dist/favicon.svg for a theme without primary-500"


@pytest.mark.parametrize("license_copy", list(TAILWINDCSS_LICENSE_COPIES))
def test_dist_license_text_matches_the_locked_tailwindcss_package(scratch_web_package: Path, license_copy: str) -> None:
    """static/dist/<license_copy> is byte for byte the file it copies from the locked tailwindcss package."""
    tailwindcss = scratch_web_package / _TAILWINDCSS_PACKAGE
    version = json.loads((tailwindcss / "package.json").read_text(encoding="utf-8"))["version"]
    licensed_file = TAILWINDCSS_LICENSE_COPIES[license_copy]
    upstream = tailwindcss / licensed_file
    committed_copy = (_DIST / license_copy).as_posix()
    installed_file = (_TAILWINDCSS_PACKAGE / licensed_file).as_posix()
    assert upstream.is_file(), (
        f"tailwindcss {version}, which package-lock.json locks, installs no {installed_file}, the file "
        f"{committed_copy} copies: this version moved or dropped that license, so a plain copy cannot refresh "
        "it. Find where this version keeps the license of the code it compiles into style.css, copy that file, "
        "and update TAILWINDCSS_LICENSE_COPIES in tests/_tailwindcss_license_copies.py to name it."
    )
    assert (_WEB_PACKAGE / _DIST / license_copy).read_bytes() == upstream.read_bytes(), (
        f"{committed_copy} is not byte for byte tailwindcss {version}'s {licensed_file.as_posix()}: a Tailwind "
        "version change was committed without refreshing the license texts beside the stylesheet. Refresh it "
        f"with `cd src/solar_challenge/web && npm ci && cp {installed_file} {committed_copy}` and commit the copy."
    )
