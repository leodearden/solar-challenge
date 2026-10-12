# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_job_manager_double.py, the JobManager double the web tests share."""

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import pandas as pd
import pytest

from tests._job_manager_double import autospecced_job_manager

_SUBMIT_HOME_JOB_ARGUMENTS: Mapping[str, object] = MappingProxyType({
    "config": object(),
    "start_date": pd.Timestamp("2024-06-01"),
    "end_date": pd.Timestamp("2024-06-07"),
    "db_path": "runs.db",
    "data_dir": "runs",
})


def test_importing_the_helper_needs_no_web_extra(project_root: Path) -> None:
    """The web_api conftest imports the helper when it loads, and a run without the web extra must skip those tests, not abort."""
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.modules['flask'] = None; import tests._job_manager_double"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr


def test_a_name_job_manager_lacks_raises_attribute_error() -> None:
    """get_job_status is the name JobManager.job_state replaced, so a stale test may still use it."""
    with pytest.raises(AttributeError, match="get_job_status"):
        autospecced_job_manager().get_job_status


def test_a_call_with_more_arguments_than_the_real_signature_takes_raises_type_error() -> None:
    with pytest.raises(TypeError, match="too many positional arguments"):
        autospecced_job_manager().job_state("job-1", None)


def test_a_keyword_the_real_method_lacks_raises_type_error() -> None:
    with pytest.raises(TypeError, match="run_name"):
        autospecced_job_manager().submit_home_job(**_SUBMIT_HOME_JOB_ARGUMENTS, run_name="x")


def test_the_double_cannot_be_called() -> None:
    """A JobManager instance is not callable."""
    with pytest.raises(TypeError, match="not callable"):
        autospecced_job_manager()()


def test_a_configured_method_returns_its_value_and_records_the_call() -> None:
    job_manager = autospecced_job_manager()
    job_manager.submit_home_job.return_value = ("job-1", "run-1")

    assert job_manager.submit_home_job(**_SUBMIT_HOME_JOB_ARGUMENTS) == ("job-1", "run-1")
    assert job_manager.submit_home_job.call_args.kwargs == dict(_SUBMIT_HOME_JOB_ARGUMENTS)
