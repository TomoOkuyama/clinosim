"""Unit tests for chronic SOAP registry resolver (v9 density fix)."""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.document.narrative._chronic_soap import resolve_chronic_soap


def test_returns_none_for_empty_conditions():
    assert resolve_chronic_soap(None) is None
    assert resolve_chronic_soap([]) is None


def test_matches_i10_hypertension():
    tmpl = resolve_chronic_soap([SimpleNamespace(code="I10")])
    assert tmpl is not None
    assert "血圧" in tmpl["subjective_ja"]
    assert "本態性高血圧" in tmpl["assessment_ja"]


def test_matches_by_prefix_i10_9():
    """Sub-codes (I10.9 etc.) resolve to the I10 base entry."""
    tmpl = resolve_chronic_soap([SimpleNamespace(code="I10.9")])
    assert tmpl is not None
    assert "血圧" in tmpl["subjective_ja"]


def test_first_matching_condition_wins():
    """Order matters — earlier conditions get priority (assumed primary)."""
    tmpl = resolve_chronic_soap(
        [
            SimpleNamespace(code="E11"),  # diabetes — matches
            SimpleNamespace(code="I10"),  # hypertension — also matches, but second
        ]
    )
    assert tmpl is not None
    assert "糖尿病" in tmpl["assessment_ja"]
    assert "血糖" in tmpl["subjective_ja"]


def test_falls_through_when_no_prefix_matches():
    tmpl = resolve_chronic_soap([SimpleNamespace(code="Z99")])  # unmapped
    assert tmpl is None


def test_accepts_plain_string_codes():
    """Legacy fixtures may pass ICD codes as bare strings."""
    tmpl = resolve_chronic_soap(["J45"])
    assert tmpl is not None
    assert "喘息" in tmpl["assessment_ja"]


def test_accepts_dict_shape():
    """CIF JSON round-trip lands as dicts."""
    tmpl = resolve_chronic_soap([{"code": "N18"}])
    assert tmpl is not None
    assert "慢性腎臓病" in tmpl["assessment_ja"]


def test_all_registry_entries_have_four_slots():
    """Every registry entry must supply the full SOAP set to satisfy
    the OutpatientSoapTemplate shape."""
    from clinosim.modules.document.narrative._chronic_soap import _load_registry

    reg = _load_registry()
    required = {"subjective_ja", "objective_ja", "assessment_ja", "plan_ja"}
    for code, entry in reg.items():
        missing = required - set(entry.keys())
        assert not missing, f"registry entry {code} missing: {missing}"
