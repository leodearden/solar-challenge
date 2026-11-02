# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's surface_form for a class whose metaclass shadows __dict__, as a metaclass that defines __dict__ as a property does, or whose metaclass's MRO holds a __getattribute__ that tests/_surface_forms_class_reads.py's overriding_getattribute_holder finds, which may give another __dict__, and for an object of such a class, one per test.

The classes and the function above the first test are defined at module level, where
their qualified names carry no '<locals>' and a parametrize decorator can reach them.
"""

import functools
import inspect
from typing import Callable

import pytest

from tests._surface_forms import surface_form
from tests.unit.surface_forms_helper._fixtures import (
    class_whose_init_is,
    class_whose_metaclass_call_is,
    class_whose_new_is,
    dict_intercepting_refusal,
    dict_shadowing_refusal,
    metaclass_whose_dict_gives,
    metaclass_whose_getattribute_gives_dict,
)


def _settle(receiver: object, rate: int) -> None: ...


class Rating:
    """A class whose __call__ is defined with def."""

    def __call__(self, rate: int) -> None: ...


class NoneCalling(Rating, metaclass=metaclass_whose_dict_gives(lambda cls: {"__call__": None})):
    """A Rating whose __dict__ gives None as __call__, over the __call__ Rating holds."""


class PartialCalling(
    Rating,
    metaclass=metaclass_whose_dict_gives(lambda cls: {"__call__": functools.partial(_settle)}),
):
    """A Rating whose __dict__ gives a functools.partial as __call__."""


class ClassmethodCalling(
    Rating,
    metaclass=metaclass_whose_dict_gives(
        lambda cls: {"__call__": classmethod(staticmethod(_settle))}
    ),
):
    """A Rating whose __dict__ gives a classmethod of a staticmethod as __call__."""


class PartialHidden(Rating, metaclass=metaclass_whose_dict_gives(lambda cls: {})):
    """A Rating whose own __call__ is a functools.partial, which its __dict__, giving nothing, hides."""

    __call__ = functools.partial(_settle)


class LoneCalling(metaclass=metaclass_whose_dict_gives(lambda cls: {})):
    """A class whose own __call__, defined with def and held by no base, its __dict__, giving nothing, hides."""

    def __call__(self, rate: int) -> None: ...


class Initialised:
    """A class whose __init__ is defined with def."""

    def __init__(self, rate: int) -> None: ...


class Made:
    """A class whose __new__ is defined with def."""

    def __new__(cls, share: str) -> "Made": ...


class NewClaimed(
    Initialised, Made, metaclass=metaclass_whose_dict_gives(lambda cls: {"__new__": None})
):
    """A class of Initialised and then Made whose __dict__ gives None as __new__."""


class InitHidden(metaclass=metaclass_whose_dict_gives(lambda cls: {})):
    """A class whose own __init__, defined with def, its __dict__, giving nothing, hides."""

    def __init__(self, rate: int) -> None: ...


class PartialInitGiven(
    Initialised,
    metaclass=metaclass_whose_dict_gives(lambda cls: {"__init__": functools.partial(_settle)}),
):
    """An Initialised whose __dict__ gives a functools.partial as __init__."""


class Bare(metaclass=metaclass_whose_dict_gives(lambda cls: {})):
    """A class that holds no constructor and whose __dict__ gives nothing."""


class Transparent(
    Initialised,
    metaclass=metaclass_whose_dict_gives(lambda cls: type.__dict__["__dict__"].__get__(cls)),
):
    """An Initialised whose __dict__ gives the very namespace the class holds."""


class PlainDictHolding(type):
    """A metaclass whose body binds __dict__ to a plain dict."""

    __dict__ = {}


class TypeDictHolding(type):
    """A metaclass whose body binds __dict__ to the descriptor type holds as its own __dict__."""

    __dict__ = type.__dict__["__dict__"]


class DictShadowingSubclass(metaclass_whose_dict_gives(lambda cls: {})):
    """A subclass of a metaclass that defines __dict__ as a property, defining nothing itself."""


class OverPlainDict(Initialised, metaclass=PlainDictHolding):
    """An Initialised of PlainDictHolding."""


class OverTypeDict(Initialised, metaclass=TypeDictHolding):
    """An Initialised of TypeDictHolding."""


class OverDictShadowingSubclass(Initialised, metaclass=DictShadowingSubclass):
    """An Initialised of DictShadowingSubclass."""


class InterceptingShadowing(
    metaclass_whose_getattribute_gives_dict(lambda cls: {}),
    metaclass_whose_dict_gives(lambda cls: {}),
):
    """A metaclass whose MRO holds a metaclass that defines __getattribute__, and then one that defines __dict__ as a property."""


class OverInterceptingShadowing(Initialised, metaclass=InterceptingShadowing):
    """An Initialised of InterceptingShadowing."""


class HiddenGetterPartial(functools.partial, metaclass=metaclass_whose_dict_gives(lambda cls: {})):
    """A functools.partial whose own __get__, giving the partial itself, its __dict__, giving nothing, hides."""

    def __get__(self, instance: object, owner: type | None = None) -> object:
        return self


class HiddenGiver(metaclass=metaclass_whose_dict_gives(lambda cls: {})):
    """A callable descriptor whose own __get__ gives the object it was made with, and whose __dict__ gives nothing."""

    def __init__(self, given: object) -> None:
        self.given = given

    def __get__(self, instance: object, owner: type | None = None) -> object:
        return self.given

    def __call__(self, rate: int) -> None: ...


class CallingShadowing(metaclass_whose_dict_gives(lambda cls: {})):
    """A metaclass whose __call__ is defined with def and whose __dict__ gives, for each class of it, nothing."""

    def __call__(cls, share: str) -> None: ...


class Called(Initialised, metaclass=CallingShadowing):
    """An Initialised of CallingShadowing, whose __call__ inspect reads in place of its __new__ and __init__."""


class Carrying(metaclass=metaclass_whose_dict_gives(lambda cls: {})):
    """A class whose __dict__ gives nothing and that carries the signature of Initialised."""

    __signature__ = inspect.signature(Initialised)


class InstanceDictHolding:
    """A class whose own __dict__ is the descriptor CPython made for it, for its instances."""


class InstanceDictMeta(InstanceDictHolding, type):
    """A metaclass whose MRO holds InstanceDictHolding, and then type."""


class Kept(Initialised, metaclass=InstanceDictMeta):
    """An Initialised of InstanceDictMeta."""


class InterceptedPartialCalling(
    Rating, metaclass=metaclass_whose_getattribute_gives_dict(lambda cls: {})
):
    """A Rating whose own __call__ is a functools.partial, which the __dict__ its metaclass's __getattribute__ gives, giving nothing, hides."""

    __call__ = functools.partial(_settle)


