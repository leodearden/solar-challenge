# Surface Forms: What inspect Reads Differently by Python Minor

**Task:** #1103
**Code:** [`tests/_surface_forms.py`](../tests/_surface_forms.py)'s `surface_form`, `member_forms` and `named_classes`, and [`tests/_surface_forms_signatures.py`](../tests/_surface_forms_signatures.py), which holds their refusals
**Test:** [`tests/unit/surface_forms_helper/`](../tests/unit/surface_forms_helper/)

---

## 1. Why the Helper Keeps This List

`surface_form` spells a public name's form alike on every Python minor that
`requires-python` admits, 3.11 to 3.14, so the frozen-surface lock,
`tests/unit/test_public_api_surface.py`, pins one text on every interpreter. It reads
signatures through `inspect`, which reads some objects differently from one minor to the
next. For each such object, `surface_form` either reads it as one minor does, on every
minor (§3), or raises `TypeError` naming what `inspect` reads that way and saying what to
do instead (§4). Both rest on the chain `inspect` follows from a routine, which is the same
on every minor (§2). `named_classes`, which gives the classes a form names, reads each
string annotation in the module that spells it, and raises `TypeError` where that module
could differ by minor (4.2). `member_forms`, which spells the public members a class's own
body defines, raises `TypeError` for one that is a `functools.partial` (4.4, 4.6). Each
entry says how each minor reads its objects, and names the rule tests that pin what
`surface_form`, `member_forms` and `named_classes` do. Each `TypeError` also states its
own case's reading.

The readings were measured on CPython 3.11.15, 3.12.3, 3.13.9 and 3.14.4 on 2026-10-25,
and those of 4.6 again on those releases and on 3.11.17 on 2026-10-26, as §6 says. 4.5's
reading of a constructor read through an object its class makes callable was measured on
CPython 3.11.15, 3.11.17, 3.12.3, 3.13.9 and 3.14.4 on 2026-10-26, 4.2's reading of a
class's constructor and 3.3's reading on those releases on 2026-10-27, and 4.4's reading
of a class member that is a `functools.partial` and 4.1's reading of a constructor
`inspect` binds as a `classmethod` or through a descriptor on those releases on
2026-10-28. A new refusal gets its rule test first, then its entry here.

## 2. The Chain inspect Follows, on Every Minor

From a routine, `inspect` follows a bound method to its `__func__`, a wrapper to the
callable it records as `__wrapped__`, as `functools.wraps` records one, and a
`functools.partial` to its `func`. It stops at a link that carries a `__signature__`, and
reads an `inspect.Signature` there as given. A wrapper whose `__signature__` is `None`,
whether a link of a routine's chain or a class's constructor, it reads as the callable it
is, not as what it wraps, so no refusal looks past it; a `functools.partial` whose
`__signature__` is `None` is still read through its `func`. An object its class makes
callable, at the chain's end, is read through the `__call__` that class resolves, bound to
the object, unless the object carries a signature.

Pinned by:
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_that_carries_a_signature_of_none_is_spelled_by_its_own_signature_whatever_it_wraps`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_constructor_wraps_a_callable_defined_in_c_but_carries_a_signature_of_none_is_spelled_by_that_constructor`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_that_wraps_a_refused_class_raises_the_type_error_naming_that_class`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_whose_chain_ends_at_an_object_its_class_makes_callable_is_spelled_by_the_call_its_class_resolves_bound_to_it_or_by_the_signature_that_object_carries`

## 3. Read Alike on Every Minor

### 3.1 A `functools.partial` is a routine

`inspect.isroutine` counts a `functools.partial` as a routine on 3.14, and not on 3.11,
3.12 or 3.13. `surface_form` counts one on every minor, as 3.14 does, so a partial is
spelled by the signature it leaves of the callable it wraps. 4.6 says how a partial whose
type takes `__get__` from a class other than `functools.partial` is read instead.

Pinned by:
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_partial_is_spelled_by_the_signature_it_leaves_of_the_callable_it_wraps`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_functools_partial_subclass_whose_type_defines_delete_is_still_a_routine_spelled_by_the_signature_it_leaves`

### 3.2 A descriptor whose type defines `__get__` and `__delete__` but no `__set__` is no routine

`inspect.ismethoddescriptor` and `inspect.isroutine` count such a descriptor on 3.11 and
3.12, and neither does from 3.13; `inspect.isdatadescriptor` counts it on every minor.
`surface_form` counts none as a routine, as 3.13 does, so such a descriptor is a constant,
spelled by its type's qualified name.

