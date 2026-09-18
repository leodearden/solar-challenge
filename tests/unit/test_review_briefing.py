# SPDX-License-Identifier: AGPL-3.0-or-later
"""review/briefing.yaml must not store task-tree-derived state.

Repo-invariant guard against a recurring drift class: review/briefing.yaml's
POSTURE header and its Deferred-task-invariant convention have repeatedly
embedded a point-in-time snapshot of the live orchestrator task tree — a
tally of tasks by status, or a stored pass/fail verdict about the tree — and
then gone stale before their own fix branch could even merge. This has
recurred four times: Task 91, Task 92 (a cancelled duplicate of the same
fix), Task 96, and Task 107 (this fix). The tree's single source of truth is
the live orchestrator task store, not a copy committed to this repo, so
storing a copy guarantees drift (a merge-latency-vs-churn race). The only
fix that does not recur is to delete the stored copy and require any tally
or verdict to be re-derived live via get_statuses(project_root=...) at read
time. These tests fail the build if a task tally or a stored verdict about
the live tree ever reappears in review/briefing.yaml.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml


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


def _load_briefing(project_root: Path) -> dict[str, Any]:
    """Parse review/briefing.yaml and return the loaded mapping."""
    data = yaml.safe_load(_read_briefing(project_root))
    assert isinstance(data, dict), "review/briefing.yaml did not parse to a mapping"
    return data


def _find_deferred_invariant_convention(data: dict[str, Any]) -> dict[str, Any]:
    """Return the conventions[] entry whose `rule` names the Deferred-task invariant.

    Asserts a match is found so this guard cannot be silently satisfied by
    deleting the invariant altogether — only by rewriting its `why` text.
    """
    for entry in data.get("conventions", []):
        if "Deferred-task invariant" in entry.get("rule", ""):
            return entry
    pytest.fail(
        "no conventions[] entry with a `rule` naming 'Deferred-task invariant' "
        "found in review/briefing.yaml — the invariant must not be deleted, "
        "only its stored-verdict `why` text rewritten"
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


@pytest.mark.parametrize(
    "literal",
    [
        "tasks 90-93, 96",
        "As of 2026-09-18, live get_statuses showed the current tree",
        "a heterogeneous 100-home fleet",
        "domestic PV and battery systems at 1-minute resolution",
        "the current tag solar-challenge-v0.4.0",
    ],
)
def test_tally_detector_ignores_non_tally_numbers(literal: str) -> None:
    """_TALLY_RE must not fire on task-ID references, dates, or domain numbers.

    Guards the detector itself against being too broad: a task-ID list
    ("tasks 90-93, 96"), a date, or an unrelated domain number already
    present in the file (fleet size, sample resolution, a version tag) must
    never be mistaken for a task-tree tally.
    """
    assert _TALLY_RE.search(literal) is None, (
        f"_TALLY_RE unexpectedly matched non-tally text: {literal!r}"
    )


def test_deferred_invariant_stores_no_point_in_time_verdict(project_root: Path) -> None:
    """The Deferred-task-invariant `why` must not store a verdict about the live tree.

    A stored PASS/FAIL-style token, or a claim that the deferred count is
    currently zero, is a point-in-time snapshot of the live tree exactly as
    a numeric tally is: it goes stale the moment a task is later deferred,
    independently of whether any number is spelled out. The `why` must
    instead name get_statuses as the place to check — so this rule cannot
    be satisfied by simply deleting the derivation instruction along with
    the verdict.
    """
    data = _load_briefing(project_root)
    entry = _find_deferred_invariant_convention(data)
    why = str(entry.get("why", ""))

    verdict_token = re.search(r"(?i)\b(pass|fail)\b", why)
    assert verdict_token is None, (
        "Deferred-task-invariant `why` stores a point-in-time PASS/FAIL-style "
        f"verdict about the live tree ({verdict_token.group(0)!r}) — this is "
        "the exact drift class this guard exists to prevent (see module "
        f"docstring). `why` was:\n{why}"
    )

    zero_deferred_claim = re.search(r"(?i)zero.{0,40}deferred|deferred.{0,40}zero", why)
    assert zero_deferred_claim is None, (
        "Deferred-task-invariant `why` stores a point-in-time 'zero deferred "
        f"tasks' claim about the live tree ({zero_deferred_claim.group(0)!r}) "
        f"— re-verify live instead of asserting it as fact. `why` was:\n{why}"
    )

    assert "get_statuses" in why, (
        "Deferred-task-invariant `why` must name get_statuses as the live "
        f"derivation source for anyone checking this invariant. `why` was:\n{why}"
    )
