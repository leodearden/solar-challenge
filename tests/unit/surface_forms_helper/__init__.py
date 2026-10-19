# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rule tests for tests/_surface_forms.py: test_<function>.py pins that public function's rules, one rule per test.

Each test pins one rule, so an edit that lets one minor's own rendering through, drops
part of a signature, or lets an attribute set on self go undeclared, fails here instead
of turning the frozen-surface lock red on one interpreter or blind to a real change.

The annotations of the modules here are evaluated, as in the modules they stand in for,
so none of them imports annotations from __future__; test_annotations_are_evaluated.py
checks that.
"""
