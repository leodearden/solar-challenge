# SPDX-License-Identifier: AGPL-3.0-or-later
"""The errors leaf's refusal type, and what importing the leaf and constructing the input types cost in imports.

ConfigurationError is a ValueError, so code that catches ValueError catches every refusal.

Importing solar_challenge.errors loads no other module of the package. Constructing
the finance, grid-services, flexibility and dispatch-configuration input types, valid
or refused, loads neither the scenario grammar (solar_challenge.config) nor pvlib, and
each refuses with a ConfigurationError, as the TOU and peak-shaving strategies do.

Each import case runs in a fresh ``python -I`` interpreter, so the modules that
earlier tests imported cannot hide what the case loads.
"""

import json
import subprocess
import sys
from datetime import timedelta

import pytest

from solar_challenge.errors import ConfigurationError

_PROBE = """\
import json
import sys

import solar_challenge

try:
    exec(sys.argv[1])
except Exception as exc:
    refusal = [f"{c.__module__}.{c.__qualname__}" for c in type(exc).__mro__]
else:
    refusal = None
loaded = sorted(
    name
    for name in sys.modules
    if name in ("pvlib", "solar_challenge") or name.startswith("solar_challenge.")
)
print(json.dumps({"loaded": loaded, "refusal": refusal}))
"""

_SCENARIO_GRAMMAR_AND_PVLIB = frozenset({"solar_challenge.config", "pvlib"})


