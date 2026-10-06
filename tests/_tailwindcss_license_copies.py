# SPDX-License-Identifier: AGPL-3.0-or-later
"""The license texts kept beside the compiled Tailwind stylesheet, and the tailwindcss file each one copies.

The Tailwind CLI compiles MIT-licensed tailwindcss code into
src/solar_challenge/web/static/dist/style.css, so static/dist keeps a verbatim
copy of each license that code is under. TAILWINDCSS_LICENSE_COPIES keys each
copy by its file name in static/dist, and names the file of the tailwindcss npm
package it copies, relative to the package's root. tests/css_build compares each
copy byte for byte with that file of the locked version, and
tests/integration/test_external_install.py checks that the copies are exactly
the license texts the wheel ships from static/dist.

Usage::

    from tests._tailwindcss_license_copies import TAILWINDCSS_LICENSE_COPIES

    for license_copy, licensed_file in TAILWINDCSS_LICENSE_COPIES.items():
        assert (dist / license_copy).read_bytes() == (tailwindcss / licensed_file).read_bytes()
"""

from collections.abc import Mapping
from pathlib import PurePosixPath
from types import MappingProxyType

TAILWINDCSS_LICENSE_COPIES: Mapping[str, PurePosixPath] = MappingProxyType({
    "LICENSE-tailwindcss.txt": PurePosixPath("LICENSE"),
    "LICENSE-tailwindcss-preflight.txt": PurePosixPath("src", "css", "LICENSE"),
})