Pinned by:
- `tests/unit/surface_forms_helper/test_surface_form_grammar.py::test_a_descriptor_whose_type_defines_get_and_delete_but_no_set_is_a_constant_spelled_by_its_type_qualified_name`

### 3.3 A `__new__` defined with `def` beside a `functools.partial` `__init__`

Where `inspect` reads a class's `__new__`, defined with `def`, in place of an `__init__`
that is a `functools.partial`, the class's own or a base's, every minor reads the class
alike, by that `__new__`: with `def __new__(cls, rate: int) -> object` beside
`__init__ = functools.partial(build)` and `def build(self, rate: int)`, it reads as
`(rate: int) -> object`. Every minor looks up that `__init__` too, before it chooses which
of the two to read. 3.13 and 3.14 bind it there, with `inspect._descriptor_get`: 3.13's
`functools.partial.__get__` warns `FutureWarning`, and 3.14's binds it as a method without
a warning. 3.11 and 3.12's `functools.partial` defines no `__get__`, so neither binds it.
`signature_of` ignores that one warning, from `inspect` alone, while `inspect` reads a
signature, so `surface_form` and `named_classes` warn on no minor. A `functools.partial`
held as an `__init__` that `inspect` reads is refused before it is read, as 4.5 says.

Pinned by:
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_init_is_a_partial_beside_a_new_defined_with_def_is_spelled_by_that_new_without_a_warning`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_inherited_init_is_a_partial_beside_its_own_new_defined_with_def_is_spelled_by_that_new_without_a_warning`

## 4. Refused

### 4.1 A `__signature__` that is neither `None` nor an `inspect.Signature`

3.12 and 3.13 convert a string given as `__signature__`, such as `'(rate)'`, and call a
callable given there; 3.11 and 3.14 raise `TypeError` for either, as an unexpected object
in `__signature__`. `surface_form` raises `TypeError` naming what carries it and that value
with its type: on the routine or class itself, on the link of a routine's chain where
`inspect` stops, and on the constructor `inspect` reads for a class, its metaclass
`__call__` included.

`inspect` binds the constructor it reads for a class before it reads it, on every minor,
as 4.5 says: a `__new__` as `getattr` gives it, and an `__init__` or a metaclass `__call__`
with `inspect._descriptor_get`. So the `__signature__` it meets there is on what that
binding gives: the function a `classmethod` holds, or what a descriptor's `__get__` gives.
With `def build(cls, rate: int)` carrying `'(cls, rate)'`, `classmethod(build)` held as
`__init__` or as a metaclass `__call__` reads as `(rate)` on 3.12 and 3.13, as does a
descriptor held there whose `__get__` gives a function carrying `'(rate)'`, and 3.11 and
3.14 raise `TypeError` for both. `surface_form` raises `TypeError` naming the class, that
constructor by the class holding it, as in `Built.__init__`, and that value with its type,
on every minor. A `__signature__` carried by the `classmethod` or the `staticmethod`
itself, or by a descriptor whose `__get__` gives another callable, is read on no minor, so
the class is spelled by what the binding gives: held as `__init__`, a `classmethod` that
carries `'(rate)'` over `def build(receiver: float, rate: int) -> None` reads as
`(rate: int) -> None` on every minor. A descriptor whose `__get__` gives itself, such as
the one 4.5 reads as a method descriptor, is still read through its own `__signature__`.

Pinned by:
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_raises_a_type_error_naming_what_carries_it_and_that_value`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_constructor_carries_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_raises_a_type_error_naming_it_that_constructor_and_that_value`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_classmethod_or_descriptor_constructor_gives_a_function_carrying_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_raises_a_type_error_naming_it_that_constructor_and_that_value`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_classmethod_staticmethod_or_descriptor_constructor_itself_carries_a_signature_attribute_that_is_neither_none_nor_an_inspect_signature_is_spelled_by_what_inspect_binds_it_to`

### 4.2 A routine that wraps an Enum, or a class constructor `inspect` reads as one

`inspect` reads an Enum's signature from `EnumType.__call__` on 3.11, from
`Enum.__signature__` on 3.12 and 3.13, and from `EnumType.__signature__` on 3.14. An Enum
with a member reads on 3.11 as
`(value, names=None, *, module=None, qualname=None, type=None, start=1, boundary=None)`,
and from 3.12 as `(*values)`. An Enum is spelled by its members; a routine that wraps one
raises `TypeError` naming it and that Enum, unless one of the routine's links carries a
signature.

