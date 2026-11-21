# SPDX-License-Identifier: AGPL-3.0-or-later
"""A throwaway project whose one offline-lane job, PROBE_JOB, runs a given command, for tests of the lane collection probes.

It writes the dark-factory-orchestrator.yaml git.offline_lane_commands entry
that tests/_orchestrator_config.py reads, beside an empty pytest.ini that makes
the project its own rootdir.

Usage::

    from tests._throwaway_lane_project import PROBE_JOB, throwaway_lane_project

    command = f"{shlex.quote(sys.executable)} -m pytest -p no:cacheprovider test_in_suite.py"
    project_root = throwaway_lane_project(tmp_path, command, cwd="suite")
    collection = collect_lane_job(project_root, PROBE_JOB, env_for=lambda command: os.environ)
"""

from pathlib import Path

import yaml

PROBE_JOB = "probe"


def throwaway_lane_project(root: Path, command: str, **job_fields: str) -> Path:
    """Make *root* a throwaway project whose one offline-lane job, PROBE_JOB, runs *command*, with *job_fields* as its other keys."""
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / "dark-factory-orchestrator.yaml").write_text(
        yaml.safe_dump({"git": {"offline_lane_commands": [{"name": PROBE_JOB, "command": command, **job_fields}]}}),
        encoding="utf-8",
    )
    return root