class InterceptedNoneCalling(
    Rating, metaclass=metaclass_whose_getattribute_gives_dict(lambda cls: {"__call__": None})
):
    """A Rating whose own __call__ is defined with def, and whose metaclass's __getattribute__ gives a __dict__ giving None as __call__."""

    def __call__(self, share: str) -> None: ...


class InterceptedNewClaimed(
    Initialised,
    Made,
    metaclass=metaclass_whose_getattribute_gives_dict(lambda cls: {"__new__": None}),
):
    """A class of Initialised and then Made whose metaclass's __getattribute__ gives a __dict__ giving None as __new__."""


class InterceptedInitHidden(metaclass=metaclass_whose_getattribute_gives_dict(lambda cls: {})):
    """A class whose own __init__, defined with def, the __dict__ its metaclass's __getattribute__ gives, giving nothing, hides."""

    def __init__(self, rate: int) -> None: ...


class InterceptedTransparent(
    Initialised,
    metaclass=metaclass_whose_getattribute_gives_dict(
        lambda cls: type.__dict__["__dict__"].__get__(cls)
    ),
):
    """An Initialised whose metaclass's __getattribute__ gives as __dict__ the very namespace the class holds."""


class PassingThrough(type):
    """A metaclass whose __getattribute__ gives what type's gives, for every name."""

    def __getattribute__(cls, name: str) -> object:
        return super().__getattribute__(name)