A class whose constructor `inspect` reads as an Enum is read the same way. Its metaclass
`__call__`, `__new__` or `__init__`, bound as `inspect` binds it, may be the Enum itself
or a callable whose chain (§2) ends at it, as a `functools.wraps` wrapper of it does.
Where the Enum has a member, such a constructor defined with `def` reads on 3.11 as
`(names=None, *, module=None, qualname=None, type=None, start=1, boundary=None)`, the
Enum's signature less its first parameter, and from 3.12 as `(*values)`. On 3.12 and 3.13
the Enum's own `__signature__` is a bound method, which 4.1 would refuse on those minors
alone, so `surface_form` checks for the Enum first. It raises `TypeError` naming the
class, that constructor and that Enum on every minor, unless the class or one of the
constructor's links carries a signature; a `functools.partial` held as `__init__` or as a
metaclass `__call__` is refused first, by its binding, as 4.5 says.

Where a link of the routine's chain, or of the constructor's, carries a signature over
the Enum, `inspect` stops there on every minor (§2), so `surface_form` spells that
signature and `named_classes` names the classes it is annotated with. But that signature
may be a copy of the Enum's own, which each minor reads from a different place, so no
module is known to spell a string annotation in it: `named_classes` raises `TypeError`
naming that Enum and the string.

Pinned by:
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_that_wraps_an_enum_raises_a_type_error_naming_it_and_that_enum`
- `tests/unit/surface_forms_helper/test_named_classes_routine_chains.py::test_a_signature_a_link_carries_over_an_enum_names_the_classes_it_is_annotated_with`
- `tests/unit/surface_forms_helper/test_named_classes_routine_chains.py::test_a_string_annotation_in_a_signature_a_link_carries_over_an_enum_raises_type_error_naming_that_enum_and_the_string`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_constructor_inspect_reads_as_an_enum_raises_a_type_error_naming_it_that_constructor_and_that_enum`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_constructor_is_a_partial_of_an_enum_raises_the_type_error_naming_that_enum_as_new_and_the_one_for_its_binding_as_init_or_metaclass_call`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_constructor_wraps_an_enum_but_carries_a_signature_or_a_signature_of_none_is_spelled_by_what_inspect_reads`

### 4.3 A routine that wraps a descriptor whose type defines `__get__` and `__delete__` but no `__set__`

3.11 and 3.12 read such a descriptor as a method descriptor, by a text signature only a
routine defined in C gives, so they find none and raise `ValueError`; from 3.13 `inspect`
reads it as a data descriptor, through its type's `__call__`. `surface_form` raises
`TypeError` naming the routine, the descriptor and its type, unless the descriptor or one
of the routine's links carries a signature.

