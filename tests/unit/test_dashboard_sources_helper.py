# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_dashboard_sources.py, which reads the dashboard's source files.

The web guards read the classes the dashboard applies through
dashboard_applied_classes_by_source, so a source it skips or misreads goes unchecked by
every guard.
"""

import pytest

pytest.importorskip("jinja2")
from tests._css_classes import applied_classes_in_script, applied_classes_in_template
from tests._dashboard_sources import (
    dashboard_applied_classes_by_source,
    dashboard_script_sources,
    dashboard_template_sources,
)


def test_applied_classes_by_source_cover_every_template_and_script_under_its_source_key() -> None:
    sources = [*dashboard_template_sources(), *dashboard_script_sources()]

    assert sorted(dashboard_applied_classes_by_source()) == sorted(sources), (
        "dashboard_applied_classes_by_source must key the classes of every dashboard template "
        "and script exactly as dashboard_template_sources and dashboard_script_sources key its "
        "source, or every web guard that reads it skips that source"
    )


def test_applied_classes_by_source_read_each_source_with_the_reader_for_its_kind() -> None:
    read_as_templates = {
        path: applied_classes_in_template(source)
        for path, source in dashboard_template_sources().items()
    }
    read_as_scripts = {
        path: applied_classes_in_script(source)
        for path, source in dashboard_script_sources().items()
    }

    assert dashboard_applied_classes_by_source() == read_as_templates | read_as_scripts, (
        "dashboard_applied_classes_by_source must read each dashboard template with "
        "applied_classes_in_template and each script with applied_classes_in_script, or every "
        "web guard that reads it sees the wrong classes for that source"
    )
