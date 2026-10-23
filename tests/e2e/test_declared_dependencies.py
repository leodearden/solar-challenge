# SPDX-License-Identifier: AGPL-3.0-or-later
"""The declared-dependency contract of each source scope whose extras include e2e.

Today that is tests-e2e, which checks tests/e2e against [project].dependencies
and the dev, web and e2e extras. It sits here because imports map to
distributions only where a scope's extras are installed, and the offline lane's
e2e job, which runs this directory, is the one run that installs the e2e extra.
tests/unit/test_dependency_declarations.py judges every other scope in the
per-task verify, and pins that the e2e job collects this module's cases.
"""

from pathlib import Path

import pytest

from tests._declared_dependencies import E2E, SOURCE_SCOPES, SourceScope, assert_imports_only_declared


@pytest.mark.parametrize(
    "scope", [scope for scope in SOURCE_SCOPES if E2E in scope.extras], ids=lambda scope: scope.name
)
def test_sources_import_only_declared_dependencies(project_root: Path, scope: SourceScope) -> None:
    """Every third-party distribution a source scope requires must be declared for that scope."""
    assert_imports_only_declared(project_root, scope)
