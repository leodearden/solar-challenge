# SPDX-License-Identifier: AGPL-3.0-or-later
"""RunFilesBroughtForward, the run files a refused part of a migration brought forward before its fault: how it lists the runs brought forward wholly or in part and the values dropped or rewritten in them, and which values it admits.

It is a plain value, built directly here, as is PartlyBroughtForwardRun, a run brought forward in
part; tests/unit/test_web_migrate_stored_runs.py checks what a refused migrate_store carries in it.
"""

import pytest

from solar_challenge.web.schema import RunFilesBroughtForward
from solar_challenge.web.stored_runs import DroppedValue, PartlyBroughtForwardRun, RewrittenValue


def test_run_files_brought_forward_lists_each_run_then_each_value_dropped_then_each_value_rewritten() -> None:
    """Each section is listed only when it holds an item, so a report of no run reads as nothing."""
    dropped = DroppedValue("run-1", "summary.json", "retired_figure", 12.5)
    rewritten = RewrittenValue("run-3", "config.json", "homes[2].dispatch_strategy", "tou_optimized", "greedy")
    brought_forward = RunFilesBroughtForward(
        runs=("run-1", "run-3"), dropped_values=(dropped,), rewritten_values=(rewritten,)
    )

    lines = str(brought_forward).splitlines()

    assert len(lines) == 7, lines
    assert lines[0].startswith("Before the fault, brought forward the files of each run below"), lines
    assert lines[1:3] == ["  run 'run-1'", "  run 'run-3'"]
    assert lines[3].startswith("Dropped each value below"), lines
    assert lines[4] == f"  {dropped}"
    assert lines[5].startswith("Rewrote each value below"), lines
    assert lines[6] == f"  {rewritten}"
    assert str(RunFilesBroughtForward(runs=("run-1",))).splitlines() == [lines[0], "  run 'run-1'"]
    assert str(RunFilesBroughtForward()) == ""


@pytest.mark.parametrize(
    ("dropped_values", "rewritten_values"),
    [
        pytest.param((DroppedValue("run-3", "summary.json", "retired_figure", 12.5),), (), id="dropped"),
        pytest.param(
            (),
            (RewrittenValue("run-3", "config.json", "homes[2].dispatch_strategy", "tou_optimized", "greedy"),),
            id="rewritten",
        ),
    ],
)
def test_run_files_brought_forward_refuses_a_value_of_a_run_it_does_not_name(
    dropped_values: tuple[DroppedValue, ...], rewritten_values: tuple[RewrittenValue, ...]
) -> None:
    """Each value is of a run whose files were brought forward, so a report that names no run holds no value."""
    with pytest.raises(ValueError) as refused:
        RunFilesBroughtForward(runs=("run-1",), dropped_values=dropped_values, rewritten_values=rewritten_values)

    for named in ["'run-3'", "run-1"]:
        assert named in str(refused.value), (named, str(refused.value))


def test_run_files_brought_forward_lists_each_run_brought_forward_in_part_after_the_runs_and_before_the_values() -> None:
    """A run brought forward in part is listed under a heading of its own, with the documents written, so a report of that run alone reads as that run."""
    dropped = DroppedValue("run-1", "summary.json", "retired_figure", 12.5)
    partly = PartlyBroughtForwardRun("run-2", ("config.json", "summary.json"))
    rewritten = RewrittenValue("run-2", "config.json", "dispatch_strategy", "tou_optimized", "greedy")
    brought_forward = RunFilesBroughtForward(
        runs=("run-1",),
        partly_brought_forward_runs=(partly,),
        dropped_values=(dropped,),
        rewritten_values=(rewritten,),
    )

    lines = str(brought_forward).splitlines()

    assert len(lines) == 8, lines
    assert lines[0].startswith("Before the fault, brought forward the files of each run below"), lines
    assert lines[1] == "  run 'run-1'"
    assert lines[2].startswith("Before the fault, brought forward only the documents named of each run below"), lines
    assert lines[3] == "  run 'run-2': config.json, summary.json"
    assert lines[4].startswith("Dropped each value below"), lines
    assert lines[5] == f"  {dropped}"
    assert lines[6].startswith("Rewrote each value below"), lines
    assert lines[7] == f"  {rewritten}"
    assert str(RunFilesBroughtForward(partly_brought_forward_runs=(partly,))).splitlines() == lines[2:4]
    assert str(RunFilesBroughtForward()) == ""


@pytest.mark.parametrize(
    ("dropped_values", "rewritten_values"),
    [
        pytest.param((DroppedValue("run-2", "config.json", "retired_figure", 12.5),), (), id="dropped"),
        pytest.param(
            (),
            (RewrittenValue("run-2", "config.json", "dispatch_strategy", "tou_optimized", "greedy"),),
            id="rewritten",
        ),
    ],
)
def test_run_files_brought_forward_admits_a_value_of_a_partly_brought_forward_run_only_in_a_document_it_wrote(
    dropped_values: tuple[DroppedValue, ...], rewritten_values: tuple[RewrittenValue, ...]
) -> None:
    """A run's documents left unwritten are read in their older format by the migration run again, which reports their values, so this report holds none of them."""
    wrote_its_summary = (PartlyBroughtForwardRun("run-2", ("summary.json",)),)
    in_its_summary = DroppedValue("run-2", "summary.json", "retired_figure", 12.5)

    admitted = RunFilesBroughtForward(partly_brought_forward_runs=wrote_its_summary, dropped_values=(in_its_summary,))

    assert admitted.dropped_values == (in_its_summary,)
    with pytest.raises(ValueError) as refused:
        RunFilesBroughtForward(
            partly_brought_forward_runs=wrote_its_summary,
            dropped_values=dropped_values,
            rewritten_values=rewritten_values,
        )
    for named in ["'run-2'", "config.json"]:
        assert named in str(refused.value), (named, str(refused.value))


def test_a_partly_brought_forward_run_names_at_least_one_document() -> None:
    """A run of which no document was written is as it was, so it was not brought forward even in part."""
    with pytest.raises(ValueError) as refused:
        PartlyBroughtForwardRun("run-2", ())

    assert "'run-2'" in str(refused.value), str(refused.value)
