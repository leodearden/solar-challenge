# SPDX-License-Identifier: AGPL-3.0-or-later
"""Release notes for changes merged since the last tag: one file per task, never a paragraph in a doc.

The rule is docs/domain-library-consumption.md's "Changes merged since the last tag";
docs/prds/release-note-fragments.md says why.
"""

from pathlib import Path

import pytest

NOTES_DIR = "docs/unreleased"
NOTE_DOCS = ("domain-library-consumption", "cost-recovery-finance-model")
NOTES_README = "README.md"
UNRELEASED_PARAGRAPH = "**Unreleased on main**"


def _notes_root(project_root: Path) -> Path:
    return project_root / NOTES_DIR


def _note_files(project_root: Path) -> list[Path]:
    """Every file under NOTES_DIR except its README, which outlives each release's notes."""
    notes_root = _notes_root(project_root)
    return sorted(
        path for path in notes_root.rglob("*") if path.is_file() and path != notes_root / NOTES_README
    )


def _is_note_path(relative: Path) -> bool:
    """Whether *relative*, a path under NOTES_DIR, spells <doc>/<task id>.md."""
    if len(relative.parts) != 2 or relative.suffix != ".md":
        return False
    doc, stem = relative.parts[0], relative.stem
    return doc in NOTE_DOCS and stem.isdigit() and str(int(stem)) == stem


def test_the_notes_directory_keeps_its_readme(project_root: Path) -> None:
    """The README keeps docs/unreleased on main between releases, so a grep scoped to it stays live."""
    assert (_notes_root(project_root) / NOTES_README).is_file(), (
        f"{NOTES_DIR}/{NOTES_README} is gone; a release deletes the notes, never the README"
    )


@pytest.mark.parametrize("doc", NOTE_DOCS)
def test_each_note_directory_names_a_doc(project_root: Path, doc: str) -> None:
    assert (project_root / "docs" / f"{doc}.md").is_file(), (
        f"NOTE_DOCS names {doc}, but docs/{doc}.md does not exist"
    )


def test_every_note_is_a_task_file_under_the_doc_it_serves(project_root: Path) -> None:
    notes_root = _notes_root(project_root)
    misplaced = [
        path.relative_to(project_root).as_posix()
        for path in _note_files(project_root)
        if not _is_note_path(path.relative_to(notes_root))
    ]
    assert not misplaced, (
        f"Files under {NOTES_DIR} that are not a release note: {misplaced}. A note is "
        f"{NOTES_DIR}/<doc>/<task id>.md, <doc> one of {list(NOTE_DOCS)} and <task id> the "
        "id of the task whose change it describes, e.g. "
        f"{NOTES_DIR}/domain-library-consumption/871.md."
    )


def test_every_note_says_what_changed(project_root: Path) -> None:
    empty = [
        path.relative_to(project_root).as_posix()
        for path in _note_files(project_root)
        if not path.read_text(encoding="utf-8").strip()
    ]
    assert not empty, f"Release notes with no text: {empty}"


@pytest.mark.parametrize("doc", NOTE_DOCS)
def test_no_doc_holds_an_unreleased_note(project_root: Path, doc: str) -> None:
    doc_lines = (project_root / "docs" / f"{doc}.md").read_text(encoding="utf-8").splitlines()
    paragraphs = [
        number for number, line in enumerate(doc_lines, start=1) if line.startswith(UNRELEASED_PARAGRAPH)
    ]
    assert not paragraphs, (
        f"docs/{doc}.md holds {UNRELEASED_PARAGRAPH} paragraphs at lines {paragraphs}. Write "
        f"each as its own file, {NOTES_DIR}/{doc}/<task id>.md, holding the paragraph without "
        "its prefix, and do not add the paragraph to the doc (docs/domain-library-consumption.md, "
        "'Changes merged since the last tag')."
    )