class InterceptingSubclass(metaclass_whose_getattribute_gives_dict(lambda cls: {})):
    """A subclass of a metaclass that defines __getattribute__, defining nothing itself."""


class GetattributeMixin:
    """A plain class whose __getattribute__ gives what the next one in its MRO gives, for every name."""

    def __getattribute__(self, name: str) -> object:
        return super().__getattribute__(name)


class MixedIntercepting(GetattributeMixin, type):
    """A metaclass whose MRO holds GetattributeMixin, and then type."""


class TypeFirst(type, GetattributeMixin):
    """A metaclass whose MRO holds type, and then GetattributeMixin."""


class TypeGetattributeHolding(type):
    """A metaclass whose body binds __getattribute__ to the one type holds as its own."""

    __getattribute__ = type.__getattribute__


class OverPassingThrough(Initialised, metaclass=PassingThrough):
    """An Initialised of PassingThrough."""


class OverInterceptingSubclass(Initialised, metaclass=InterceptingSubclass):
    """An Initialised of InterceptingSubclass."""


class OverMixedIntercepting(Initialised, metaclass=MixedIntercepting):
    """An Initialised of MixedIntercepting."""


class OverTypeFirst(Initialised, metaclass=TypeFirst):
    """An Initialised of TypeFirst."""


class OverTypeGetattribute(Initialised, metaclass=TypeGetattributeHolding):
    """An Initialised of TypeGetattributeHolding."""


class CallingIntercepting(metaclass_whose_getattribute_gives_dict(lambda cls: {})):
    """A metaclass whose __call__ is defined with def and whose __getattribute__ gives, for each class of it, a __dict__ giving nothing."""

    def __call__(cls, share: str) -> None: ...


class InterceptedCalled(Initialised, metaclass=CallingIntercepting):
    """An Initialised of CallingIntercepting, whose __call__ inspect reads in place of its __new__ and __init__."""


class InterceptedCarrying(metaclass=metaclass_whose_getattribute_gives_dict(lambda cls: {})):
    """A class whose metaclass's __getattribute__ gives a __dict__ giving nothing, and that carries the signature of Initialised."""

    __signature__ = inspect.signature(Initialised)


@pytest.mark.parametrize(
    ("build", "name"),
    [
        pytest.param(lambda: functools.partial(NoneCalling()), "NoneCalling", id="partial-of-it"),
        pytest.param(lambda: class_whose_init_is(NoneCalling()), "NoneCalling", id="init"),
        pytest.param(lambda: class_whose_new_is(NoneCalling()), "NoneCalling", id="new"),
        pytest.param(
            lambda: class_whose_metaclass_call_is(NoneCalling()),
            "NoneCalling",
            id="metaclass-call",
        ),
        pytest.param(
            lambda: class_whose_init_is(PartialCalling()),
            "PartialCalling",
            id="dict-giving-a-partial-call",
        ),
        pytest.param(
            lambda: class_whose_init_is(ClassmethodCalling()),
            "ClassmethodCalling",
            id="dict-giving-a-classmethod-call",
        ),
        pytest.param(
            lambda: class_whose_init_is(PartialHidden()),
            "PartialHidden",
            id="dict-hiding-a-partial-call",
        ),
        pytest.param(
            lambda: class_whose_init_is(LoneCalling()),
            "LoneCalling",
            id="dict-hiding-a-call-no-base-holds",
        ),
    ],
)
def test_an_object_whose_types_metaclass_shadows_dict_raises_a_type_error_naming_that_type_and_its_metaclass_wherever_inspect_reads_it(
    build: Callable[[], object], name: str
) -> None:
    with pytest.raises(TypeError, match=dict_shadowing_refusal(name)):
        surface_form(build())


