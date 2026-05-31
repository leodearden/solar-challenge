"""License compliance contract tests.

These tests encode machine-checkable repo invariants for the AGPL-3.0-or-later
license declaration. They provide durable forward regression protection.
"""

import re
from pathlib import Path


def _get_project_docs(project_root: Path) -> list[Path]:
    """Return project-owned markdown docs excluding docs/research/."""
    docs: list[Path] = [project_root / "README.md"]
    docs_dir = project_root / "docs"
    if docs_dir.exists():
        for md in docs_dir.rglob("*.md"):
            # Exclude docs/research/ — those legitimately reference third-party licenses
            if "research" not in md.parts:
                docs.append(md)
    return docs


_MIT_LICENSE_RE = re.compile(r"\bMIT License\b", re.IGNORECASE)


def test_no_project_doc_claims_mit_license(project_root: Path) -> None:
    """No project-owned doc should claim the MIT License.

    README.md and docs/**/*.md (excluding docs/research/) must not contain
    a whole-word 'MIT License' phrase, since the authoritative license is
    AGPL-3.0-or-later.  A word-boundary regex avoids false positives from
    innocent substrings such as 'permit license'.
    """
    docs = _get_project_docs(project_root)
    assert docs, "Expected at least README.md to be found"

    violators: list[str] = []
    for doc in docs:
        if doc.exists():
            content = doc.read_text(encoding="utf-8")
            if _MIT_LICENSE_RE.search(content):
                violators.append(str(doc.relative_to(project_root)))

    assert not violators, (
        f"These project docs claim the MIT License (should be AGPL-3.0-or-later): "
        f"{violators}"
    )


def test_readme_declares_agpl(project_root: Path) -> None:
    """README.md must name the AGPL-3.0-or-later license somewhere.

    Checks the substantive invariant — README mentions the license name — without
    coupling to cosmetic wording like the heading text or exact link syntax, which
    would break on benign documentation rewrites.  Coverage of the LICENSE file
    content itself is handled by test_license_file_is_agpl.
    """
    readme = project_root / "README.md"
    assert readme.exists(), "README.md must exist"

    content = readme.read_text(encoding="utf-8")

    names_agpl = (
        "AGPL-3.0-or-later" in content or "Affero General Public License" in content
    )
    assert names_agpl, (
        "README.md must name 'AGPL-3.0-or-later' or 'Affero General Public License'"
    )


def test_license_file_is_agpl(project_root: Path) -> None:
    """The root LICENSE file must contain the GNU AGPL v3 text.

    README.md and SPDX headers both point at this file; this test closes the
    loop by verifying the file itself is AGPL rather than MIT or anything else.
    """
    license_file = project_root / "LICENSE"
    assert license_file.exists(), "Root LICENSE file must exist"

    content = license_file.read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in content, (
        "LICENSE must contain 'GNU AFFERO GENERAL PUBLIC LICENSE'"
    )
    assert not _MIT_LICENSE_RE.search(content), (
        "LICENSE must not contain 'MIT License'"
    )


def test_all_source_files_have_spdx_header(project_root: Path) -> None:
    """Every *.py under src/solar_challenge/ must carry the SPDX identifier.

    The token 'SPDX-License-Identifier: AGPL-3.0-or-later' must appear within
    the first 3 lines of each file. This enforces a top-of-file header and
    auto-covers any future module added to the package.
    """
    src_root = project_root / "src" / "solar_challenge"
    source_files = sorted(src_root.rglob("*.py"))

    # Sanity check: the package must have source files
    assert source_files, f"No *.py files found under {src_root}"

    SPDX_TOKEN = "SPDX-License-Identifier: AGPL-3.0-or-later"

    missing: list[str] = []
    for py_file in source_files:
        lines = py_file.read_text(encoding="utf-8").splitlines()
        first_three = "\n".join(lines[:3])
        if SPDX_TOKEN not in first_three:
            missing.append(str(py_file.relative_to(project_root)))

    assert not missing, (
        f"These source files are missing '{SPDX_TOKEN}' in their first 3 lines "
        f"({len(missing)} file(s)):\n" + "\n".join(f"  {f}" for f in missing)
    )
