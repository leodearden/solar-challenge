# SPDX-License-Identifier: AGPL-3.0-or-later
"""The classes of the divider components/macros.html rules under its header bands and tab bars,
so every test that expects the divider reads the one copy here.

A test of a header band or a tab bar expects them among the classes the band or bar is drawn
in, and a source test counts the class lists of macros.html that spell them.

Usage::

    from tests._dashboard_divider import DIVIDER_CLASSES

    panel_title_band_classes = DIVIDER_CLASSES | {"px-5", "py-4"}
"""

DIVIDER_CLASSES = frozenset({"border-b", "border-slate-200", "dark:border-slate-700"})
