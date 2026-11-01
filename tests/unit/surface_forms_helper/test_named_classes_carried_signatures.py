# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules of tests/_surface_forms.py's named_classes for a class that carries an inspect.Signature, for the module the strings that signature names are read in, whether that of the end of its constructor's chain, of the class holding the signature or of the link of that chain given it, and for the TypeError raised where no module is known to spell them, one per test.

The constructor that spells the signature of a class that carries none has its rules in
test_named_classes_constructors.py.
"""

import decimal
import fractions
import functools
import inspect
import pathlib
import warnings
from collections.abc import Callable

import pytest

from tests._surface_forms import named_classes, surface_form
from tests.unit.surface_forms_helper._fixtures import (
    CLASSMETHOD_WRAPPEES_BOUND_BY_MINOR,
    imported_module,
    metaclass_whose_mro_gives,
)


_LINKCALLING_SOURCE = (
    "import functools\n"
    "import inspect\n"
    "from fractions import Fraction as Share\n"
    "\n"
    "def _given(receiver: 'Share', rate: int) -> None: ...\n"
    "\n"
    "wrapper = functools.wraps(object.__init__)(_given)\n"
    "wrapper.__signature__ = inspect.Signature(\n"
    "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
    ")\n"
    "\n"
    "class LinkCalling(type):\n"
    "    __call__ = staticmethod(wrapper)\n"
    "\n"
    "class LinkInitialised:\n"
    "    __init__ = wrapper\n"
)

_METASIGNING_SOURCE = (
    "import inspect\n"
    "from decimal import Decimal as Share\n"
    "\n"
    "from linkcalling import LinkCalling, LinkInitialised, wrapper\n"
    "\n"
    "own = inspect.Signature(\n"
    "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
    ")\n"
    "\n"
    "class OwnSigning(type):\n"
    "    @property\n"
    "    def __signature__(cls):\n"
    "        return own\n"
    "\n"
    "class OwnSigningCalling(OwnSigning, LinkCalling):\n"
    "    pass\n"
    "\n"
    "class CopiedCalled(metaclass=OwnSigningCalling):\n"
    "    __signature__ = wrapper.__signature__\n"
    "\n"
    "class CopiedInitialised(LinkInitialised, metaclass=OwnSigning):\n"
    "    __signature__ = wrapper.__signature__\n"
    "\n"
    "class LinkSigning(type):\n"
    "    @property\n"
    "    def __signature__(cls):\n"
    "        return wrapper.__signature__\n"
    "\n"
    "class LinkSigningCalling(LinkSigning, LinkCalling):\n"
    "    pass\n"
    "\n"
    "class OwnCalled(metaclass=LinkSigningCalling):\n"
    "    __signature__ = own\n"
    "\n"
    "class OwnInitialised(LinkInitialised, metaclass=LinkSigning):\n"
    "    __signature__ = own\n"
)


def test_a_class_names_the_classes_its_signature_names_read_where_its_constructor_is_spelled_though_the_class_carries_one(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metering",
        "from fractions import Fraction as Share\n"
        "\n"
        "class Meter:\n"
        "    def __init__(self, share: 'Share', rate: int) -> None: ...\n",
    )
    imported_module(
        tmp_path,
        monkeypatch,
        "decorating",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "def without_rate(cls):\n"
        "    signature = inspect.signature(cls)\n"
        "    parameters = list(signature.parameters.values())[:1]\n"
        "    cls.__signature__ = signature.replace(parameters=parameters)\n"
        "    return cls\n",
    )
    submetering = imported_module(
        tmp_path,
        monkeypatch,
        "submetering",
        "from decimal import Decimal as Share\n"
        "\n"
        "from decorating import without_rate\n"
        "from metering import Meter\n"
        "\n"
        "@without_rate\n"
        "class Submeter(Meter):\n"
        "    pass\n",
    )

    assert named_classes(submetering.Submeter) == {fractions.Fraction}


def test_a_class_constructed_by_object_or_in_c_names_the_classes_its_signature_names_read_where_the_class_holding_that_signature_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rates = imported_module(
        tmp_path,
        monkeypatch,
        "rates",
        "import collections\n"
        "import functools\n"
        "import inspect\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Rated(dict):\n"
        "    __signature__ = signature\n"
        "\n"
        "class Ordered(collections.OrderedDict):\n"
        "    __signature__ = signature\n"
        "\n"
        "class Plain:\n"
        "    __signature__ = signature\n"
        "\n"
        "class Counting(type):\n"
        "    @functools.wraps(type.__call__)\n"
        "    def __call__(cls, *args, **kwargs):\n"
        "        return super().__call__(*args, **kwargs)\n"
        "\n"
        "class Counted(metaclass=Counting):\n"
        "    __signature__ = signature\n"
        "\n"
        "class SettingSignature(inspect.Signature):\n"
        "    def __set__(self, instance, value): ...\n"
        "\n"
        "class SetRated(dict):\n"
        "    __signature__ = SettingSignature(signature.parameters.values())\n",
    )
    rerates = imported_module(
        tmp_path,
        monkeypatch,
        "rerates",
        "from decimal import Decimal as Share\n"
        "\n"
        "from rates import Rated\n"
        "\n"
        "class Rerated(Rated):\n"
        "    pass\n",
    )

    assert named_classes(rates.Rated) == {fractions.Fraction}
    assert named_classes(rates.Ordered) == {fractions.Fraction}
    assert named_classes(rates.Plain) == {fractions.Fraction}
    assert named_classes(rates.Counted) == {fractions.Fraction}
    assert named_classes(rates.SetRated) == {fractions.Fraction}
    assert named_classes(functools.partial(rates.Rated)) == {fractions.Fraction}
    assert named_classes(rerates.Rerated) == {fractions.Fraction}


def test_a_class_carrying_a_signature_a_base_holds_names_the_classes_it_names_read_where_that_base_is_spelled_whatever_mro_its_metaclass_gives(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "signing_bases",
        "import inspect\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "class Signing:\n"
        "    __signature__ = inspect.Signature(\n"
        "        [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        "    )\n",
    )
    hidden_signers = imported_module(
        tmp_path,
        monkeypatch,
        "hidden_signers",
        "from decimal import Decimal as Share\n"
        "\n"
        "from signing_bases import Signing\n"
        "\n"
        "class Hiding(type):\n"
        "    @property\n"
        "    def __mro__(cls):\n"
        "        return (cls,)\n"
        "\n"
        "class Signed(Signing, metaclass=Hiding):\n"
        "    pass\n",
    )

    assert named_classes(hidden_signers.Signed) == {fractions.Fraction}


def test_a_class_whose_metaclass_holds_its_signature_raises_type_error_naming_the_class_and_that_metaclass_whatever_its_constructor(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "metas",
        "import inspect\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Signed(type):\n"
        "    __signature__ = signature\n"
        "\n"
        "class PropertySigned(type):\n"
        "    @property\n"
        "    def __signature__(cls):\n"
        "        return signature\n"
        "\n"
        "class CallingSigned(type):\n"
        "    __signature__ = signature\n"
        "\n"
        "    def __call__(cls, share: 'Share') -> None: ...\n",
    )
    users = imported_module(
        tmp_path,
        monkeypatch,
        "users",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from metas import CallingSigned, PropertySigned, Signed\n"
        "\n"
        "class Rated(dict, metaclass=Signed):\n"
        "    pass\n"
        "\n"
        "class DefinedRated(metaclass=Signed):\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "class Overridden(dict, metaclass=PropertySigned):\n"
        "    __signature__ = inspect.Signature()\n"
        "\n"
        "class DefinedOverridden(metaclass=PropertySigned):\n"
        "    __signature__ = inspect.Signature()\n"
        "\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "class Called(metaclass=CallingSigned):\n"
        "    pass\n",
    )

    with pytest.raises(TypeError) as plain:
        named_classes(users.Rated)
    with pytest.raises(TypeError) as defined_plain:
        named_classes(users.DefinedRated)
    with pytest.raises(TypeError) as overriding:
        named_classes(users.Overridden)
    with pytest.raises(TypeError) as defined_overriding:
        named_classes(users.DefinedOverridden)
    with pytest.raises(TypeError) as called:
        named_classes(users.Called)

    assert "users.Rated" in str(plain.value)
    assert "metas.Signed" in str(plain.value)
    assert "users.DefinedRated" in str(defined_plain.value)
    assert "metas.Signed" in str(defined_plain.value)
    assert "users.Overridden" in str(overriding.value)
    assert "metas.PropertySigned" in str(overriding.value)
    assert "users.DefinedOverridden" in str(defined_overriding.value)
    assert "metas.PropertySigned" in str(defined_overriding.value)
    assert "users.Called" in str(called.value)
    assert "metas.CallingSigned" in str(called.value)


def test_a_class_whose_metaclass_takes_a_signature_from_a_base_its_own_metaclass_mro_hides_raises_type_error_naming_the_class_and_that_metaclass() -> None:
    class SigningMetaBase(type):
        @property
        def __signature__(cls) -> inspect.Signature:
            return inspect.Signature(
                [inspect.Parameter("meta", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=bytes)]
            )

    class SigningMeta(SigningMetaBase, metaclass=metaclass_whose_mro_gives(lambda cls: (cls,))):
        pass

    class Signed(metaclass=SigningMeta):
        __signature__ = inspect.Signature(
            [inspect.Parameter("share", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
        )

    with pytest.raises(
        TypeError, match=r"\.Signed carries a signature its metaclass \S*\.SigningMeta provides\b"
    ):
        named_classes(Signed)


def test_a_class_whose_metaclass_defines_getattribute_raises_type_error_whatever_its_constructor_but_one_that_shadows_its_metaclass_attribute_names_its_own_signatures_classes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "lookup_metas",
        "import inspect\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('meta', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class PlainSigned(type):\n"
        "    __signature__ = signature\n"
        "\n"
        "class Intercepting(type):\n"
        "    def __getattribute__(cls, name):\n"
        "        if name == '__signature__':\n"
        "            return signature\n"
        "        return super().__getattribute__(name)\n",
    )
    lookup_users = imported_module(
        tmp_path,
        monkeypatch,
        "lookup_users",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from lookup_metas import Intercepting, PlainSigned\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Shadowed(dict, metaclass=PlainSigned):\n"
        "    __signature__ = signature\n"
        "\n"
        "class Intercepted(dict, metaclass=Intercepting):\n"
        "    __signature__ = signature\n"
        "\n"
        "class DefinedIntercepted(metaclass=Intercepting):\n"
        "    __signature__ = signature\n"
        "\n"
        "    def __init__(self, share: 'Share') -> None: ...\n",
    )

    with pytest.raises(TypeError) as intercepted:
        named_classes(lookup_users.Intercepted)
    with pytest.raises(TypeError) as defined_intercepted:
        named_classes(lookup_users.DefinedIntercepted)

    assert "lookup_users.Intercepted" in str(intercepted.value)
    assert "lookup_metas.Intercepting" in str(intercepted.value)
    assert "lookup_users.DefinedIntercepted" in str(defined_intercepted.value)
    assert "lookup_metas.Intercepting" in str(defined_intercepted.value)
    assert named_classes(lookup_users.Shadowed) == {decimal.Decimal}


@pytest.mark.parametrize(
    "describing_base",
    [
        pytest.param("object", id="plain-class"),
        pytest.param("inspect.Signature", id="inspect-signature-subclass"),
    ],
)
def test_a_class_whose_signature_a_descriptor_gives_raises_type_error_naming_it_the_class_holding_that_descriptor_and_its_type_whatever_its_constructor(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, describing_base: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "describing",
        "import inspect\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        f"class Describing({describing_base}):\n"
        "    def __get__(self, instance, owner):\n"
        "        return signature\n",
    )
    described = imported_module(
        tmp_path,
        monkeypatch,
        "described",
        "import functools\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from describing import Describing\n"
        "\n"
        "class Described(dict):\n"
        "    __signature__ = Describing()\n"
        "\n"
        "class Redescribed(Described):\n"
        "    pass\n"
        "\n"
        "class DefinedDescribed:\n"
        "    __signature__ = Describing()\n"
        "\n"
        "    def __init__(self, share: 'Share') -> None: ...\n"
        "\n"
        "class Bound:\n"
        "    __init__ = staticmethod(object().__init__)\n"
        "\n"
        "class BoundDescribed(Bound):\n"
        "    __signature__ = Describing()\n"
        "\n"
        "class PlainDescribed:\n"
        "    __signature__ = Describing()\n"
        "\n"
        "carried = Describing()\n"
        "\n"
        "def _relayed(receiver: 'Share', rate: int) -> None: ...\n"
        "\n"
        "relay = functools.wraps(object.__init__)(_relayed)\n"
        "relay.__signature__ = carried\n"
        "\n"
        "class Relayed:\n"
        "    __init__ = relay\n"
        "\n"
        "class LinkDescribed(Relayed):\n"
        "    __signature__ = carried\n",
    )

    holder_of = {
        "Described": "Described",
        "Redescribed": "Described",
        "DefinedDescribed": "DefinedDescribed",
        "BoundDescribed": "BoundDescribed",
        "PlainDescribed": "PlainDescribed",
        "LinkDescribed": "LinkDescribed",
    }
    for name, holder in holder_of.items():
        with pytest.raises(TypeError) as raised:
            named_classes(getattr(described, name))

        for text in (f"described.{name}", f"described.{holder}", "describing.Describing"):
            assert text in str(raised.value)
        assert "builtins.type" not in str(raised.value)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Recreated", id="new"),
        pytest.param("Reinitialised", id="init"),
        pytest.param("ReboundInitialised", id="init-wrapping-a-method-wrapper"),
        pytest.param("RekeyedInitialised", id="init-wrapping-a-classmethod-descriptor"),
    ],
)
def test_a_class_that_carries_a_signature_over_a_constructor_that_wraps_a_callable_defined_in_c_names_the_classes_that_signature_names_read_where_the_class_holding_it_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "wrapping",
        "from fractions import Fraction as Share\n"
        "from functools import wraps\n"
        "\n"
        "class Created:\n"
        "    @wraps(object.__new__)\n"
        "    def __new__(cls, *args, **kwargs):\n"
        "        return object.__new__(cls)\n"
        "\n"
        "class Initialised:\n"
        "    @wraps(object.__init__)\n"
        "    def __init__(self, *args, **kwargs) -> None: ...\n"
        "\n"
        "class BoundInitialised:\n"
        "    @wraps(object().__init__)\n"
        "    def __init__(self, *args, **kwargs) -> None: ...\n"
        "\n"
        "class KeyedInitialised:\n"
        "    @wraps(dict.__dict__['fromkeys'])\n"
        "    def __init__(self, *args, **kwargs) -> None: ...\n",
    )
    signing = imported_module(
        tmp_path,
        monkeypatch,
        "signing",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from wrapping import BoundInitialised, Created, Initialised, KeyedInitialised\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Recreated(Created):\n"
        "    __signature__ = signature\n"
        "\n"
        "class Reinitialised(Initialised):\n"
        "    __signature__ = signature\n"
        "\n"
        "class ReboundInitialised(BoundInitialised):\n"
        "    __signature__ = signature\n"
        "\n"
        "class RekeyedInitialised(KeyedInitialised):\n"
        "    __signature__ = signature\n",
    )

    assert named_classes(getattr(signing, name)) == {decimal.Decimal}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("MethodWrapperCalled", id="metaclass-call-staticmethod-of-a-method-wrapper"),
        pytest.param(
            "ClassmethodDescriptorCalled",
            id="metaclass-call-descriptor-giving-a-classmethod-descriptor",
        ),
        pytest.param(
            "WrapperCalled", id="metaclass-call-staticmethod-of-a-wrapper-of-a-slot-wrapper"
        ),
        pytest.param("MethodWrapperRebuilt", id="init-staticmethod-of-a-method-wrapper"),
        pytest.param(
            "ClassmethodDescriptorRebuilt", id="init-descriptor-giving-a-classmethod-descriptor"
        ),
        pytest.param("WrapperRebuilt", id="init-staticmethod-of-a-wrapper-of-a-slot-wrapper"),
    ],
)
def test_a_class_that_carries_a_signature_over_a_metaclass_call_or_init_inspect_binds_to_a_callable_defined_in_c_or_to_a_wrapper_of_one_names_the_classes_that_signature_names_read_where_the_class_holding_it_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "binding_in_c",
        "import functools\n"
        "from fractions import Fraction as Share\n"
        "\n"
        "from tests.unit.surface_forms_helper._fixtures import Giver\n"
        "\n"
        "def build(receiver: 'Share', rate: int) -> None: ...\n"
        "\n"
        "class MethodWrapperCalling(type):\n"
        "    __call__ = staticmethod(object().__init__)\n"
        "\n"
        "class ClassmethodDescriptorCalling(type):\n"
        "    __call__ = Giver(dict.__dict__['fromkeys'])\n"
        "\n"
        "class WrapperCalling(type):\n"
        "    __call__ = staticmethod(functools.wraps(object.__init__)(build))\n"
        "\n"
        "class MethodWrapperBuilt:\n"
        "    __init__ = staticmethod(object().__init__)\n"
        "\n"
        "class ClassmethodDescriptorBuilt:\n"
        "    __init__ = Giver(dict.__dict__['fromkeys'])\n"
        "\n"
        "class WrapperBuilt:\n"
        "    __init__ = staticmethod(functools.wraps(object.__init__)(build))\n",
    )
    signing_over_c = imported_module(
        tmp_path,
        monkeypatch,
        "signing_over_c",
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "import binding_in_c\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class MethodWrapperCalled(metaclass=binding_in_c.MethodWrapperCalling):\n"
        "    __signature__ = signature\n"
        "\n"
        "class ClassmethodDescriptorCalled(metaclass=binding_in_c.ClassmethodDescriptorCalling):\n"
        "    __signature__ = signature\n"
        "\n"
        "class WrapperCalled(metaclass=binding_in_c.WrapperCalling):\n"
        "    __signature__ = signature\n"
        "\n"
        "class MethodWrapperRebuilt(binding_in_c.MethodWrapperBuilt):\n"
        "    __signature__ = signature\n"
        "\n"
        "class ClassmethodDescriptorRebuilt(binding_in_c.ClassmethodDescriptorBuilt):\n"
        "    __signature__ = signature\n"
        "\n"
        "class WrapperRebuilt(binding_in_c.WrapperBuilt):\n"
        "    __signature__ = signature\n",
    )
    cls = getattr(signing_over_c, name)

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        assert named_classes(subject) == {decimal.Decimal}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("CopiedCalled", id="metaclass-call"),
        pytest.param("CopiedInitialised", id="init"),
    ],
)
def test_a_class_that_carries_the_very_signature_a_link_of_its_constructor_chain_carries_over_a_callable_defined_in_c_names_the_classes_that_signature_names_read_where_the_link_given_it_is_spelled(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(tmp_path, monkeypatch, "linkcalling", _LINKCALLING_SOURCE)
    linksigning = imported_module(
        tmp_path,
        monkeypatch,
        "linksigning",
        "from decimal import Decimal as Share\n"
        "\n"
        "from linkcalling import LinkCalling, LinkInitialised, wrapper\n"
        "\n"
        "class CopiedCalled(metaclass=LinkCalling):\n"
        "    __signature__ = wrapper.__signature__\n"
        "\n"
        "class CopiedInitialised(LinkInitialised):\n"
        "    __signature__ = wrapper.__signature__\n",
    )
    cls = getattr(linksigning, name)

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        assert named_classes(subject) == {fractions.Fraction}


@pytest.mark.parametrize(
    ("link", "naming_the_link_the_string_and_the_reason"),
    [
        pytest.param(
            "functools.partial(object.__init__)",
            r"\bfunctools\.partial\(<slot wrapper '__init__' of 'object' objects>\).*'Share'.*"
            r"\brecords no module of its own\b",
            id="partial",
        ),
        pytest.param(
            "functools.wraps(wrapper)(_relayed)",
            r"\blinkcalling\.object\.__init__\b.*'Share'.*"
            r"\bwraps a callable that carries a signature of its own\b",
            id="wrapper-of-a-signed-link",
        ),
    ],
)
@pytest.mark.parametrize(
    "name",
    [
        pytest.param("CopiedCalled", id="metaclass-call"),
        pytest.param("CopiedInitialised", id="init"),
    ],
)
def test_a_class_that_carries_the_very_signature_a_link_of_its_constructor_chain_carries_over_a_callable_defined_in_c_raises_type_error_for_a_string_annotation_naming_that_link_if_it_records_no_module_or_wraps_a_link_carrying_a_signature_of_its_own(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    link: str,
    naming_the_link_the_string_and_the_reason: str,
) -> None:
    imported_module(tmp_path, monkeypatch, "linkcalling", _LINKCALLING_SOURCE)
    linksigning = imported_module(
        tmp_path,
        monkeypatch,
        "linksigning",
        "import functools\n"
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from linkcalling import wrapper\n"
        "\n"
        "def _relayed(receiver: 'Share', rate: int) -> None: ...\n"
        "\n"
        f"link = {link}\n"
        "link.__signature__ = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Calling(type):\n"
        "    __call__ = staticmethod(link)\n"
        "\n"
        "class Initialised:\n"
        "    __init__ = link\n"
        "\n"
        "class CopiedCalled(metaclass=Calling):\n"
        "    __signature__ = link.__signature__\n"
        "\n"
        "class CopiedInitialised(Initialised):\n"
        "    __signature__ = link.__signature__\n",
    )
    cls = getattr(linksigning, name)

    class Inheriting(cls):
        pass

    for subject in (cls, Inheriting):
        with pytest.raises(TypeError, match=naming_the_link_the_string_and_the_reason):
            named_classes(subject)


@pytest.mark.parametrize(
    "names",
    [
        pytest.param(("OwnCalled", "DerivedCalled", "ClassedCalled"), id="metaclass-call"),
        pytest.param(("OwnInitialised", "DerivedInitialised", "ClassedInitialised"), id="init"),
    ],
)
def test_a_signature_a_class_carries_over_a_constructor_whose_chain_holds_a_link_carrying_a_signature_of_its_own_over_a_callable_defined_in_c_raises_type_error_for_a_string_annotation_naming_the_class_the_link_the_string_and_that_it_may_be_a_copy(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, names: tuple[str, str, str]
) -> None:
    imported_module(tmp_path, monkeypatch, "linkcalling", _LINKCALLING_SOURCE)
    linksigning = imported_module(
        tmp_path,
        monkeypatch,
        "linksigning",
        "import decimal\n"
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from linkcalling import LinkCalling, LinkInitialised, wrapper\n"
        "\n"
        "own = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "derived = wrapper.__signature__.replace(return_annotation=None)\n"
        "classed = inspect.Signature(\n"
        "    [\n"
        "        inspect.Parameter(\n"
        "            'share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=decimal.Decimal\n"
        "        )\n"
        "    ]\n"
        ")\n"
        "\n"
        "class OwnCalled(metaclass=LinkCalling):\n"
        "    __signature__ = own\n"
        "\n"
        "class DerivedCalled(metaclass=LinkCalling):\n"
        "    __signature__ = derived\n"
        "\n"
        "class ClassedCalled(metaclass=LinkCalling):\n"
        "    __signature__ = classed\n"
        "\n"
        "class OwnInitialised(LinkInitialised):\n"
        "    __signature__ = own\n"
        "\n"
        "class DerivedInitialised(LinkInitialised):\n"
        "    __signature__ = derived\n"
        "\n"
        "class ClassedInitialised(LinkInitialised):\n"
        "    __signature__ = classed\n",
    )
    own, derived, classed = names

    for name in (own, derived):
        holder = getattr(linksigning, name)

        class Inheriting(holder):
            pass

        naming_the_holder_the_string_the_link_and_the_reason = (
            rf"\blinksigning\.{name}\b.*'Share'.*\blinkcalling\.object\.__init__\b.*\bmay be a copy\b"
        )
        for subject in (holder, Inheriting):
            with pytest.raises(TypeError, match=naming_the_holder_the_string_the_link_and_the_reason):
                named_classes(subject)
    assert named_classes(getattr(linksigning, classed)) == {decimal.Decimal}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("CopiedCalled", id="metaclass-call"),
        pytest.param("CopiedInitialised", id="init"),
    ],
)
def test_a_class_that_carries_the_very_signature_a_link_of_its_constructor_chain_carries_over_a_callable_defined_in_c_names_the_classes_that_signature_names_read_where_the_link_given_it_is_spelled_though_the_metaclass_of_the_class_holding_it_gives_that_class_another_signature(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(tmp_path, monkeypatch, "linkcalling", _LINKCALLING_SOURCE)
    metasigning = imported_module(tmp_path, monkeypatch, "metasigning", _METASIGNING_SOURCE)
    holder = getattr(metasigning, name)

    class Unsigning(type(holder)):
        __signature__ = None

    class Shadowing(holder, metaclass=Unsigning):
        pass

    assert named_classes(Shadowing) == {fractions.Fraction}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("OwnCalled", id="metaclass-call"),
        pytest.param("OwnInitialised", id="init"),
    ],
)
def test_a_class_that_carries_a_signature_of_its_own_over_a_constructor_whose_chain_holds_a_link_carrying_one_over_a_callable_defined_in_c_raises_type_error_for_a_string_annotation_naming_the_class_holding_it_the_link_the_string_and_that_it_may_be_a_copy_though_the_metaclass_of_that_class_gives_it_the_signature_of_that_link(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(tmp_path, monkeypatch, "linkcalling", _LINKCALLING_SOURCE)
    metasigning = imported_module(tmp_path, monkeypatch, "metasigning", _METASIGNING_SOURCE)
    holder = getattr(metasigning, name)

    class Unsigning(type(holder)):
        __signature__ = None

    class Shadowing(holder, metaclass=Unsigning):
        pass

    with pytest.raises(
        TypeError,
        match=rf"\bmetasigning\.{name}\b.*'Share'.*\blinkcalling\.object\.__init__\b.*\bmay be a copy\b",
    ):
        named_classes(Shadowing)


@pytest.mark.parametrize("wrap", CLASSMETHOD_WRAPPEES_BOUND_BY_MINOR)
def test_a_class_that_carries_a_signature_over_a_classmethod_constructor_whose_binding_differs_by_minor_names_the_classes_that_signature_names(
    wrap: Callable[[Callable[..., object]], object],
) -> None:
    def build(receiver: object, rate: int) -> None: ...

    signature = inspect.Signature(
        [inspect.Parameter("rate", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=int)]
    )

    class Initialised:
        __signature__ = signature
        __init__ = classmethod(wrap(build))

    class Created:
        __signature__ = signature
        __new__ = classmethod(wrap(build))

    class Calling(type):
        __call__ = classmethod(wrap(build))

    class Called(metaclass=Calling):
        __signature__ = signature

    for cls in (Initialised, Created, Called):
        assert surface_form(cls) == "(rate: int)"
        assert named_classes(cls) == {int}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("Initialised", id="init"),
        pytest.param("Called", id="metaclass-call"),
    ],
)
def test_a_functools_partial_constructor_of_a_class_that_carries_a_signature_is_read_unbound_without_a_warning_and_names_the_classes_the_module_of_the_function_it_wraps_binds_the_names_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    imported_module(
        tmp_path,
        monkeypatch,
        "partialling",
        "from fractions import Fraction as Share\n"
        "\n"
        "def settle(self, share: 'Share', rate: int) -> None: ...\n",
    )
    repartialling = imported_module(
        tmp_path,
        monkeypatch,
        "repartialling",
        "import functools\n"
        "import inspect\n"
        "from decimal import Decimal as Share\n"
        "\n"
        "from partialling import settle\n"
        "\n"
        "signature = inspect.Signature(\n"
        "    [inspect.Parameter('share', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Share')]\n"
        ")\n"
        "\n"
        "class Settling(type):\n"
        "    __call__ = functools.partial(settle, rate=1)\n"
        "\n"
        "class Initialised:\n"
        "    __signature__ = signature\n"
        "    __init__ = functools.partial(settle, rate=1)\n"
        "\n"
        "class Called(metaclass=Settling):\n"
        "    __signature__ = signature\n",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        classes = named_classes(getattr(repartialling, name))

    assert classes == {fractions.Fraction}
