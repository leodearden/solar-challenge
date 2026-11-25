# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read what a command printed on stderr under typer's CliRunner as one line of text.

Usage::

    from tests._cli_stderr_text import stderr_text

    result = runner.invoke(app, ["home", "run", "--pv-kw", "0"])
    assert stderr_text(result) == "Configuration error: --pv-kw: capacity_kw must be greater than 0, got 0.0"
"""

from typer.testing import Result


def stderr_text(result: Result) -> str:
    """The result's stderr with its whitespace collapsed to single spaces, undoing Rich's wrap at 80 columns."""
    return " ".join(result.stderr.split())
