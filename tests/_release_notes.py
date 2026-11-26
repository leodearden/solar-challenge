# SPDX-License-Identifier: AGPL-3.0-or-later
"""The layout of the release notes merged since the last tag, whose rule is docs/domain-library-consumption.md's "Changes merged since the last tag"."""

NOTES_DIR = "docs/unreleased"
CONSUMPTION_DOC = "domain-library-consumption"
FINANCE_MODEL_DOC = "cost-recovery-finance-model"
NOTE_DOCS = (CONSUMPTION_DOC, FINANCE_MODEL_DOC)


def note_path(doc: str, task_id: int) -> str:
    """The project-root-relative POSIX path of the note task *task_id* writes for docs/<doc>.md."""
    return f"{NOTES_DIR}/{doc}/{task_id}.md"
