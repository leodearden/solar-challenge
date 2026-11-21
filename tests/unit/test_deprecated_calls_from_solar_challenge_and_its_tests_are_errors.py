# SPDX-License-Identifier: AGPL-3.0-or-later
"""A deprecated call made from solar_challenge or from the test suite's own modules fails the test that meets it; one made from a dependency stays a warning.

pyproject.toml's filterwarnings turns every DeprecationWarning attributed to a
solar_challenge module, or to one of the test suite's own modules, into an
error, in each run that reads its pytest ini. Libraries such as pandas
attribute a deprecation to the frame that made the deprecated call, so a call
solar_challenge makes fails the first run whose release deprecates it, not a
run on the release that removes it. The newest-releases lane runs on the
newest releases pyproject's ranges admit, so it fails at, and names, each such
call before uv.lock reaches that release. weather.py's read_csv
float_precision, which pandas 3.1 deprecated, was one.

The suite's helpers, conftests and test modules are named tests.<...>, since
tests/ is a package (tests/__init__.py), and they make the same pandas calls
solar_challenge does: tests._synthetic_weather builds the weather frames. So a
deprecated call there fails the newest-releases lane at the release that
deprecates it too, not at the one that removes it. A test that means to make a
deprecated call wraps it in pytest.deprecated_call(), which records the
warning instead of raising it.

A dependency's own deprecated calls, such as pvlib's tools.py on pandas 3.1,
are not this project's to fix, so they stay warnings. The filter's module field
is a regular expression the warnings module matches at the start of the
attributed module's name, with two alternatives. The first, solar_challenge,
matches every name that begins with it: the package's modules, and the
collection-report plugin, which tests/_collect_only.py loads by its own
top-level name, solar_challenge_collection_report. The second, tests, must be
followed by a dot or by the name's end, so it matches the suite's package and
its modules but not a dependency whose name merely begins with "tests", such
as testscenarios. The field is a TOML literal string, in single quotes, since a
basic string rejects the backslash before that dot.

The filter names the builtin DeprecationWarning, which pandas' Pandas4Warning
subclasses, not a pandas class. A filter naming a class its module lacks stops
pytest at startup, and naming a pandas class would import pandas in every
session that applies the filters, collect-only probes included.
"""

import warnings

import pytest

from tests._collect_only import COLLECTION_REPORT_PLUGIN

_DEPRECATION = "a call a later release removes"


@pytest.mark.parametrize(
    ("module", "filename"),
    [
        pytest.param("solar_challenge.weather", "weather.py", id="solar_challenge"),
        pytest.param("tests._synthetic_weather", "_synthetic_weather.py", id="tests"),
        pytest.param("tests", "__init__.py", id="tests-package"),
        pytest.param(COLLECTION_REPORT_PLUGIN, f"{COLLECTION_REPORT_PLUGIN}.py", id="collection-report-plugin"),
    ],
)
def test_a_deprecation_warning_attributed_to_solar_challenge_or_its_test_suite_fails_the_test_that_meets_it(
    module: str, filename: str
) -> None:
    """A DeprecationWarning attributed to a solar_challenge module, or to one of the suite's own modules, a tests.* module, the tests package or the collection-report plugin, is raised as an error, not recorded."""
    with pytest.raises(DeprecationWarning, match=_DEPRECATION):
        warnings.warn_explicit(_DEPRECATION, DeprecationWarning, filename, 1, module=module)


@pytest.mark.parametrize(
    ("module", "filename"),
    [
        pytest.param("pvlib.tools", "tools.py", id="pvlib"),
        pytest.param("testscenarios", "__init__.py", id="a-name-that-begins-with-tests"),
    ],
)
def test_a_deprecation_warning_attributed_to_a_dependency_is_recorded_not_raised(module: str, filename: str) -> None:
    """A DeprecationWarning attributed to a dependency's module is recorded as a warning, not raised.

    A dependency whose name merely begins with "tests", such as testscenarios,
    is a dependency too. It is recorded under the filters the test runs with:
    pytest.warns would set them to always, hiding the error filter.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.warn_explicit(_DEPRECATION, DeprecationWarning, filename, 1, module=module)

    assert [str(warning.message) for warning in caught] == [_DEPRECATION]
