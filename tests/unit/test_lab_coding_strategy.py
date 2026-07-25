"""Unit tests for the JP-CLINS lab coding strategy dispatcher.

PR 1 scope: pin the interface + strategy dispatch + PR 1 invariants
(byte-identical delegation, LocalCode always None, InfectionLabo
raises). PR 3 will add tests for the CoreLabo real emit +
LocalCode activation."""

from __future__ import annotations

import pytest

from clinosim.modules.output._lab_coding_strategy import (
    CoreLaboStrategy,
    InfectionLaboStrategy,
    LabCodingKind,
    LegacyJSLMStrategy,
    LegacyLOINCStrategy,
    UncodedStrategy,
    _classify_analyte,
    select_lab_coding_strategy,
)

# --------------------------------------------------------------------------- #
# LabCodingKind enum stability


def test_kind_enum_membership_is_fixed_for_migration():
    """The enum members are the fixed set for the JP-CLINS migration
    chain (PR 1..5). Adding a new member requires a matching strategy
    in the same PR — see module docstring. This test locks the exact
    member set so accidental additions surface immediately."""
    assert set(LabCodingKind) == {
        LabCodingKind.CORELABO_JLAC10,
        LabCodingKind.INFECTION_LABO_JLAC10,
        LabCodingKind.UNCODED,
        LabCodingKind.LEGACY_JSLM,
        LabCodingKind.LEGACY_LOINC,
    }


# --------------------------------------------------------------------------- #
# PR 1 invariant: emit_localcode_coding returns None on EVERY strategy


@pytest.mark.parametrize(
    "strategy_cls",
    [LegacyJSLMStrategy, LegacyLOINCStrategy, CoreLaboStrategy, UncodedStrategy, InfectionLaboStrategy],
)
def test_pr1_invariant_emit_localcode_coding_returns_none(strategy_cls):
    """CRITICAL: byte-identical guarantee depends on this. If any
    strategy starts returning a LocalCode coding in PR 1..2, downstream
    ``code.coding[]`` will grow by one element and every JP Observation
    NDJSON line will shift, breaking the migration chain's bisect
    ability. PR 3 will flip specific strategies to non-None; this
    test's expected value moves at that time."""
    strategy = strategy_cls()
    result = strategy.emit_localcode_coding(lab_name="WBC", order={}, result={}, country="JP")
    assert result is None, f"{strategy_cls.__name__}.emit_localcode_coding returned non-None in PR 1: {result!r}"


# --------------------------------------------------------------------------- #
# Dispatcher: PR 1 classifier placeholder returns LEGACY_* for every input


@pytest.mark.parametrize("country", ["JP", "jp"])
def test_classifier_returns_legacy_jslm_for_jp(country):
    """PR 1: any analyte on any accepted JP country string routes to
    LEGACY_JSLM. Country string acceptance follows the shared
    ``is_us`` predicate — the classifier is JP-else-US, so ``JP`` and
    anything the codebase doesn't classify as US (e.g. ``Japan``) both
    reach LEGACY_JSLM. Only strict ``US`` / ``us`` diverge."""
    assert _classify_analyte("WBC", country) == LabCodingKind.LEGACY_JSLM
    assert _classify_analyte("Glucose", country) == LabCodingKind.LEGACY_JSLM
    assert _classify_analyte("SomeUnknownAnalyte", country) == LabCodingKind.LEGACY_JSLM


@pytest.mark.parametrize("country", ["US", "us"])
def test_classifier_returns_legacy_loinc_for_us(country):
    """Only strict ``US`` / ``us`` route to LEGACY_LOINC; the shared
    ``is_us`` predicate does not accept ``United States`` as US."""
    assert _classify_analyte("WBC", country) == LabCodingKind.LEGACY_LOINC
    assert _classify_analyte("SomeUnknownAnalyte", country) == LabCodingKind.LEGACY_LOINC


def test_select_returns_singleton_strategy_per_kind():
    """Strategies are cached (module-level singletons in
    ``_STRATEGIES``). Repeated calls must return the same instance so
    stateful behaviors added in PR 3 (e.g. LRU-cached lookups) don't
    fragment across per-call instances."""
    s1 = select_lab_coding_strategy("WBC", "JP")
    s2 = select_lab_coding_strategy("Glucose", "JP")
    assert s1 is s2  # same LEGACY_JSLM singleton
    assert s1.kind == LabCodingKind.LEGACY_JSLM


