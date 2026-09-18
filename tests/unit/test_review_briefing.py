# SPDX-License-Identifier: AGPL-3.0-or-later
"""review/briefing.yaml must not store task-tree-derived state.

Repo-invariant guard against a recurring drift class: review/briefing.yaml's
POSTURE header and its Deferred-task-invariant convention have repeatedly
embedded a point-in-time snapshot of the live orchestrator task tree — a
tally of tasks by status — and then gone stale before their own fix branch
could even merge. This has recurred four times: Task 91, Task 92 (a
cancelled duplicate of the same fix), Task 96, and Task 107 (this fix). The
tree's single source of truth is the live orchestrator task store, not a
copy committed to this repo, so storing a copy guarantees drift (a
merge-latency-vs-churn race). The only fix that does not recur is to delete
the stored copy, require any tally to be re-derived live via
get_statuses(project_root=...) at read time, and mark both rewritten blocks
`# human-edited` so a `/review-briefing` regeneration cannot silently
reintroduce a fresh snapshot. These tests fail the build if a task tally
ever reappears in review/briefing.yaml, or if either drift-prone block loses
its `# human-edited` marker.
"""

import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_briefing(project_root: Path) -> str:
    """Return the full text of review/briefing.yaml."""
    return (project_root / "review" / "briefing.yaml").read_text(encoding="utf-8")


# Detects a task-tree tally in any of the spellings the historical drift texts
# used (verified against `git show` of the task 91/93/96 merge commits):
#   - "96 tasks"                                 (POSTURE header, deferred-why)
#   - "96-task tree"                              (task 96 deferred-invariant why)
#   - "85 done" / "8 cancelled" / "2 in-progress" / "1 pending" / "0 open" /
#     "N deferred" / "N blocked"                  (per-status counts)
# Deliberately does NOT match a bare task-ID reference ("tasks 90-93, 96" —
# digits appear AFTER the word "tasks", not before), a date ("2026-09-18"),
# or an unrelated domain number already in the file ("100-home fleet",
# "1-minute resolution", a version tag) — none of those have a digit
# immediately followed by "tasks" / "-task" / one of the status words.
_TALLY_RE = re.compile(
    r"\b\d+\s+tasks\b"
    r"|\b\d+-task\b"
    r"|\b\d+\s+(?:done|open|cancelled|pending|deferred|blocked|in-progress)\b"
)


def _find_tally_lines(text: str) -> list[tuple[int, str]]:
    """Return (1-based line number, line text) for every line matching _TALLY_RE."""
    return [
        (lineno, line)
        for lineno, line in enumerate(text.splitlines(), start=1)
        if _TALLY_RE.search(line)
    ]


def _posture_header_lines(text: str) -> list[str]:
    """Return the leading run of `#`-prefixed lines (the POSTURE header block)."""
    header: list[str] = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        header.append(line)
    return header


def _comment_lines_immediately_above(lines: list[str], index: int) -> list[str]:
    """Return the contiguous run of comment lines directly above ``lines[index]``.

    Walks upward while a line's stripped content starts with ``#``, stopping
    at the first blank or non-comment line. Used to find a `# human-edited`
    marker that may span more than one comment line immediately preceding a
    YAML entry.
    """
    above: list[str] = []
    i = index - 1
    while i >= 0 and lines[i].strip().startswith("#"):
        above.append(lines[i])
        i -= 1
    return above


def _deferred_invariant_rule_line_index(lines: list[str]) -> int:
    """Return the 0-based index of the `- rule: >` line for the Deferred-task invariant.

    The invariant's name lives in the folded `rule` scalar's first content
    line, one line below its `- rule: >` header — so this locates the name,
    then walks back to that header line.
    """
    for i, line in enumerate(lines):
        if "Deferred-task invariant" in line:
            for j in range(i - 1, -1, -1):
                if re.match(r"\s*-\s*rule:\s*>", lines[j]):
                    return j
            pytest.fail(
                "found 'Deferred-task invariant' text but could not locate "
                "its preceding `- rule: >` line"
            )
    pytest.fail(
        "no line containing 'Deferred-task invariant' found in review/briefing.yaml"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_briefing_stores_no_task_tally_snapshot(project_root: Path) -> None:
    """review/briefing.yaml must not embed a task-tree tally anywhere.

    A tally embedded here is derived data whose single source of truth is
    the live task tree; a copy in this hand-edited, branch-and-merge file
    cannot win the merge-latency-vs-churn race — it drifted across tasks 91,
    92, 96, and 107. Anyone needing a tally must derive it live via
    get_statuses(project_root=...) instead of trusting a stored number.
    """
    text = _read_briefing(project_root)
    offenders = _find_tally_lines(text)
    assert not offenders, (
        "review/briefing.yaml embeds a task-tree tally snapshot — this exact "
        "drift has recurred across tasks 91, 92, 96, and 107; delete the "
        "count(s) and instruct readers to derive them live via "
        "get_statuses(project_root=...) instead. Offending line(s):\n"
        + "\n".join(f"  line {lineno}: {line.strip()}" for lineno, line in offenders)
    )


def test_drift_proof_blocks_are_marked_human_edited(project_root: Path) -> None:
    """Both drift-proof blocks must carry a `# human-edited` marker comment.

    Per briefing-schema.md's "Human edit preservation" section, a future
    `/review-briefing` regeneration preserves any line or block carrying a
    `# human-edited` comment — and would otherwise be free to overwrite this
    fix's drift-proof phrasing with a fresh task-tally snapshot, reopening
    the same recurrence through a second path. The marker must be a real
    YAML comment line, not text folded into a `why: >` scalar's string
    value, so both checks below inspect specific raw text lines rather than
    parsed YAML values.
    """
    text = _read_briefing(project_root)
    lines = text.splitlines()

    header = _posture_header_lines(text)
    assert any("human-edited" in line for line in header), (
        "POSTURE header comment block carries no `# human-edited` marker — "
        "a /review-briefing regeneration could overwrite its drift-proof "
        "phrasing with a fresh task-tally snapshot (briefing-schema.md "
        "'Human edit preservation')."
    )

    rule_idx = _deferred_invariant_rule_line_index(lines)
    preceding_comments = _comment_lines_immediately_above(lines, rule_idx)
    assert any("human-edited" in line for line in preceding_comments), (
        "Deferred-task-invariant convention is not preceded by a "
        "`# human-edited` comment line immediately above its `- rule: >` "
        "line — a /review-briefing regeneration could overwrite its "
        "verdict-free phrasing with a fresh snapshot. The marker must sit "
        "on its own comment line, not inside the `why: >` folded scalar "
        "(that would be string content, not a comment). Comment lines "
        f"immediately above `- rule: >` were: {preceding_comments!r}"
    )
