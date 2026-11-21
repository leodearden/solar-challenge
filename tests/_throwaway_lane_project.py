# SPDX-License-Identifier: AGPL-3.0-or-later
"""A throwaway project whose dark-factory-orchestrator.yaml declares one offline-lane job, PROBE_JOB, and optionally a test_command verify slot, for tests of the probes that run those commands.

tests/_orchestrator_config.py's lane_command and verify_command read the job and
the slot from the yaml, which sits beside an empty pytest.ini that makes the
project its own rootdir.

Usage::

    from tests._throwaway_lane_project import PROBE_JOB, throwaway_lane_project

    command = f"{shlex.quote(sys.executable)} -m pytest -p no:cacheprovider test_in_suite.py"
    project_root = throwaway_lane_project(tmp_path, command, cwd="suite")
    collection = collect_lane_job(project_root, PROBE_JOB, env_for=lambda command: os.environ)

With a test_command, the project also has the verify slot::

    project_root = throwaway_lane_project(tmp_path, command, test_command=command)
    verify = verify_command(project_root, "test_command")
"""

from pathlib import Path

import yaml

PROBE_JOB = "probe"


def throwaway_lane_project(root: Path, command: str, *, test_command: str | None = None, **job_fields: str) -> Path:
    """Make *root* a throwaway project whose one offline-lane job, PROBE_JOB, runs *command*, with *job_fields* as its other keys.

    When given, *test_command* is the project's verify test_command.
    """
    orchestrator_config: dict[str, object] = {
        "git": {"offline_lane_commands": [{"name": PROBE_JOB, "command": command, **job_fields}]}
    }
    if test_command is not None:
        orchestrator_config["test_command"] = test_command
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / "dark-factory-orchestrator.yaml").write_text(yaml.safe_dump(orchestrator_config), encoding="utf-8")
    return root
