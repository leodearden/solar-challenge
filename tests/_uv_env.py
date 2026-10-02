# SPDX-License-Identifier: AGPL-3.0-or-later
"""The process environment in which a test runs a uv command, without the caller's virtualenv or uv lock mode.

Usage::

    from tests._uv_env import isolated_uv_env

    result = run_collect_only(command, project_root, env=isolated_uv_env(tmp_path / "venv"))
"""

import os
from pathlib import Path

_CALLERS_VIRTUALENV_AND_LOCK_MODE = frozenset({"VIRTUAL_ENV", "UV_FROZEN", "UV_LOCKED", "UV_NO_SYNC"})


def isolated_uv_env(project_environment: Path) -> dict[str, str]:
    """Return this process's environment for a uv command whose project environment is *project_environment*.

    The caller's virtualenv and uv lock mode are left out, so the command treats
    uv.lock as it is spelled: an inherited UV_FROZEN would make its --locked an
    error, UV_NO_SYNC would skip its lock check, and UV_LOCKED would impose a
    lock check it does not ask for.
    """
    env = {name: value for name, value in os.environ.items() if name not in _CALLERS_VIRTUALENV_AND_LOCK_MODE}
    env["UV_PROJECT_ENVIRONMENT"] = str(project_environment)
    return env
