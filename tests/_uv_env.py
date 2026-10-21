# SPDX-License-Identifier: AGPL-3.0-or-later
"""The process environment in which a test runs a uv command, without the caller's virtualenv or uv lock mode.

Usage::

    from tests._uv_env import SharedUvEnvironments, isolated_uv_env

    result = run_collect_only(lane_command(project_root, "e2e"), env=isolated_uv_env(tmp_path / "venv"))

    environments = SharedUvEnvironments(tmp_path_factory.mktemp("uv-probe-environments"))
    command = lane_command(project_root, "e2e")
    result = run_collect_only(command, env=environments.for_command(command.command))
"""

import os
import shlex
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


def _words_after_uv_run(words: list[str]) -> list[str]:
    """Return the words after the first `uv run` among *words*, or none when no `uv run` is among them."""
    for index in range(len(words) - 1):
        if words[index] == "uv" and words[index + 1] == "run":
            return words[index + 2 :]
    return []


def uv_run_options(command: str) -> tuple[str, ...]:
    """Return the words *command* gives `uv run`: those after `uv run`, before the pytest it runs.

    A prefix such as `timeout -k 60 600` and pytest's own arguments are not among
    them. It asserts, naming *command*, that the command runs pytest through `uv run`.
    """
    after_uv_run = _words_after_uv_run(shlex.split(command))
    assert "pytest" in after_uv_run, (
        f"{command!r} runs no pytest through `uv run`, so it gives uv run no options to choose an environment by"
    )
    return tuple(after_uv_run[: after_uv_run.index("pytest")])


class SharedUvEnvironments:
    """One fresh uv project environment per set of `uv run` options, shared only by the commands that give the same options.

    `uv run` syncs inexactly, keeping what an earlier sync installed, so only
    identical options leave an environment holding exactly what each command
    names. It is for commands that run in this project. Each environment dict
    comes from this process's environment at the call, so it carries the calling
    test's offline-window proxy variables.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._project_environments: dict[tuple[str, ...], Path] = {}

    def for_command(self, command: str) -> dict[str, str]:
        """Return an isolated_uv_env for *command*, whose project environment is the one for its uv run options; uv creates it at its first sync."""
        options = uv_run_options(command)
        if options not in self._project_environments:
            self._project_environments[options] = self._root / f"venv-{len(self._project_environments)}"
        return isolated_uv_env(self._project_environments[options])
