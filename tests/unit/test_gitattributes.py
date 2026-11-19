# SPDX-License-Identifier: AGPL-3.0-or-later
"""Git checks out a weather-cache entry committed under tests/fixtures/weather_cache byte for byte, whatever line-ending conversion is asked for.

It does so because the entry's first line seals the SHA-256 of the exact bytes after it.
WeatherCache.get refuses an entry whose bytes no longer match, so a checkout that wrote CRLFs would leave the entry unreadable.
"""

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pandas as pd
import pytest

from solar_challenge.location import Location
from solar_challenge.weather import WeatherCache

from tests._committed_weather_cache import COMMITTED_WEATHER_CACHE_DIR
from tests._repository_paths import REPOSITORY_ROOT
from tests._synthetic_checkout import synthetic_checkout
from tests._synthetic_weather import synthetic_june_weather

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed; the weather-cache entry is checked out with it"
)

_GITATTRIBUTES = PurePosixPath(".gitattributes")
_ENTRY_DIRECTORY = COMMITTED_WEATHER_CACHE_DIR.relative_to(REPOSITORY_ROOT)


@dataclass(frozen=True)
class _CrlfRequest:
    """A way to ask git for CRLF line endings in a checkout: *name* words it, in a test's id and in its failure message, and *apply* asks for it in the checkout."""

    name: str
    apply: Callable[[Path], None]


def _git(checkout: Path, *arguments: str) -> None:
    """Run git with *arguments* in *checkout*; raise CalledProcessError if it fails."""
    subprocess.run(["git", *arguments], cwd=checkout, check=True)


def _set_core_autocrlf(checkout: Path) -> None:
    _git(checkout, "config", "core.autocrlf", "true")


def _put_an_eol_crlf_rule_ahead_of_the_repositorys(checkout: Path) -> None:
    attributes = checkout / _GITATTRIBUTES
    attributes.write_bytes(b"* text=auto eol=crlf\n" + attributes.read_bytes())


_CRLF_REQUESTS = (
    _CrlfRequest("a clone's core.autocrlf=true, the Windows default", _set_core_autocrlf),
    _CrlfRequest(
        "a '* text=auto eol=crlf' rule ahead of the repository's", _put_an_eol_crlf_rule_ahead_of_the_repositorys
    ),
)


@pytest.fixture
def checkout(project_root: Path, tmp_path: Path) -> Path:
    """Return a new hermetic git checkout holding a copy of the project's .gitattributes."""
    return synthetic_checkout(tmp_path / "checkout", {_GITATTRIBUTES: (project_root / _GITATTRIBUTES).read_bytes()})


def _restore_from_the_index(checkout: Path, file: Path) -> None:
    """Delete *file* and have git write it again from *checkout*'s index, converting its line endings as a clone's checkout does.

    It takes no commit, so it needs no user name or signing configuration.
    """
    file.unlink()
    _git(checkout, "checkout", "--", file.relative_to(checkout).as_posix())


@pytest.mark.parametrize("crlf_request", _CRLF_REQUESTS, ids=lambda crlf_request: crlf_request.name)
def test_git_checks_out_a_sealed_weather_cache_entry_byte_for_byte_under_each_request_for_crlf(
    checkout: Path, crlf_request: _CrlfRequest
) -> None:
    entry_directory = checkout / _ENTRY_DIRECTORY
    bristol = Location.bristol()
    frame = synthetic_june_weather("2024-06-21")
    WeatherCache(cache_dir=entry_directory).put(frame, "tmy", bristol)
    [entry_file] = list(entry_directory.iterdir())
    sealed_bytes = entry_file.read_bytes()
    _git(checkout, "add", "--all")

    crlf_request.apply(checkout)
    _restore_from_the_index(checkout, entry_file)

    assert entry_file.read_bytes() == sealed_bytes, (
        f"git rewrote the bytes of {entry_file.name}, a sealed weather-cache entry, under {crlf_request.name}, so"
        " WeatherCache.get would refuse it; mark tests/fixtures/weather_cache/*.csv binary in .gitattributes, so that"
        " git never rewrites the bytes the entry's seal covers"
    )
    pd.testing.assert_frame_equal(WeatherCache(cache_dir=entry_directory).get("tmy", bristol), frame)
