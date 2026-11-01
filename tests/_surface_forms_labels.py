# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the surface-forms helper's errors name an object, so each of its modules names objects alike.

Of the helper, this module imports only the modules below it in
tests/unit/test_surface_forms_layers.py's LAYERS, which checks that.
"""


def label_of(obj: object) -> str:
    """The name this helper's errors give *obj*: its module's name and its qualified name, dotted; its repr if it records no qualified name, as a type variable does not."""
    qualified_name = getattr(obj, "__qualname__", None)
    return repr(obj) if qualified_name is None else f"{obj.__module__}.{qualified_name}"
