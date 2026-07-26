"""Unit tests for the JP-CLINS lab coding strategy dispatcher.

PR 1 scope: interface + strategy dispatch + PR 1 invariants
(byte-identical delegation, LocalCode always None, InfectionLabo
raises).

PR 3a scope: real ``_classify_analyte`` + ``_ANALYTE_TO_SLICE_NAME``
+ ``_slice_name_for_analyte``. Dispatcher stays unchanged for
byte-identical guarantee — classifier is verified here alone and
never consumed by production code until PR 3b (CoreLabo) / PR 3c
(Uncoded)."""

from __future__ import annotations

import pytest

from clinosim.modules.output._lab_coding_strategy import (
    _ANALYTE_TO_SLICE_NAME,
    _KNOWN_UNCODED_ANALYTES,
    CoreLaboStrategy,
    InfectionLaboStrategy,
    LabCodingKind,
    LegacyJSLMStrategy,
    LegacyLOINCStrategy,
    UncodedStrategy,
    _classify_analyte,
    _slice_name_for_analyte,
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


# PR 3c (migration complete): CoreLabo + Uncoded now emit LocalCode
# co-slice. Legacy / InfectionLabo remain None (Legacy has no LocalCode
# semantics; InfectionLabo raises at emit_codings before LocalCode is
# consulted).


@pytest.mark.parametrize(
    "strategy_cls",
    [LegacyJSLMStrategy, LegacyLOINCStrategy, InfectionLaboStrategy],
)
def test_legacy_and_infection_strategies_never_emit_localcode(strategy_cls):
    """Legacy paths carry no LocalCode semantics; InfectionLabo raises
    at emit_codings so LocalCode is unreachable. Both return None
    forever (invariant, session 67 memo)."""
    strategy = strategy_cls()
    result = strategy.emit_localcode_coding(lab_name="WBC", order={}, result={}, country="JP")
    assert result is None


# --------------------------------------------------------------------------- #
# Dispatcher: PR 1 classifier placeholder returns LEGACY_* for every input


# --------------------------------------------------------------------------- #
# PR 3a classifier — expected classification for every JP analyte in
# current production data (32 unique lab_name values in v30 CIF).
# CoreLabo 20 (1,898 obs) + Uncoded 12 (611 obs) = 32 (2,509 obs).
# Glucose is INTENTIONALLY Uncoded — see T67-Glucose-disambig backlog.
_JP_EXPECTED_KIND: dict[str, LabCodingKind] = {
    # CoreLabo — 20 entries, each maps to a slice in _ANALYTE_TO_SLICE_NAME
    "Creatinine": LabCodingKind.CORELABO_JLAC10,
    "K": LabCodingKind.CORELABO_JLAC10,
    "Na": LabCodingKind.CORELABO_JLAC10,
    "WBC": LabCodingKind.CORELABO_JLAC10,
    "AST": LabCodingKind.CORELABO_JLAC10,
    "ALT": LabCodingKind.CORELABO_JLAC10,
    "CRP": LabCodingKind.CORELABO_JLAC10,
    "Hb": LabCodingKind.CORELABO_JLAC10,
    "BUN": LabCodingKind.CORELABO_JLAC10,
    "PT_INR": LabCodingKind.CORELABO_JLAC10,
    "BNP": LabCodingKind.CORELABO_JLAC10,
    "Plt": LabCodingKind.CORELABO_JLAC10,
    "Ca": LabCodingKind.CORELABO_JLAC10,
    "Albumin": LabCodingKind.CORELABO_JLAC10,
    "HbA1c": LabCodingKind.CORELABO_JLAC10,
    "TG": LabCodingKind.CORELABO_JLAC10,
    "HDL": LabCodingKind.CORELABO_JLAC10,
    "TC": LabCodingKind.CORELABO_JLAC10,
    "APTT": LabCodingKind.CORELABO_JLAC10,
    "D_dimer": LabCodingKind.CORELABO_JLAC10,
    # Uncoded — 12 entries, each in _KNOWN_UNCODED_ANALYTES
    "pH": LabCodingKind.UNCODED,
    "pCO2": LabCodingKind.UNCODED,
    "pO2": LabCodingKind.UNCODED,
    "HCO3": LabCodingKind.UNCODED,
    "Troponin_I": LabCodingKind.UNCODED,
    "CK_MB": LabCodingKind.UNCODED,
    "Lactate": LabCodingKind.UNCODED,
    "PCT": LabCodingKind.UNCODED,
    "TSH": LabCodingKind.UNCODED,
    "Fibrinogen": LabCodingKind.UNCODED,
    "eGFR": LabCodingKind.UNCODED,
    "Glucose": LabCodingKind.UNCODED,
}


@pytest.mark.parametrize("lab_name,expected_kind", list(_JP_EXPECTED_KIND.items()))
def test_classify_analyte_jp_matches_expected_kind(lab_name, expected_kind):
    """Pins the CoreLabo / Uncoded classification for every JP analyte
    currently emitted (v30 CIF, 32 unique lab_name values). If a value
    here starts producing an unexpected kind, either the classification
    map has drifted or a data-pipeline change (e.g. T67-Glucose-disambig)
    should update this table intentionally — never silently."""
    assert _classify_analyte(lab_name, "JP") == expected_kind


def test_classify_analyte_unknown_jp_defaults_to_uncoded():
    """Unmapped JP analyte routes to UNCODED — safe-side fallback that
    does NOT resurrect the pre-migration LEGACY_JSLM path. PR 3c will
    activate UncodedStrategy dispatch; PR 3a keeps this as a return-value
    contract only."""
    assert _classify_analyte("SomeUnknownAnalyteNotInAnyList", "JP") == LabCodingKind.UNCODED


@pytest.mark.parametrize("country", ["US", "us"])
def test_classify_analyte_us_returns_legacy_loinc(country):
    """Only strict ``US`` / ``us`` route to LEGACY_LOINC; the shared
    ``is_us`` predicate does not accept ``United States`` as US."""
    assert _classify_analyte("WBC", country) == LabCodingKind.LEGACY_LOINC
    assert _classify_analyte("SomeUnknownAnalyte", country) == LabCodingKind.LEGACY_LOINC


# --------------------------------------------------------------------------- #
# _slice_name_for_analyte — clinosim IP mapping


@pytest.mark.parametrize(
    "lab_name,expected_slice",
    [
        ("Creatinine", "cre"),
        ("K", "k"),
        ("Na", "na"),
        ("WBC", "wbc"),
        ("AST", "ast"),
        ("ALT", "alt"),
        ("CRP", "crp"),
        ("Hb", "hb"),
        ("BUN", "bun"),
        ("PT_INR", "pt-inr"),
        ("BNP", "bnp"),
        ("Plt", "plt"),
        ("Ca", "ca"),
        ("Albumin", "alb"),
        ("HbA1c", "hba1c-ngsp"),
        ("TG", "tg"),
        ("HDL", "hdl-c"),
        ("TC", "t-cho"),
        ("APTT", "aptt"),
        ("D_dimer", "dd"),
    ],
)
def test_slice_name_for_analyte_covers_all_corelabo_entries(lab_name, expected_slice):
    """All 20 CoreLabo-classified analytes map to the expected SD
    slice suffix. Any mismatch means either the SD naming changed
    (session 67 pinned these against SD 1.12.0) or the analyte moved
    kind (should also flip the _JP_EXPECTED_KIND table)."""
    assert _slice_name_for_analyte(lab_name) == expected_slice


def test_slice_name_for_analyte_returns_none_for_uncoded_analytes():
    """Uncoded analytes have no CoreLabo slice by definition."""
    for lab_name in _KNOWN_UNCODED_ANALYTES:
        assert _slice_name_for_analyte(lab_name) is None, (
            f"{lab_name} is in _KNOWN_UNCODED_ANALYTES but has a slice mapping "
            "— inconsistency between _ANALYTE_TO_SLICE_NAME and _KNOWN_UNCODED_ANALYTES"
        )


# --------------------------------------------------------------------------- #
# Completeness — silent takedown guard.


def test_no_overlap_between_corelabo_and_uncoded_sets():
    """An analyte cannot be BOTH CoreLabo and Known-Uncoded. Overlap
    would let the classifier's iteration order determine the kind
    (silent behavior)."""
    overlap = set(_ANALYTE_TO_SLICE_NAME.keys()) & set(_KNOWN_UNCODED_ANALYTES)
    assert overlap == set(), f"analytes in BOTH sets: {overlap}"


def test_all_current_production_analytes_have_explicit_classification():
    """Every JP analyte currently emitted by the pipeline (v30 CIF)
    MUST be explicitly classified — either in _ANALYTE_TO_SLICE_NAME
    or _KNOWN_UNCODED_ANALYTES. If a new analyte lands in the
    pipeline, this test fails and the maintainer must choose
    intentionally whether it goes to CoreLabo (with a slice mapping)
    or Uncoded (explicit membership) rather than falling into the
    silent unmapped→UNCODED default. That default is a runtime safety
    net, not a mechanism for silent takedowns of newly-added
    analytes."""
    # Enumerated from v30 CIF Observation.ndjson (session 67 PR 3a
    # preparation). Any new lab_name that appears in production
    # requires an intentional classification decision.
    current_production_analytes = set(_JP_EXPECTED_KIND.keys())
    classified = set(_ANALYTE_TO_SLICE_NAME.keys()) | set(_KNOWN_UNCODED_ANALYTES)
    missing = current_production_analytes - classified
    assert missing == set(), (
        f"Production analytes without explicit classification: {sorted(missing)}. "
        "Add each to _ANALYTE_TO_SLICE_NAME (CoreLabo) or _KNOWN_UNCODED_ANALYTES (Uncoded)."
    )


def test_expected_kind_totals_match_v30_analyte_split():
    """Session 67 memo confirms the CoreLabo / Uncoded split on v30
    p=100 s=300: 20 CoreLabo analytes + 12 Uncoded analytes = 32
    total (1,898 + 611 = 2,509 observations; observation counts
    verified against v30 CIF at classifier design time)."""
    corelabo = [n for n, k in _JP_EXPECTED_KIND.items() if k == LabCodingKind.CORELABO_JLAC10]
    uncoded = [n for n, k in _JP_EXPECTED_KIND.items() if k == LabCodingKind.UNCODED]
    assert len(corelabo) == 20, f"expected 20 CoreLabo, got {len(corelabo)}"
    assert len(uncoded) == 12, f"expected 12 Uncoded (incl. Glucose), got {len(uncoded)}"
    assert len(_ANALYTE_TO_SLICE_NAME) == 20, (
        f"_ANALYTE_TO_SLICE_NAME should have 20 entries, got {len(_ANALYTE_TO_SLICE_NAME)}"
    )
    assert len(_KNOWN_UNCODED_ANALYTES) == 12, (
        f"_KNOWN_UNCODED_ANALYTES should have 12 entries, got {len(_KNOWN_UNCODED_ANALYTES)}"
    )


# --------------------------------------------------------------------------- #
# PR 3a dispatcher invariant — byte-identical preserved.


def test_select_lab_coding_strategy_pr3c_full_bridge():
    """PR 3c bridge (session 67 migration complete): dispatcher fully
    consults ``_classify_analyte`` for JP. CoreLabo → CoreLaboStrategy;
    Uncoded / unmapped → UncodedStrategy. LegacyJSLM is no longer
    routed to for any classified JP analyte (kept as defensive
    fallback for pkg-absent state)."""
    # CoreLabo analytes → CoreLaboStrategy
    for analyte in ("WBC", "K", "Creatinine", "PT_INR"):
        s = select_lab_coding_strategy(analyte, "JP")
        assert s.kind == LabCodingKind.CORELABO_JLAC10, f"{analyte} → {s.kind}"
    # Uncoded analytes → UncodedStrategy (PR 3c bridge)
    for analyte in ("Glucose", "pH", "Lactate"):
        s = select_lab_coding_strategy(analyte, "JP")
        assert s.kind == LabCodingKind.UNCODED, f"{analyte} (Uncoded) → {s.kind}"
    # Unknown JP → UncodedStrategy (safe default)
    s = select_lab_coding_strategy("UnknownNewAnalyte", "JP")
    assert s.kind == LabCodingKind.UNCODED
    # US → LegacyLOINC unchanged
    s = select_lab_coding_strategy("WBC", "US")
    assert s.kind == LabCodingKind.LEGACY_LOINC


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
# CoreLaboStrategy PR 3b: real emit (skipped when JP-CLINS pkg unavailable).
# CoreLaboStrategy has a defensive fallback to LegacyJSLM emission when the
# pkg is missing (so a minimal-install run doesn't crash mid-generate). The
# 4 tests below are validating the real emit path and skip when pkg absent —
# same pattern as ``tests/unit/test_lab_coding_package.py::_pkg_or_skip``.


@pytest.fixture
def _pkg_or_skip_corelabo():
    from clinosim.modules.output.lab_coding_package import load_lab_coding_package

    pkg = load_lab_coding_package()
    if not pkg.is_available():
        pytest.skip("JP-CLINS pkg not installed — CoreLabo real emit tests require the eCS SD + CoreLabo CS")
    return pkg


def test_corelabo_pr3b_emits_real_17digit_with_fixed_display(_pkg_or_skip_corelabo):
    """PR 3b (2026-07-26): CoreLaboStrategy no longer delegates to
    LegacyJSLM. Emits primary coding = (CoreLabo CS URI, 17-digit code,
    Fixed display from SD) + LOINC secondary. session 67 memo §H.3 rev
    + user Option B decision: numerically-largest material (chemistry
    resolves to 023 血清), method 998 preferred."""
    core = CoreLaboStrategy()
    codings = core.emit_codings(lab_name="WBC", order={}, result={}, country="JP")
    assert len(codings) >= 1
    primary = codings[0]
    assert "CoreLabo" in primary["system"], f"primary must be CoreLabo CS, got {primary['system']!r}"
    assert len(primary["code"]) == 17, f"CoreLabo code must be 17 digits, got {primary['code']!r}"
    assert primary["display"] == "WBC", f"Fixed display must be SD Fixed value 'WBC', got {primary['display']!r}"


def test_corelabo_pr3b_998_method_preference_for_k(_pkg_or_skip_corelabo):
    """PR 3b code-selection rule: method=998 preferred + numerically-largest
    material. For K, this resolves to material 023 (血清) + method 998 =
    3H015000002399801 (session 67 memo example)."""
    core = CoreLaboStrategy()
    codings = core.emit_codings(lab_name="K", order={}, result={}, country="JP")
    primary = codings[0]
    # Segment decomposition: 5/4/3/3/2 = analyte/id/material/method/result_id
    assert primary["code"][9:12] == "023", f"K material segment must be 023 (Option B), got {primary['code'][9:12]}"
    assert primary["code"][12:15] == "998", f"K method segment must be 998, got {primary['code'][12:15]}"
    assert primary["display"] == "K", f"K Fixed display, got {primary['display']!r}"


def test_corelabo_pr3b_single_material_analytes_resolve_deterministically(_pkg_or_skip_corelabo):
    """WBC / Plt have only material 019 in CoreLabo CS — Option B (max)
    yields 019 vacuously, no material-selection ambiguity."""
    core = CoreLaboStrategy()
    for analyte, expected_display in [("WBC", "WBC"), ("Plt", "PLT")]:
        codings = core.emit_codings(lab_name=analyte, order={}, result={}, country="JP")
        primary = codings[0]
        assert primary["code"][9:12] == "019", (
            f"{analyte} material segment must be 019 (only material in CS), got {primary['code'][9:12]}"
        )
        assert primary["display"] == expected_display


def test_corelabo_pr3b_keeps_loinc_secondary(_pkg_or_skip_corelabo):
    """JP dual-coding invariant: CoreLabo primary + LOINC secondary.
    Preserves the JP output's international interop (LOINC readable
    by non-JP consumers); PR 4 will decide the retain/drop ADR
    formally, but PR 3b keeps the dual-coding by default."""
    core = CoreLaboStrategy()
    codings = core.emit_codings(lab_name="WBC", order={}, result={}, country="JP")
    systems = [c["system"] for c in codings]
    assert any("CoreLabo" in s for s in systems), "primary must include CoreLabo"
    assert "http://loinc.org" in systems, "LOINC secondary must be preserved for JP dual-coding"


# --------------------------------------------------------------------------- #
# UncodedStrategy + InfectionLaboStrategy: not implemented in PR 1


def test_uncoded_strategy_pr3c_emits_uncoded_slice(_pkg_or_skip_corelabo):
    """PR 3c: UncodedStrategy activated. Emits spec-pinned Uncoded slice
    (code=99999999999999999, display=未標準化コード項目(JLAC)) + LOINC
    secondary (when available in code_mapping_lab US)."""
    s = UncodedStrategy()
    codings = s.emit_codings(lab_name="pH", order={}, result={}, country="JP")
    primary = codings[0]
    assert "Uncoded" in primary["system"], f"primary must be Uncoded CS, got {primary['system']!r}"
    assert primary["code"] == "99999999999999999"
    assert primary["display"] == "未標準化コード項目(JLAC)"
    # LOINC secondary if lab_name has a US mapping (pH → 2744-1)
    systems = [c["system"] for c in codings]
    assert "http://loinc.org" in systems, "LOINC secondary preserved for interop"


def test_uncoded_strategy_pr3c_emits_localcode_with_sanitized_ja(_pkg_or_skip_corelabo):
    """PR 3c: UncodedStrategy emits LocalCode co-slice with sanitized
    Japanese display. pH gets '動脈血pH' (space removed per JP-CLINS
    LocalCode display rule)."""
    s = UncodedStrategy()
    lc = s.emit_localcode_coding(lab_name="pH", order={}, result={}, country="JP")
    assert lc is not None
    assert "LocalCode" in lc["system"]
    assert lc["code"] == "pH"  # alphanumeric passes sanitize unchanged
    assert lc["display"] == "動脈血pH"  # spec-required no-whitespace form


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
