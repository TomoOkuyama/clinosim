"""Unit tests for clinosim.audit.registry — register / discover / get_registered."""

from __future__ import annotations

import pytest

from clinosim.audit.registry import (
    ModuleAuditSpec,
    _reset_for_test,
    discover,
    get_registered,
    register_audit_module,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    _reset_for_test()
    yield
    _reset_for_test()


@pytest.mark.unit
def test_register_then_retrieve():
    spec = ModuleAuditSpec(name="hai")
    register_audit_module(spec)
    assert get_registered() == {"hai": spec}


@pytest.mark.unit
def test_register_last_wins():
    s1 = ModuleAuditSpec(name="hai", canonical_constants={"x": ("a",)})
    s2 = ModuleAuditSpec(name="hai", canonical_constants={"x": ("b",)})
    register_audit_module(s1)
    register_audit_module(s2)
    assert get_registered()["hai"].canonical_constants == {"x": ("b",)}


@pytest.mark.unit
def test_get_registered_returns_copy():
    register_audit_module(ModuleAuditSpec(name="hai"))
    snapshot = get_registered()
    snapshot["other"] = ModuleAuditSpec(name="other")
    assert "other" not in get_registered()


@pytest.mark.unit
def test_discover_imports_existing_audit_modules():
    # No clinosim.modules.<name>.audit yet at Task 1 — but discover must
    # NOT raise even if zero matches are found.
    discover()
    # No assertion on registry contents; the contract is "no errors".
