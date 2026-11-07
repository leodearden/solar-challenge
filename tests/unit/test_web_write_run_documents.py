# SPDX-License-Identifier: AGPL-3.0-or-later
"""write_run_documents writes each of a run's documents whole, then its format.json; an OSError that stops it part way names the documents it wrote before the fault."""

import json
from pathlib import Path

import pytest

from solar_challenge.web.stored_runs import RunDocumentsWriteStopped, StoredDocument, write_run_documents

_DOCUMENTS = (
    StoredDocument("run-1", "config.json", {"a": 1}),
    StoredDocument("run-1", "summary.json", {"b": 2}),
)
"""Two documents of a run, in the order they are written."""


@pytest.mark.parametrize(
    ("unwritable", "written"),
    [
        pytest.param("config.json", (), id="config-json"),
        pytest.param("summary.json", ("config.json",), id="summary-json"),
        pytest.param("format.json", ("config.json", "summary.json"), id="format-json"),
    ],
)
def test_write_run_documents_stopped_by_a_file_it_cannot_write_names_each_document_it_wrote_before_it(
    tmp_path: Path, unwritable: str, written: tuple[str, ...]
) -> None:
    """A directory in the place of a file stands in for one that cannot be written, e.g. on a full disk: no user can write it as a file, whereas a file's permissions do not bind a root user."""
    run_dir = tmp_path / "run-1"
    (run_dir / unwritable).mkdir(parents=True)

    with pytest.raises(RunDocumentsWriteStopped) as stopped:
        write_run_documents(run_dir, _DOCUMENTS, 3)

    assert stopped.value.written == written
    assert isinstance(stopped.value.fault, OSError)
    assert stopped.value.__cause__ is stopped.value.fault
    assert str(stopped.value) == str(stopped.value.fault)
    assert str(run_dir / unwritable) in str(stopped.value), str(stopped.value)
    contents = {document.name: document.content for document in _DOCUMENTS}
    assert {name: json.loads((run_dir / name).read_text()) for name in written} == {
        name: contents[name] for name in written
    }
    assert not (run_dir / "format.json").is_file()
    assert sorted(path.name for path in run_dir.iterdir()) == sorted({*written, unwritable})


def test_write_run_documents_writes_each_document_then_format_json_naming_the_version(tmp_path: Path) -> None:
    write_run_documents(tmp_path, _DOCUMENTS, 3)

    assert {path.name: json.loads(path.read_text()) for path in tmp_path.iterdir()} == {
        "config.json": {"a": 1},
        "summary.json": {"b": 2},
        "format.json": {"format_version": 3},
    }