@pytest.mark.parametrize(
    ("cls", "name"),
    [
        pytest.param(NewClaimed, "NewClaimed", id="dict-giving-new"),
        pytest.param(InitHidden, "InitHidden", id="dict-hiding-init"),
        pytest.param(PartialInitGiven, "PartialInitGiven", id="dict-giving-a-partial-init"),
        pytest.param(Bare, "Bare", id="no-constructor"),
        pytest.param(Transparent, "Transparent", id="dict-giving-the-namespace-the-class-holds"),
    ],
)
def test_a_class_whose_metaclass_shadows_dict_raises_a_type_error_naming_it_and_its_metaclass_wherever_inspect_reads_its_new_or_init(
    cls: type, name: str
) -> None:
    with pytest.raises(TypeError, match=dict_shadowing_refusal(name)):
        surface_form(cls)


@pytest.mark.parametrize(
    ("cls", "refusal"),
    [
        pytest.param(
            OverPlainDict,
            r"\.OverPlainDict has the metaclass \S*\.PlainDictHolding, whose MRO holds "
            r"\S*\.PlainDictHolding\.__dict__, a builtins\.dict, in place of the __dict__ type "
            "gives each class",
            id="plain-dict",
        ),
        pytest.param(
            OverTypeDict,
            r"\.OverTypeDict has the metaclass \S*\.TypeDictHolding, whose MRO holds "
            r"\S*\.TypeDictHolding\.__dict__, a builtins\.getset_descriptor, in place of the "
            "__dict__ type gives each class",
            id="the-descriptor-type-holds",
        ),
        pytest.param(
            OverDictShadowingSubclass,
            dict_shadowing_refusal("OverDictShadowingSubclass", "DictShadowingSubclass"),
            id="subclass-of-a-shadowing-metaclass",
        ),
        pytest.param(
            OverInterceptingShadowing,
            dict_shadowing_refusal("OverInterceptingShadowing", "InterceptingShadowing"),
            id="getattribute-held-before-the-dict",
        ),
    ],
)
def test_a_type_error_for_a_class_whose_metaclass_shadows_dict_names_the_class_in_that_metaclass_mro_holding_the_dict_and_its_type_whatever_that_dict_is(
    cls: type, refusal: str
) -> None:
    with pytest.raises(TypeError, match=refusal):
        surface_form(cls)


@pytest.mark.parametrize(
    ("build", "name"),
    [
        pytest.param(lambda: HiddenGetterPartial(_settle), "HiddenGetterPartial", id="partial"),
        pytest.param(
            lambda: class_whose_init_is(classmethod(HiddenGiver(_settle))),
            "HiddenGiver",
            id="classmethod",
        ),
    ],
)
def test_a_partial_or_a_classmethod_wrapped_object_whose_types_metaclass_shadows_dict_raises_the_type_error_naming_that_type_and_its_metaclass(
    build: Callable[[], object], name: str
) -> None:
    with pytest.raises(TypeError, match=dict_shadowing_refusal(name)):
        surface_form(build())


@pytest.mark.parametrize(
    ("cls", "form"),
    [
        pytest.param(Called, "(share: str) -> None", id="metaclass-call"),
        pytest.param(Carrying, "(rate: int) -> None", id="carried-signature"),
    ],
)
def test_a_class_whose_metaclass_shadows_dict_is_spelled_by_the_metaclass_call_inspect_reads_in_place_of_its_new_and_init_or_by_the_signature_it_carries(
    cls: type, form: str
) -> None:
    assert surface_form(cls) == form


def test_a_class_whose_metaclass_mro_holds_a_class_whose_own_dict_is_the_one_cpython_made_for_it_is_spelled_by_its_constructor() -> None:
    assert surface_form(Kept) == "(rate: int) -> None"


