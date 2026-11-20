# SPDX-License-Identifier: AGPL-3.0-or-later
"""A deprecated call made from solar_challenge fails the test that meets it; one made from a dependency stays a warning.

pyproject.toml's filterwarnings turns every DeprecationWarning attributed to a
solar_challenge module into an error, in each run that reads its pytest ini.
Libraries such as pandas attribute a deprecation to the frame that made the
deprecated call, so a call solar_challenge makes fails the first run whose
release deprecates it, not a run on the release that removes it. The
newest-releases lane runs on the newest releases pyproject's ranges admit, so
it fails at, and names, each such call before uv.lock reaches that release.
weather.py's read_csv float_precision, which pandas 3.1 deprecated, was one.

A dependency's own deprecated calls, such as pvlib's tools.py on pandas 3.1,
are not this project's to fix. The filter's module field is a regular
expression matched at the start of the attributed module's name, and it names
solar_challenge alone, so those calls stay warnings.

The filter names the builtin DeprecationWarning, which pandas' Pandas4Warning
subclasses, not a pandas class. A filter naming a class its module lacks stops
pytest at startup, and naming a pandas class would import pandas in every
session that applies the filters, collect-only probes included.
"""

import warnings

import pytest

_DEPRECATION = "a call a later release removes"


def test_a_deprecation_warning_attributed_to_a_solar_challenge_module_fails_the_test_that_meets_it() -> None:
    """A DeprecationWarning attributed to a solar_challenge module is raised as an error, not recorded."""
    with pytest.raises(DeprecationWarning, match=_DEPRECATION):
        warnings.warn_explicit(_DEPRECATION, DeprecationWarning, "weather.py", 1, module="solar_challenge.weather")


def test_a_deprecation_warning_attributed_to_a_dependency_is_recorded_not_raised() -> None:
    """A DeprecationWarning attributed to a dependency's module is recorded as a warning, not raised.

    It is recorded under the filters the test runs with: pytest.warns would set
    them to always, hiding the error filter.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.warn_explicit(_DEPRECATION, DeprecationWarning, "tools.py", 216, module="pvlib.tools")

    assert [str(warning.message) for warning in caught] == [_DEPRECATION]
