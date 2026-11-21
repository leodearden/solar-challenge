# SPDX-License-Identifier: AGPL-3.0-or-later
"""The e2e conftest imports nothing from the e2e extra when it loads.

tests/unit/test_e2e_job_wait.py, tests/unit/test_e2e_network_change_reruns.py and
tests/unit/test_e2e_live_server_weather.py load copies of it in the verify environment, which lacks that extra.
"""

from pathlib import Path

import pytest

from tests._blocked_imports import extra_modules, import_with_modules_blocked

pytest.importorskip("flask")


def test_importing_the_e2e_conftest_needs_no_e2e_extra(project_root: Path) -> None:
    result = import_with_modules_blocked("tests.e2e.conftest", extra_modules(project_root, "e2e"), project_root)

    assert result.returncode == 0, f"tests.e2e.conftest needs the e2e extra when it loads:\n{result.stderr}"