Pinned by:
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_that_wraps_a_descriptor_whose_type_defines_get_and_delete_but_no_set_raises_a_type_error_naming_it_that_descriptor_and_its_type`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_that_wraps_a_descriptor_whose_type_defines_set_or_no_get_or_that_carries_a_signature_is_spelled_by_the_signature_inspect_reads_for_it`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_that_wraps_a_descriptor_whose_type_defines_get_and_delete_but_no_set_is_spelled_by_the_signature_one_of_its_links_carries`

### 4.4 A routine whose chain ends at an object its class makes callable, or a class member that is a `functools.partial`

`inspect` reads such an object through the `__call__` its class resolves, unless the
object carries a signature (§2). Each other refusal of this section, and `surface_form`'s
refusal of a routine whose signature `inspect` cannot read, applies to that `__call__` as
to the routine, and names the routine. Three readings of the object differ by minor:

- A class in the object's type's MRO defines `__call__` in C. From 3.13 `inspect` reads a
  `__text_signature__` such a class gives its instances in place of the `__call__` their
  type resolves, which it reads on 3.11 and 3.12. `operator.itemgetter(1)` reads as
  `(*args, **kwargs)` on 3.11 and 3.12 and as `(obj, /)` from 3.13; an instance of a
  subclass of `sqlite3.Connection` that defines its own `__call__` reads as that `__call__`
  on 3.11 and 3.12 and as `(sql, /)` from 3.13. `surface_form` raises `TypeError` naming
  the routine, the object and that class.
- The object carries a `__text_signature__`: `inspect` reads it in place of the `__call__`
  from 3.13, and reads the `__call__` on 3.11 and 3.12. `surface_form` raises `TypeError`
  naming the routine, the object and that text.
- The `__call__` the object's class resolves is a `functools.partial`: 3.14 binds it to the
  object as a method, so its first parameter goes, while 3.11 to 3.13 call it without the
  object, 3.13 warning `FutureWarning`. 3.14 binds a signature that partial carries the
  same way, so that signature does not lift the refusal. `surface_form` raises `TypeError`
  naming the routine and that `__call__`. A partial whose type takes `__get__` from a class
  other than `functools.partial` binds by that `__get__` instead, as 4.6 says.

The section's other case is a class member that is a `functools.partial`. Read from an
instance, it is bound as a partial `__call__` is: 3.14 binds it to the instance as a
method, so its first parameter goes, while 3.11 to 3.13 call it without the instance, 3.13
warning `FutureWarning`. `member_forms` raises `TypeError` naming the class, the member
and that binding. Wrapped in `staticmethod`, which gives the partial itself on every
minor, it is spelled `staticmethod`, then the signature the partial leaves.

Pinned by:
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_whose_chain_ends_at_an_object_its_class_makes_callable_raises_the_type_error_the_call_it_is_read_through_raises_naming_the_routine`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_whose_chain_ends_at_an_object_whose_call_wraps_a_refused_class_raises_the_type_error_naming_that_class`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_whose_chain_ends_at_an_object_a_class_defined_in_c_makes_callable_raises_a_type_error_naming_it_that_object_and_that_class`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_whose_chain_ends_at_an_object_whose_class_overrides_a_call_a_base_defines_in_c_raises_a_type_error_naming_it_that_object_and_that_base`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_whose_chain_ends_at_an_object_that_carries_a_text_signature_raises_a_type_error_naming_it_that_object_and_that_text`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_whose_chain_ends_at_an_object_whose_class_resolves_a_partial_as_call_raises_a_type_error_naming_it_and_that_call_without_binding_the_partial`
- `tests/unit/surface_forms_helper/test_member_forms.py::test_a_partial_member_raises_a_type_error_naming_the_class_the_member_and_that_only_python_3_14_binds_it_to_the_instance`
- `tests/unit/surface_forms_helper/test_member_forms.py::test_a_partial_member_wrapped_in_staticmethod_is_spelled_staticmethod_then_the_signature_the_partial_leaves`

### 4.5 A class whose constructor inspect reads differently by minor, or cannot read on any

Such a class raises `TypeError` naming it and the class holding that constructor, or,
where `inspect` reads that constructor through an object its class makes callable, naming
it and what 4.4's `TypeError` names besides the routine, unless the class carries a
signature, which `inspect` reads in that constructor's place. A routine that wraps such a
class, through a `functools.partial`, a bound method or a `functools.wraps` wrapper,
raises the same, unless the class or one of the routine's links carries a signature.
`signature_of`'s docstring in `tests/_surface_forms_signatures.py` points at the list of
the constructors refused, in the order they are checked. A constructor can meet the
readings of 4.1, 4.2 and 4.3, and that of 4.4's partial: 3.14 binds a `functools.partial`
held as `__init__` or as a metaclass `__call__`, dropping its first parameter, and 3.11 to
3.13 do not, 3.13 warning `FutureWarning`; 4.6 says how a partial whose type takes
`__get__` from a class other than `functools.partial` is refused there and as `__new__`.
The other readings are:

- A constructor that wraps a callable defined in C, as `functools.wraps(object.__new__)`
  records one: 3.11 and 3.12 read the wrapper through that callable, as
  `(*args, **kwargs)`, and from 3.13 `inspect` skips it as defined in C and reads the
  constructor after it. `warnings.deprecated`, new in 3.13, writes such a `__new__`.
- A descriptor whose type defines `__get__` in Python but neither `__set__` nor
  `__delete__`: every minor reads it as a method descriptor, finds no text signature and
  raises `ValueError`.
- A class constructed by a class defined in C: `inspect` reads its text signature, which a
  release of its package can add or rewrite. `dict` and `int` give none on any minor.
- A constructor read through an object its class makes callable. `inspect` reads a
  metaclass `__call__`, a `__new__` or an `__init__`, bound as it binds it, as it reads a
  routine (§2), so where that constructor is such an object, or a chain from it ends at
  one, `inspect` reads it through the `__call__` the object's class resolves, by the three
  readings 4.4 lists. For `__call__ = functools.partial(charge, rate=1)`, with
  `def charge(self, share, rate)`, an `__init__` or a metaclass `__call__` reads as
  `(self, share, *, rate=1)` on 3.11 to 3.13, 3.13 warning `FutureWarning`, and as
  `(share, *, rate=1)` on 3.14; held as `__new__`, it reads one parameter fewer on each
  minor. `operator.itemgetter(1)` as `__init__` reads as `(*args, **kwargs)` on 3.11 and
  3.12 and as `(obj, /)` from 3.13. A `__text_signature__` the object carries is read in
  place of its `__call__` from 3.13. `surface_form` raises the `TypeError` 4.4 raises,
  naming the class in the routine's place, unless the object or the class carries a
  signature.

Pinned by:
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_init_is_a_partial_raises_a_type_error_naming_it_and_the_class_holding_the_partial`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_init_is_a_partial_beside_a_new_defined_in_c_raises_the_type_error_naming_the_partial`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_metaclass_call_is_a_partial_raises_a_type_error_naming_it_and_that_call`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_new_or_init_wraps_a_callable_defined_in_c_raises_a_type_error_naming_it_that_constructor_and_that_callable`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_whose_metaclass_call_wraps_a_callable_defined_in_c_raises_a_type_error_naming_it_that_call_and_that_callable`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_decorated_with_warnings_deprecated_raises_the_type_error_naming_the_new_it_writes`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_constructed_through_a_descriptor_inspect_reads_as_a_builtin_raises_a_type_error_naming_it_that_constructor_and_the_descriptor_type`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_constructed_through_a_descriptor_that_carries_a_signature_or_whose_get_gives_a_function_is_spelled_by_what_inspect_reads`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_constructed_by_a_class_defined_in_c_raises_a_type_error_naming_it_and_that_class`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_constructed_through_an_object_whose_class_resolves_a_partial_as_call_raises_a_type_error_naming_it_and_that_call_without_binding_the_partial`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_constructed_through_an_object_its_class_makes_callable_raises_the_type_error_a_routine_whose_chain_ends_at_that_object_raises_naming_the_class`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_constructed_through_an_object_its_class_makes_callable_is_spelled_by_the_call_its_class_resolves_bound_to_it_or_by_the_signature_that_object_carries`
- `tests/unit/surface_forms_helper/test_surface_form_constructors.py::test_a_class_that_carries_a_signature_is_spelled_by_that_signature_whatever_its_constructor`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_partial_of_a_refused_class_raises_the_type_error_naming_that_class`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_that_wraps_a_refused_class_raises_the_type_error_naming_that_class`
- `tests/unit/surface_forms_helper/test_surface_form_routine_chains.py::test_a_routine_that_wraps_a_class_but_carries_a_signature_is_spelled_by_that_signature`

### 4.6 A `functools.partial` whose type takes `__get__` from a class other than `functools.partial`

3.11 and 3.12 check whether an object is a method descriptor, one whose type has a
`__get__` and no `__set__`, before they check for a `functools.partial`, and
`functools.partial` defines no `__get__` before 3.13. So a partial whose type takes
`__get__` from another class, its own or a base on either side of `functools.partial` in
its MRO, and defines no `__set__`, reads there as a method descriptor, by a text signature
only a routine defined in C gives: by its `__text_signature__` if it carries one, else
with `ValueError`. A `__delete__` does not change that, since `inspect.ismethoddescriptor`
ignores it before 3.13, nor does a `__signature__` of `None`. 3.13 counts no partial as a
method descriptor, and 3.14 checks for a partial first, so both read it through its
`func`.

`surface_form` raises `TypeError` naming such a partial and its type wherever `inspect`
reads it: passed directly; as a link of a routine's chain, through `functools.wraps`, a
bound method or a plain partial that keeps it as its `func`; as a class's `__new__`, or
as what a descriptor's `__get__` gives as a class's `__init__` or an object's `__call__`;
and as a class member, which `member_forms` names with its class. A `__set__` its type
defines lifts the refusal, since 3.11 and 3.12 then read it as a partial too, and so does
a signature other than `None` it carries: an `inspect.Signature` reads alike, and a string
or callable meets 4.1. So does a `__wrapped__` it records, as `functools.update_wrapper`
records one, unless it also carries a `__signature__` of `None`: every minor follows that
`__wrapped__` before it reads the partial, as §2 says it follows any wrapper's, and reads
what the partial wraps. A plain partial of such a partial that holds no instance `__dict__`
takes its `func` and arguments as its own, so it reads alike.

Where `inspect` binds a partial through its type's `__get__`, as a class's `__init__` or
metaclass `__call__`, as the `__call__` an object's class resolves, or as a member, a
partial whose type takes `__get__` from a class other than `functools.partial` raises
`TypeError` naming its type, whatever its `__set__` or signature, in place of 4.4's and
4.5's clause, which says how `functools.partial`'s own `__get__` binds. How it binds
depends on the `__get__` its type resolves, which no rule reads. 3.11.15, 3.11.17 and
3.12.3 bind a constructor and a `__call__` through that `__get__`, with
`inspect._descriptor_get`, as 3.13 and 3.14 do. So a partial whose type defines `__set__`
and a `__get__` that binds it as a method reads alike on every minor there, and one whose
type defines no `__set__` still reads as a method descriptor on 3.11 and 3.12. A subclass
that lists `functools.partial` before the class it takes `__get__` from resolves
`functools.partial`'s own from 3.13, through which 3.13 calls it without the instance and
3.14 binds it. A member that 3.11 and 3.12 read as a method descriptor is refused with that
reading.

Pinned by:
- `tests/unit/surface_forms_helper/test_surface_form_getter_partials.py::test_a_partial_whose_type_takes_get_from_another_class_and_defines_no_set_raises_a_type_error_naming_it_and_its_type_wherever_inspect_reads_it`
- `tests/unit/surface_forms_helper/test_surface_form_getter_partials.py::test_a_partial_whose_type_takes_get_from_another_class_but_defines_set_or_carries_a_signature_is_spelled_by_the_signature_inspect_reads_for_it`
- `tests/unit/surface_forms_helper/test_member_forms.py::test_a_member_that_is_a_partial_whose_type_takes_get_from_another_class_and_defines_no_set_raises_a_type_error_naming_the_class_the_member_and_its_type`
- `tests/unit/surface_forms_helper/test_surface_form_getter_partials.py::test_a_class_or_call_bound_through_a_partial_whose_type_takes_get_from_another_class_raises_a_type_error_naming_that_type_instead_of_the_binding_of_a_partial`
- `tests/unit/surface_forms_helper/test_member_forms.py::test_a_member_that_is_a_partial_whose_type_takes_get_from_another_class_and_defines_set_raises_a_type_error_naming_the_class_the_member_and_that_type`
- `tests/unit/surface_forms_helper/test_surface_form_getter_partials.py::test_a_partial_whose_type_takes_get_from_another_class_but_carries_wrapped_is_spelled_by_the_signature_of_what_it_wraps`
- `tests/unit/surface_forms_helper/test_surface_form_getter_partials.py::test_a_plain_partial_of_a_partial_whose_type_takes_get_from_another_class_and_that_holds_no_instance_dict_is_spelled_by_the_func_and_arguments_it_takes_as_its_own`
- `tests/unit/surface_forms_helper/test_member_forms.py::test_a_member_that_is_a_partial_whose_type_takes_get_from_another_class_but_carries_wrapped_raises_the_type_error_for_its_binding`

## 5. When the Admitted Minors Change

On a newly admitted minor, re-measure each reading here (§6) and run the rule tests. An
entry whose readings no longer differ among the admitted minors no longer needs its
refusal or its normalization. 3.2, 4.3, the first two readings listed in 4.4, the first
listed in 4.5, 4.5's reading of a constructor read through an object its class makes
callable where it meets those two readings of 4.4, and the reading 4.6 refuses where
`inspect` reads a partial differ only between 3.11 and 3.12 on one side and 3.13 and 3.14
on the other, so they rest on 3.11 and 3.12 alone. The warning 3.3 ignores rests on 3.13
alone. 4.6's refusal where a partial is bound rests on no minor: it names a binding no
rule reads. Whether to lift one is for the task that changes `requires-python`.

## 6. How to Re-measure

Each minor's reading comes from its own environment, built offline from uv's cache:

    UV_OFFLINE=1 UV_PROJECT_ENVIRONMENT=/tmp/<dir>/venv-3.X UV_PYTHON=3.X \
        uv run --locked --extra dev python -I -c 'import functools, inspect; print(inspect.isroutine(functools.partial(print)))'

Use `UV_PYTHON=3.14+gil` for 3.14: a bare `3.14` can pick the free-threaded build. On the
pinned 3.12, a plain `uv run --locked --extra dev` uses the project's own environment.
The rule tests run the same way, with
`pytest tests/unit/surface_forms_helper -p no:cacheprovider` in place of
`python -I -c ...`.