# --------------------------------------------------------------------------- #
# LegacyJSLMStrategy: primary emit shape (byte-identical baseline)


def test_legacy_jslm_emits_jslm_primary_for_mapped_analyte():
    """When ``lab_name`` is in ``code_mapping_lab.yaml`` (JP), the
    primary coding uses ``urn:oid:1.2.392.200119.4.1005`` (JSLM
    generic OID) + the mapped 5-digit code. Fixed against real
    production data by baseline sha256 pin — see PR body docs."""
    s = LegacyJSLMStrategy()
    codings = s.emit_codings(lab_name="WBC", order={}, result={}, country="JP")
    assert len(codings) >= 1
    primary = codings[0]
    assert primary["system"] == "urn:oid:1.2.392.200119.4.1005"
    assert primary["code"], "primary code must be non-empty for a mapped analyte"


def test_legacy_jslm_appends_loinc_secondary_when_us_mapping_exists():
    """JP dual coding: LOINC secondary is appended when the US-side
    ``code_mapping_lab.yaml`` has a value for the same ``lab_name`` and
    it differs from the JP primary."""
    s = LegacyJSLMStrategy()
    codings = s.emit_codings(lab_name="WBC", order={}, result={}, country="JP")
    systems = [c["system"] for c in codings]
    assert "http://loinc.org" in systems, "expected LOINC secondary on WBC (has US mapping)"


def test_legacy_jslm_fallback_to_order_code_when_unmapped():
    """Unmapped ``lab_name`` falls back to ``order.order_code`` under
    LOINC — the pre-refactor behavior. Tagging an arbitrary code under
    ``jlac10`` would produce an incoherent coding (matches the
    ``_bb_microbiology`` culture-code resolution rule)."""
    s = LegacyJSLMStrategy()
    codings = s.emit_codings(lab_name="TotallyUnknownAnalyte", order={"order_code": "12345-6"}, result={}, country="JP")
    assert codings[0]["system"] == "http://loinc.org"
    assert codings[0]["code"] == "12345-6"


# --------------------------------------------------------------------------- #
# LegacyLOINCStrategy: US primary (no secondary)


def test_legacy_loinc_emits_single_loinc_primary():
    s = LegacyLOINCStrategy()
    codings = s.emit_codings(lab_name="WBC", order={}, result={}, country="US")
    assert len(codings) == 1, "US primary must be a single coding, no secondary"
    assert codings[0]["system"] == "http://loinc.org"


# --------------------------------------------------------------------------- #
# CoreLaboStrategy: PR 1 wrapper delegates to LegacyJSLM


def test_corelabo_pr1_delegates_to_legacy_jslm():
    """PR 1: CoreLaboStrategy is a thin wrapper over LegacyJSLM to
    preserve byte-identical output. PR 3 replaces the delegation with
    real 17-digit code selection."""
    core = CoreLaboStrategy()
    legacy = LegacyJSLMStrategy()
    kwargs = {"lab_name": "WBC", "order": {}, "result": {}, "country": "JP"}
    assert core.emit_codings(**kwargs) == legacy.emit_codings(**kwargs)


# --------------------------------------------------------------------------- #
# UncodedStrategy + InfectionLaboStrategy: not implemented in PR 1


def test_uncoded_strategy_raises_in_pr1():
    """PR 1: UncodedStrategy is not routed to by the classifier.
    Explicit raise beats silent Uncoded emission if a call site ever
    reaches here."""
    s = UncodedStrategy()
    with pytest.raises(NotImplementedError, match="not activated in PR 1"):
        s.emit_codings(lab_name="X", order={}, result={}, country="JP")


def test_infection_labo_strategy_raises_with_spec_violation_note():
    """InfectionLaboStrategy MUST raise NotImplementedError, not fall
    back to Uncoded. Falling back would be a JP-CLINS spec violation
    (「感染症 5 項目該当なら共有項目 JLAC code 必須」). See TODO
    T67-I1 / T67-M1. The error message must mention the spec-violation
    rationale so future readers understand why the raise is deliberate
    rather than a stub-to-be-completed-with-Uncoded-fallback."""
    s = InfectionLaboStrategy()
    with pytest.raises(NotImplementedError) as exc_info:
        s.emit_codings(lab_name="HBs_Ag", order={}, result={}, country="JP")
    msg = str(exc_info.value)
    assert "spec violation" in msg
    assert "T67-I1" in msg or "T67-M1" in msg
