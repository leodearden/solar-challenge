# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every `>>>` example in a solar_challenge docstring prints what it shows.

Each docstring's examples run as one case, as `python -m doctest` would run them,
so an example that drifts from the code fails under the name of what it documents.
This is a test, not `--doctest-modules` in addopts, because dark-factory's serial
and confirm reruns clear addopts with `-o addopts=`. Finding the examples imports
every module, the web subpackage's too, so like the web tests it needs the web extra.
"""

import doctest
import importlib
import io
import pkgutil
from types import ModuleType

import pytest

import solar_challenge

pytest.importorskip("flask")


def _package_modules() -> list[ModuleType]:
    """Return solar_challenge and every module beneath it, imported."""
    walk = pkgutil.walk_packages(solar_challenge.__path__, f"{solar_challenge.__name__}.")
    return [solar_challenge, *(importlib.import_module(info.name) for info in walk)]


def _examples_by_docstring() -> list[doctest.DocTest]:
    """Return the examples of each package docstring that has any, one DocTest per docstring."""
    finder = doctest.DocTestFinder()
    return [found for module in _package_modules() for found in finder.find(module) if found.examples]


_EXAMPLES_BY_DOCSTRING = _examples_by_docstring()


def _with_fresh_globals(collected: doctest.DocTest) -> doctest.DocTest:
    """Return `collected`'s examples over a copy of its globals, which a run clears and rebinds."""
    return doctest.DocTest(
        collected.examples,
        collected.globs,
        collected.name,
        collected.filename,
        collected.lineno,
        collected.docstring,
    )


@pytest.mark.parametrize(
    "examples", _EXAMPLES_BY_DOCSTRING, ids=[examples.name for examples in _EXAMPLES_BY_DOCSTRING]
)
def test_docstring_examples_print_what_they_show(examples: doctest.DocTest) -> None:
    """Each example in the docstring prints exactly the output written beneath it."""
    report = io.StringIO()
    fresh = _with_fresh_globals(examples)
    outcome = doctest.DocTestRunner(verbose=False).run(fresh, out=report.write)
    assert outcome.failed == 0, report.getvalue()
