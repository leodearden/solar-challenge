# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read a Rich table a command printed under typer's CliRunner as one line of text, in which each row reads as its cells joined by single spaces.

Usage::

    from tests._cli_table_text import table_text

    result = runner.invoke(app, ["validate", "config", "config.yaml"])
    assert "ERROR tilt must be between 0 and 90, got 100.0" in table_text(result.stdout)
"""


def table_text(output: str) -> str:
    """A Rich table's rows folded onto one line, each row reading as its cells joined by single spaces.

    CliRunner renders Rich tables at 80 columns, and a long last cell wraps onto
    continuation lines whose other cells are blank. Folding the column rule "│" and all
    whitespace to single spaces rejoins each row.
    """
    return " ".join(output.replace("│", " ").split())
