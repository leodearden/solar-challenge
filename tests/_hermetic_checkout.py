# SPDX-License-Identifier: AGPL-3.0-or-later
"""A new git checkout for a test, in which git reads no exclude pattern from outside the checkout.

So a test that lists the checkout's files, as tests/_working_tree.py's working_tree_files does, or adds them with
`git add --all`, gets the same result whatever the user's or the system's git configuration excludes.

Usage::

    from tests._hermetic_checkout import init_hermetic_checkout

    checkout = init_hermetic_checkout(tmp_path / "checkout")
"""

import os
import subprocess
from pathlib import Path


def init_hermetic_checkout(directory: Path) -> Path:
    """Make *directory* the top level of a new git checkout whose exclude patterns are its own, and return it.

    git makes *directory* and its missing parents, and the files an existing *directory* holds stay there, untracked.
    The empty --template= copies no template, so the checkout has no info/exclude, whatever GIT_TEMPLATE_DIR or
    init.templateDir names. The checkout's own config names the null device as its core.excludesFile, which outranks
    an excludes file the user's or the system's config names and the user's default ignore file,
    XDG_CONFIG_HOME/git/ignore. That setting lives in the checkout, not in this process's environment, so every
    process that runs git there reads it, such as the verify suite the newest-releases suite runs in its copy.
    """
    subprocess.run(["git", "init", "--quiet", "--template=", str(directory)], check=True)
    subprocess.run(["git", "config", "core.excludesFile", os.devnull], cwd=directory, check=True)
    return directory
