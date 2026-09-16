# SPDX-License-Identifier: AGPL-3.0-or-later
"""Orchestrator config canonicalization guard tests.

These tests encode the invariant that in-repo references to the dark-factory
orchestrator config point at the canonical ./dark-factory-orchestrator.yaml
file rather than the legacy top-level ./orchestrator.yaml path, and that the
legacy path itself no longer exists.
"""

import os
import re
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_canonical_orchestrator_config_loads(project_root: Path) -> None:
    """dark-factory-orchestrator.yaml exists and parses as a populated mapping.

    In-repo proxy for the acceptance criterion "the orchestrator still loads
    its config" — this repo cannot spin up the actual orchestrator process,
    but it can assert the canonical config file is present and well-formed.
    """
    config_path = project_root / "dark-factory-orchestrator.yaml"
    assert config_path.exists(), (
        f"canonical orchestrator config not found at {config_path}"
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, (
        "dark-factory-orchestrator.yaml did not parse to a non-empty mapping"
    )
    expected_keys = {"project_root", "test_command", "type_check_command", "git"}
    missing = expected_keys - data.keys()
    assert not missing, (
        f"dark-factory-orchestrator.yaml is missing expected keys: {missing}"
    )


def test_envrc_targets_canonical_config(project_root: Path) -> None:
    """.envrc's ORCH_CONFIG_PATH must name the canonical config file.

    Compares basenames only: the .envrc value is an absolute path into the
    main checkout, not this worktree, so asserting on-disk existence of that
    absolute path would be environment-dependent and flaky. Uses an exact
    basename comparison rather than ``.endswith("orchestrator.yaml")`` because
    the canonical filename also ends with that literal substring — an
    endswith check could never fail on the legacy name.

    The regex tolerates double-quoted, single-quoted, or unquoted values so a
    stylistic change to the export line (e.g. dropping quotes) doesn't turn
    this into a false-negative "could not find ORCH_CONFIG_PATH" failure
    instead of tracking the actual invariant being guarded.
    """
    envrc_path = project_root / ".envrc"
    text = envrc_path.read_text(encoding="utf-8")
    m = re.search(r'ORCH_CONFIG_PATH\s*=\s*["\']?([^"\'\s]+)', text)
    assert m, 'could not find ORCH_CONFIG_PATH=... in .envrc'
    value = m.group(1)
    assert os.path.basename(value) == "dark-factory-orchestrator.yaml", (
        f".envrc ORCH_CONFIG_PATH={value!r} does not target the canonical "
        "dark-factory-orchestrator.yaml file"
    )


def test_legacy_top_level_config_absent(project_root: Path) -> None:
    """The legacy top-level ./orchestrator.yaml must not exist in any form.

    Uses ``lexists`` so a dangling symlink also counts as present.
    """
    legacy_path = project_root / "orchestrator.yaml"
    assert not os.path.lexists(legacy_path), (
        f"{legacy_path} exists; the orchestrator config lives only at "
        "dark-factory-orchestrator.yaml"
    )
