# SPDX-License-Identifier: AGPL-3.0-or-later
"""The type every dataclass instance has, the bound of a type variable over dataclasses: this module imports no other solar_challenge module, so any module can import it at top level."""

from dataclasses import Field
from typing import Any, ClassVar, Protocol


class DataclassInstance(Protocol):
    """An instance of any dataclass: what dataclasses.fields, asdict and replace accept."""

    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]
