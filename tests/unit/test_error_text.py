# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.error_text's one function, error_text_with_notes: an error's text, then each of its notes on a line of its own."""

import pytest

from solar_challenge.error_text import error_text_with_notes
from tests._modules_loaded_by_importing import package_modules_loaded_by_importing


class _AnErrorWhoseTextCannotBeRead(ValueError):
    """An error whose text cannot be read, so error_text_with_notes names its type in its place."""

    def __str__(self) -> str:
        raise RuntimeError("the text of this error cannot be read")


class _ANoteWhoseTextCannotBeRead(str):
    """A note that is a str, as add_note requires, but whose text cannot be read."""

    def __str__(self) -> str:
        raise RuntimeError("the text of this note cannot be read")


class _AnObjectWhoseTextCannotBeRead:
    """An object that is not a str and whose text cannot be read."""

    def __str__(self) -> str:
        raise RuntimeError("the text of this object cannot be read")


class _AnObjectWhoseReprCannotBeRead:
    """An object whose repr cannot be read."""

    def __repr__(self) -> str:
        raise RuntimeError("the repr of this object cannot be read")


class _AnInterruption(BaseException):
    """An error that is not an Exception."""


class _AnErrorWhoseTextIsInterrupted(ValueError):
    """An error reading whose text raises _AnInterruption, an error that is not an Exception."""

    def __str__(self) -> str:
        raise _AnInterruption("reading the text of this error was interrupted")


def _with_notes(error: BaseException, *notes: str) -> BaseException:
    """*error*, once each of *notes* has been added to it."""
    for note in notes:
        error.add_note(note)
    return error


def _with_notes_assigned(error: BaseException, notes: object) -> BaseException:
    """*error*, once *notes* is assigned to its __notes__: add_note keeps __notes__ a list of str, so only an assignment leaves it anything else."""
    setattr(error, "__notes__", notes)
    return error


def test_importing_the_module_loads_no_other_package_module() -> None:
    """A fresh interpreter that imports the module loads no other package module, so any module can import it at top level."""
    assert package_modules_loaded_by_importing("solar_challenge.error_text") == {
        "solar_challenge",
        "solar_challenge.error_text",
    }


def test_an_error_with_no_notes_reads_as_its_text_alone() -> None:
    assert error_text_with_notes(ValueError("it failed")) == "it failed"


@pytest.mark.parametrize(
    "error_type",
    [
        pytest.param(RuntimeError, id="an-exception"),
        pytest.param(SystemExit, id="an-error-that-is-not-an-exception"),
    ],
)
def test_an_errors_notes_follow_its_text_each_on_a_line_of_its_own(error_type: type[BaseException]) -> None:
    error = _with_notes(error_type("it failed"), "first note", "second note")

    assert error_text_with_notes(error) == "it failed\nfirst note\nsecond note"


def test_an_error_whose_text_cannot_be_read_is_named_by_its_type_and_its_notes_still_follow() -> None:
    error = _with_notes(_AnErrorWhoseTextCannotBeRead(), "first note", "second note")

    assert error_text_with_notes(error) == (
        "_AnErrorWhoseTextCannotBeRead, whose message could not be read\nfirst note\nsecond note"
    )


@pytest.mark.parametrize(
    "unreadable_note",
    [
        pytest.param(_ANoteWhoseTextCannotBeRead("hidden"), id="a-str"),
        pytest.param(_AnObjectWhoseTextCannotBeRead(), id="an-object-that-is-not-a-str"),
    ],
)
def test_a_note_whose_text_cannot_be_read_is_named_unreadable_in_its_place_and_the_other_notes_still_read(
    unreadable_note: object,
) -> None:
    error = _with_notes_assigned(ValueError("it failed"), ["first note", unreadable_note, "third note"])

    assert error_text_with_notes(error) == "it failed\nfirst note\nA note whose text could not be read\nthird note"


def test_a_note_that_is_not_a_str_but_reads_is_its_text() -> None:
    error = _with_notes_assigned(ValueError("it failed"), [5])

    assert error_text_with_notes(error) == "it failed\n5"


@pytest.mark.parametrize(
    ("notes", "line"),
    [
        pytest.param("abc", "'abc'", id="a-str"),
        pytest.param(b"ab", "b'ab'", id="bytes"),
        pytest.param(5, "5", id="an-int"),
        pytest.param(
            _AnObjectWhoseReprCannotBeRead(),
            "A __notes__ whose text could not be read",
            id="an-object-whose-repr-cannot-be-read",
        ),
    ],
)
def test_notes_that_are_not_a_sequence_of_notes_are_one_line_their_repr(notes: object, line: str) -> None:
    """As the interpreter's traceback shows them: a str or bytes too is one line, not one note per item."""
    error = _with_notes_assigned(ValueError("it failed"), notes)

    assert error_text_with_notes(error) == f"it failed\n{line}"


def test_an_error_that_is_not_an_exception_raised_while_the_text_is_read_propagates() -> None:
    """Only an Exception is caught, so an interruption such as KeyboardInterrupt or SystemExit is never swallowed."""
    with pytest.raises(_AnInterruption):
        error_text_with_notes(_AnErrorWhoseTextIsInterrupted())
