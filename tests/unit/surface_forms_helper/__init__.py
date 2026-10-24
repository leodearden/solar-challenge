# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rule tests for tests/_surface_forms.py: test_<function>.py pins that public function's rules, one rule per test.

named_classes has more rules than one module holds, so test_named_classes_<family>.py
splits them by rule family, each module's docstring naming its family. A new rule test
goes in the module of the function, or the family, whose rule its name states.

Each test pins one rule, so an edit that lets one minor's own rendering through, drops
part of a signature, or lets an attribute set on self go undeclared, fails here instead
of turning the frozen-surface lock red on one interpreter or blind to a real change.

No module here imports a rule module, so each reads alone: what more than one of them
uses is in _fixtures.py; test_no_rule_module_imports_another.py checks that.

The annotations of the modules here are evaluated, as in the modules they stand in for,
so none of them imports annotations from __future__; test_annotations_are_evaluated.py
checks that.
"""