def _probe(statement: str) -> tuple[set[str], list[str] | None]:
    """Run *statement* in a fresh interpreter that has imported only solar_challenge.

    Returns the pvlib and solar_challenge modules loaded once it has run, and the
    qualified names along the MRO of the exception it raised, or None if it raised none.
    """
    result = subprocess.run(
        [sys.executable, "-I", "-c", _PROBE, statement],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, f"the probe of {statement!r} failed:\n{result.stderr}"
    report = json.loads(result.stdout)
    return set(report["loaded"]), report["refusal"]


def test_a_configuration_error_is_a_value_error() -> None:
    assert issubclass(ConfigurationError, ValueError)


@pytest.mark.parametrize(
    ("field", "requirement", "value", "message"),
    [
        pytest.param("tz", "a ZoneInfo", "Europe/London", "tz must be a ZoneInfo, got 'Europe/London'", id="text-is-quoted"),
        pytest.param(
            "duration",
            "more than 0 and at most a day",
            timedelta(0),
            "duration must be more than 0 and at most a day, got datetime.timedelta(0)",
            id="an-object-is-shown-by-repr",
        ),
    ],
)
def test_must_be_refuses_a_value_saying_what_its_field_must_be_and_what_it_got(
    field: str, requirement: str, value: object, message: str
) -> None:
    """Every refusal of one field's value takes this frame; the value is shown by repr, so text is quoted."""
    refusal = ConfigurationError.must_be(field, requirement, got=value)

    assert type(refusal) is ConfigurationError
    assert str(refusal) == message


def test_must_be_on_a_subclass_returns_that_subclass() -> None:
    class NarrowerRefusal(ConfigurationError):
        pass

    refusal = NarrowerRefusal.must_be("tz", "a ZoneInfo", got="Europe/London")

    assert type(refusal) is NarrowerRefusal


def test_importing_the_errors_module_loads_no_other_package_module() -> None:
    loaded, refusal = _probe("import solar_challenge.errors")

    assert refusal is None, f"importing solar_challenge.errors raised {refusal}"
    assert loaded == {"solar_challenge", "solar_challenge.errors"}


@pytest.mark.parametrize(
    "construction",
    [
        pytest.param("solar_challenge.FinanceConfig(standing_charge_pence_per_day=50.0)", id="FinanceConfig"),
        pytest.param("solar_challenge.GridServicesEventsConfig()", id="GridServicesEventsConfig"),
        pytest.param(
            "solar_challenge.EventWindow(months=(11, 12, 1, 2), weekdays=(0, 1, 2, 3, 4), hours=(16, 17, 18), "
            "events_per_year=12, event_hours=3.0)",
            id="EventWindow",
        ),
        pytest.param(
            "solar_challenge.GridServicesRateBand(availability_gbp_per_kw_per_event=1.0, utilisation_gbp_per_mwh=60.0)",
            id="GridServicesRateBand",
        ),
        pytest.param(
            "from solar_challenge.flex import FlexibilityValueBand; "
            "FlexibilityValueBand(name='central', time_shift_gbp=1.0, grid_services_per_home_gbp=1.0, "
            "grid_services_per_kw_gbp=1.0, total_gbp=3.0, provenance='test')",
            id="FlexibilityValueBand",
        ),
        pytest.param(
            "from solar_challenge.dispatch import GridChargeConfig; GridChargeConfig()",
            id="GridChargeConfig",
        ),
        pytest.param(
            "from solar_challenge.dispatch import TOUOptimizedStrategyConfig; "
            "TOUOptimizedStrategyConfig(peak_hours=((16, 19),))",
            id="TOUOptimizedStrategyConfig",
        ),
        pytest.param(
            "from solar_challenge.dispatch import PeakShavingStrategyConfig; "
            "PeakShavingStrategyConfig(import_limit_kw=3.0)",
            id="PeakShavingStrategyConfig",
        ),
    ],
)
def test_a_valid_construction_loads_neither_the_scenario_grammar_nor_pvlib(construction: str) -> None:
    loaded, refusal = _probe(construction)

    assert refusal is None, f"{construction} raised {refusal}"
    assert _SCENARIO_GRAMMAR_AND_PVLIB.isdisjoint(loaded), (
        f"{construction} loaded {sorted(_SCENARIO_GRAMMAR_AND_PVLIB & loaded)}"
    )


@pytest.mark.parametrize(
    "construction",
    [
        pytest.param(
            "solar_challenge.FinanceConfig(standing_charge_pence_per_day=50.0, vat_rate=2.0)",
            id="FinanceConfig",
        ),
        pytest.param("solar_challenge.GridServicesEventsConfig(band='extreme')", id="GridServicesEventsConfig"),
        pytest.param(
            "solar_challenge.EventWindow(months=(), weekdays=(0, 1, 2, 3, 4), hours=(16, 17, 18), "
            "events_per_year=12, event_hours=3.0)",
            id="EventWindow",
        ),
        pytest.param(
            "solar_challenge.GridServicesRateBand(availability_gbp_per_kw_per_event=-1.0, utilisation_gbp_per_mwh=0.0)",
            id="GridServicesRateBand",
        ),
        pytest.param(
            "from solar_challenge.flex import FlexibilityValueBand; "
            "FlexibilityValueBand(name='central', time_shift_gbp=-1.0, grid_services_per_home_gbp=1.0, "
            "grid_services_per_kw_gbp=1.0, total_gbp=3.0, provenance='test')",
            id="FlexibilityValueBand",
        ),
        pytest.param(
            "from solar_challenge.dispatch import GridChargeConfig; GridChargeConfig(1.5)",
            id="GridChargeConfig",
        ),
        pytest.param(
            "from solar_challenge.dispatch import TOUOptimizedStrategyConfig; "
            "TOUOptimizedStrategyConfig(peak_hours=((20, 17),))",
            id="TOUOptimizedStrategyConfig",
        ),
        pytest.param(
            "from solar_challenge.dispatch import PeakShavingStrategyConfig; "
            "PeakShavingStrategyConfig(import_limit_kw=0.0)",
            id="PeakShavingStrategyConfig",
        ),
        pytest.param("solar_challenge.TOUOptimizedStrategy([(25, 28)])", id="TOUOptimizedStrategy"),
        pytest.param("solar_challenge.PeakShavingStrategy(0.0)", id="PeakShavingStrategy"),
    ],
)
def test_a_refusal_is_a_configuration_error_and_loads_neither_the_scenario_grammar_nor_pvlib(
    construction: str,
) -> None:
    loaded, refusal = _probe(construction)

    assert refusal is not None and "solar_challenge.errors.ConfigurationError" in refusal, (
        f"{construction} raised {refusal}, not a ConfigurationError"
    )
    assert _SCENARIO_GRAMMAR_AND_PVLIB.isdisjoint(loaded), (
        f"{construction} loaded {sorted(_SCENARIO_GRAMMAR_AND_PVLIB & loaded)}"
    )
