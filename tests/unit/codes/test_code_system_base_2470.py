"""One CodeSystem base class owns lookup, language selection and fallback
(code-mapping spec §2.3, Issue #2470)."""

from __future__ import annotations

import pytest

from clinosim.codes import CodeSystem, code_system, display, system_keys
from clinosim.codes.icd10 import Icd10CodeSystem

pytestmark = pytest.mark.unit


def _all_subclasses(cls: type) -> set[type]:
    found = set()
    for sub in cls.__subclasses__():
        found |= {sub} | _all_subclasses(sub)
    return found


def test_subclasses_do_not_override_the_shared_operations() -> None:
    for sub in _all_subclasses(CodeSystem):
        overridden = [op for op in CodeSystem.FINAL_OPERATIONS if op in vars(sub)]
        assert not overridden, (sub.__name__, overridden)


def test_every_registry_file_builds_one_instance() -> None:
    for key in system_keys():
        cs = code_system(key)
        if cs is None:
            continue
        assert isinstance(cs, CodeSystem)
        assert cs.key == key
        assert code_system(key) is cs


def test_icd10_systems_use_the_category_hook() -> None:
    for key in ("icd-10-cm", "icd-10", "icd-10-mhlw"):
        assert isinstance(code_system(key), Icd10CodeSystem)
    assert type(code_system("loinc")) is CodeSystem


def test_category_stands_in_for_an_unregistered_subcode() -> None:
    cs = code_system("icd-10-cm")
    assert cs is not None
    assert "E78" in cs.codes and "E78.99" not in cs.codes
    assert cs.parents("E78.99") == ("E78",)
    assert display("icd-10-cm", "E78.99", "en") == cs.codes["E78"]["en"]


def test_base_class_has_no_hierarchy() -> None:
    cs = CodeSystem(key="t", name="t", uri="urn:t", version="", codes={"A": {"en": "A"}})
    assert cs.parents("A.1") == ()
    assert cs.display("A", "ja") == "A"
    assert cs.display("B", "en") is None


def test_module_functions_delegate_to_the_instance() -> None:
    cs = code_system("snomed-ct")
    assert cs is not None
    code = next(iter(cs.codes))
    assert display("snomed-ct", code, "ja") == cs.display(code, "ja")
