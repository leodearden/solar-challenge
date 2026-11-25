# SPDX-License-Identifier: AGPL-3.0-or-later
"""The loads a home's demand is made of, each named by its kind."""

from collections.abc import Iterator, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypeVar

V = TypeVar("V")


class LoadKind(StrEnum):
    """One of the loads a home's demand is made of; its value names its chart role."""

    HOUSEHOLD = "household"
    HEAT_PUMP = "heat_pump"
    EV = "ev"

    @property
    def column(self) -> str:
        """The column its power in kW is written under."""
        return f"{self.value}_load_kw"

    @property
    def energy_column(self) -> str:
        """The column its energy in kWh is written under."""
        return f"{self.value}_load_kwh"

    @property
    def label(self) -> str:
        """How a report names it."""
        return _LABELS[self]

    @classmethod
    def parse(cls, value: object) -> "LoadKind":
        """The kind whose value *value* is; ValueError, naming it and every kind's value, for anything else."""
        if isinstance(value, str):
            for kind in cls:
                if kind.value == value:
                    return kind
        values = [repr(kind.value) for kind in cls]
        raise ValueError(
            f"{value!r} is not a load kind: the load kinds are {', '.join(values[:-1])} and {values[-1]}"
        )


_LABELS: Mapping[LoadKind, str] = MappingProxyType({
    LoadKind.HOUSEHOLD: "Household",
    LoadKind.HEAT_PUMP: "Heat pump",
    LoadKind.EV: "EV charging",
})


class PerLoad(Mapping[LoadKind, V]):
    """A read-only mapping of a value per load kind, held in LoadKind order whatever the order it was given in."""

    __slots__ = ("_items",)

    def __init__(self, by_kind: Mapping[Any, V]) -> None:
        """Hold a copy of *by_kind*, each key read by LoadKind.parse, which refuses one naming no kind."""
        given = {LoadKind.parse(key): value for key, value in by_kind.items()}
        self._items: dict[LoadKind, V] = {kind: given[kind] for kind in LoadKind if kind in given}

    def __getitem__(self, kind: LoadKind) -> V:
        return self._items[kind]

    def __iter__(self) -> Iterator[LoadKind]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __hash__(self) -> int:
        return hash(tuple(self._items.items()))

    def __repr__(self) -> str:
        return f"PerLoad({self._items!r})"

    def __reduce__(self) -> tuple[type["PerLoad[V]"], tuple[dict[LoadKind, V]]]:
        """Rebuild through the constructor from a dict of the items, so a copy reads its keys as the original did."""
        return (type(self), (dict(self._items),))