@pytest.mark.parametrize(
    ("build", "name"),
    [
        pytest.param(
            lambda: class_whose_init_is(InterceptedPartialCalling()),
            "InterceptedPartialCalling",
            id="getattribute-hiding-a-partial-call",
        ),
        pytest.param(
            lambda: class_whose_init_is(InterceptedNoneCalling()),
            "InterceptedNoneCalling",
            id="getattribute-giving-none-as-call",
        ),
        pytest.param(
            lambda: functools.partial(InterceptedNoneCalling()),
            "InterceptedNoneCalling",
            id="partial-of-it",
        ),
    ],
)
def test_an_object_whose_types_metaclass_overrides_types_getattribute_raises_a_type_error_naming_that_type_and_its_metaclass_wherever_inspect_reads_it(
    build: Callable[[], object], name: str
) -> None:
    with pytest.raises(TypeError, match=dict_intercepting_refusal(name)):
        surface_form(build())


@pytest.mark.parametrize(
    ("cls", "name"),
    [
        pytest.param(InterceptedNewClaimed, "InterceptedNewClaimed", id="getattribute-giving-new"),
        pytest.param(
            InterceptedInitHidden, "InterceptedInitHidden", id="getattribute-hiding-init"
        ),
        pytest.param(
            InterceptedTransparent,
            "InterceptedTransparent",
            id="getattribute-giving-the-namespace-the-class-holds",
        ),
    ],
)
def test_a_class_whose_metaclass_overrides_types_getattribute_raises_a_type_error_naming_it_and_its_metaclass_wherever_inspect_reads_its_new_or_init(
    cls: type, name: str
) -> None:
    with pytest.raises(TypeError, match=dict_intercepting_refusal(name)):
        surface_form(cls)


@pytest.mark.parametrize(
    ("cls", "name", "metaclass", "holder"),
    [
        pytest.param(
            OverPassingThrough,
            "OverPassingThrough",
            "PassingThrough",
            "PassingThrough",
            id="getattribute-giving-what-types-gives",
        ),
        pytest.param(
            OverInterceptingSubclass,
            "OverInterceptingSubclass",
            "InterceptingSubclass",
            "Intercepting",
            id="subclass-of-a-metaclass-defining-getattribute",
        ),
        pytest.param(
            OverMixedIntercepting,
            "OverMixedIntercepting",
            "MixedIntercepting",
            "GetattributeMixin",
            id="base-before-type",
        ),
    ],
)
def test_a_type_error_for_a_class_whose_metaclass_overrides_types_getattribute_names_the_class_in_that_metaclass_mro_holding_it_whatever_it_gives(
    cls: type, name: str, metaclass: str, holder: str
) -> None:
    with pytest.raises(TypeError, match=dict_intercepting_refusal(name, metaclass, holder)):
        surface_form(cls)


@pytest.mark.parametrize(
    "cls",
    [
        pytest.param(OverTypeFirst, id="getattribute-held-after-type"),
        pytest.param(OverTypeGetattribute, id="body-binding-types-own-getattribute"),
    ],
)
def test_a_class_whose_metaclass_mro_first_holds_types_own_getattribute_is_spelled_by_its_constructor(
    cls: type,
) -> None:
    assert surface_form(cls) == "(rate: int) -> None"


@pytest.mark.parametrize(
    ("cls", "form"),
    [
        pytest.param(InterceptedCalled, "(share: str) -> None", id="metaclass-call"),
        pytest.param(InterceptedCarrying, "(rate: int) -> None", id="carried-signature"),
    ],
)
def test_a_class_whose_metaclass_overrides_types_getattribute_is_spelled_by_the_metaclass_call_inspect_reads_in_place_of_its_new_and_init_or_by_the_signature_it_carries(
    cls: type, form: str
) -> None:
    assert surface_form(cls) == form
