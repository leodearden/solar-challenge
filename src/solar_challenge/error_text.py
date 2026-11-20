# SPDX-License-Identifier: AGPL-3.0-or-later
"""An error's text as a user reads it: the error's message, then each of its notes on a line of its own, each read so that an unreadable one is named in its place.

The module imports no other solar_challenge module, so any module can import it at top level.
"""

from collections.abc import Callable, Sequence


def error_text_with_notes(error: BaseException) -> str:
    """*error*'s text, then each of its notes on a line of its own.

    A __notes__ that is not a sequence of notes (a str or bytes included) is one line, its repr, as the interpreter's
    traceback shows it. A text that cannot be read, the error's, a note's or that repr, is named as unreadable in its
    place. Only an Exception raised while a text is read is caught, so an error that is not one, such as a
    KeyboardInterrupt, propagates.
    """
    return "\n".join(
        [_text_or(error, f"{type(error).__name__}, whose message could not be read"), *_note_texts_of(error)]
    )


def _text_or(value: object, unreadable: str, read: Callable[[object], str] = str) -> str:
    """*value* as *read* gives it, str by default, or *unreadable* when reading it raises an Exception."""
    try:
        return read(value)
    except Exception:
        return unreadable


def _note_texts_of(error: BaseException) -> list[str]:
    """The text of each of *error*'s notes.

    add_note keeps __notes__ a list, but an assignment can leave it anything. One that is not a sequence of notes, a
    str or bytes included, is shown as the interpreter's traceback shows it: as a single entry, its repr.
    """
    notes = getattr(error, "__notes__", ())
    if isinstance(notes, Sequence) and not isinstance(notes, (str, bytes)):
        return [_text_or(note, "A note whose text could not be read") for note in notes]
    return [_text_or(notes, "A __notes__ whose text could not be read", read=repr)]
