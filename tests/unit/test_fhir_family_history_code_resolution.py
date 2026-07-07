"""FP-FH-CODE-RESOLUTION: family_history condition-code resolution.

Session 40 fix — three defects converged into one:

1. **I64 missing** (WHO-only code). US emitted `"code": "I64"` +
   `"display": "(display unavailable)"` and JP emitted `"code": "I64"` +
   `"display": "I64"` for every family history that referenced it.
   The gap surfaced in a US p=1000 cohort sweep.

2. **E11 prefix-child fallback misdisplay**. E11 (category header) had no
   entry in ``codes/data/icd-10-cm.yaml``; ``code_lookup`` fell back to a
   child (E11.10 / E11.11) whose display is
   "Type 2 diabetes mellitus with ketoacidosis without coma" — clinically
   wrong for a "family history of type 2 diabetes" resource.

3. **Personal-history Z-code overreach**. The chronic/history diagnosis map
   folds I63 → Z86.73 ("Personal history of TIA / cerebral infarction"),
   which is semantically wrong for a *relative's* condition
   (FamilyMemberHistory.condition.code encodes the disease in the relative,
   not the patient's personal past). Applying the map indiscriminately in
   the FH builder would regress I63 emission.

The fix pattern: (a) add the missing WHO code and US category-map entries,
(b) apply ``_map_diagnosis_code`` in the FH builder,
(c) wrap it in ``_resolve_family_history_code`` which rejects Z-code
targets so I63 stays as the disease.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup
from clinosim.modules.output._fhir_family_history import _resolve_family_history_code


pytestmark = pytest.mark.unit


FAMILY_HISTORY_CODES = ("E11", "I10", "I25", "I63", "I64", "E78", "C50", "C18", "C34", "C61")


class TestFamilyHistoryCodeResolutionUS:
    def test_e11_folds_to_billable_leaf(self) -> None:
        assert _resolve_family_history_code("E11", "US") == "E11.9"

    def test_i64_folds_to_billable_leaf(self) -> None:
        assert _resolve_family_history_code("I64", "US") == "I63.9"

    def test_i63_stays_disease_not_personal_history(self) -> None:
        """Regression guard: applying the chronic-history map here would give
        Z86.73 (Personal history), semantically wrong for a relative."""
        assert _resolve_family_history_code("I63", "US") == "I63"

    def test_all_family_history_codes_have_authoritative_display_us(self) -> None:
        """Coverage guard: no US family_history condition falls back to
        '(display unavailable)' or the raw code."""
        for c in FAMILY_HISTORY_CODES:
            resolved = _resolve_family_history_code(c, "US")
            disp = lookup("icd-10-cm", resolved, "en")
            assert disp, f"US {c} → {resolved} has empty display"
            assert disp != resolved, f"US {c} → {resolved} display resolves to the code itself"
            assert "unavailable" not in disp.lower(), (
                f"US {c} → {resolved} falls back to placeholder: {disp!r}"
            )


class TestFamilyHistoryCodeResolutionJP:
    def test_i64_resolves_via_who(self) -> None:
        assert _resolve_family_history_code("I64", "JP") == "I64"
        # WHO ICD-10 has the authoritative name
        assert lookup("icd-10", "I64", "ja") == "脳卒中（出血または梗塞と明示されないもの）"
        assert lookup("icd-10", "I64", "en") == "Stroke, not specified as haemorrhage or infarction"

    def test_all_family_history_codes_have_authoritative_display_jp(self) -> None:
        for c in FAMILY_HISTORY_CODES:
            resolved = _resolve_family_history_code(c, "JP")
            disp = lookup("icd-10", resolved, "ja")
            assert disp, f"JP {c} → {resolved} has empty display"
            assert disp != resolved, f"JP {c} → {resolved} display resolves to the code itself"
            assert "表示不可" not in disp, (
                f"JP {c} → {resolved} falls back to placeholder: {disp!r}"
            )


class TestZCodeRejection:
    """The wrap-and-reject mechanism must reject any Z-code target from the
    chronic-history map to prevent future personal-history regressions
    (Z86.* / Z87.* / Z82.* are all "personal history of X" codes)."""

    @pytest.mark.parametrize("code,expected", [
        ("I26", "I26"),  # map targets Z86.711 (Personal history of PE) → reject
        ("I80", "I80"),  # map targets Z86.718 → reject
        ("I82", "I82"),  # map targets Z86.718 → reject
        ("M48", "M48"),  # map targets Z87.311 → reject
        ("M80", "M80"),  # map targets Z87.310 → reject
    ])
    def test_z_code_target_falls_back_to_original(self, code: str, expected: str) -> None:
        assert _resolve_family_history_code(code, "US") == expected


class TestI64CoverageForBothCountries:
    """The session 40 finding: I64 was emitting '(display unavailable)' in US
    cohorts and 'I64' fallback in JP. Both must now resolve to authoritative
    displays."""

    def test_us_i64_display_is_authoritative_cerebral_infarction_leaf(self) -> None:
        resolved = _resolve_family_history_code("I64", "US")
        assert resolved == "I63.9"
        assert lookup("icd-10-cm", resolved, "en") == "Cerebral infarction, unspecified"

    def test_jp_i64_display_is_authoritative_who_stroke_nos(self) -> None:
        # JP path: I64 stays as WHO ICD-10 code (no fold — WHO retains I64)
        resolved = _resolve_family_history_code("I64", "JP")
        assert resolved == "I64"
        assert "脳卒中" in lookup("icd-10", resolved, "ja")
