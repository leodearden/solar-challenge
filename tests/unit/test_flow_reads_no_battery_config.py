# SPDX-License-Identifier: AGPL-3.0-or-later
"""flow.py reads a battery only through the Battery's own answers, never through its BatteryConfig.

So flow.py's code accesses no attribute named config. Of flow.py's inputs, the pandas Series, the Battery, the
TariffConfig and the DispatchStrategy, only a Battery has one, so the scan finds a battery.config read however the
battery is reached, an alias or another object's attribute included
(docs/prds/dispatch-configuration-below-config.md §4, step 3).
"""

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

_FLOW_PY = Path(__file__).resolve().parents[2] / "src" / "solar_challenge" / "flow.py"


@dataclass(frozen=True)
class _ConfigAccess:
    """One access of an attribute named config: its line, and the expression that accesses it, as source."""

    line: int
    expression: str


def _config_accesses(source: str) -> list[_ConfigAccess]:
    """Every access of an attribute named config in the Python *source*, in line order."""
    accesses = [
        _ConfigAccess(node.lineno, ast.unparse(node))
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr == "config"
    ]
    return sorted(accesses, key=lambda access: access.line)


def test_flow_py_accesses_no_attribute_named_config() -> None:
    accesses = _config_accesses(_FLOW_PY.read_text(encoding="utf-8"))

    sites = "\n".join(f"flow.py:{access.line} accesses {access.expression}" for access in accesses)
    assert accesses == [], (
        f"flow.py reads a battery only through the Battery's own answers, and these lines access a config:\n{sites}\n"
        "Read the Battery property that answers the question instead, adding one to battery.py if none does"
    )


@pytest.mark.parametrize(
    ("source", "access"),
    [
        pytest.param("battery.config.max_charge_kw\n", _ConfigAccess(1, "battery.config"), id="battery-config"),
        pytest.param("b = battery\nb.config.grid_charging\n", _ConfigAccess(2, "b.config"), id="alias"),
        pytest.param(
            "self.battery.config.capacity_kwh\n", _ConfigAccess(1, "self.battery.config"), id="another-object-s-attribute"
        ),
    ],
)
def test_an_access_of_config_is_reported_by_its_line_and_expression(source: str, access: _ConfigAccess) -> None:
    assert _config_accesses(source) == [access]


def test_the_battery_s_answers_are_not_reported() -> None:
    source = (
        "battery.grid_charge_target_kwh\n"
        "battery.max_charge_kw\n"
        "battery.effective_capacity_kwh\n"
        "battery.charge(1.0, 1.0)\n"
    )

    assert _config_accesses(source) == []
