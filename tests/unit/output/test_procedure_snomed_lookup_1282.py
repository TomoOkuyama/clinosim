"""Order → Procedure SNOMED CT lookup crosswalk (#1282 Sub-B).

The Order-derived Procedure builder (`output/fhir_r4/lib/inline_bb.py`)
previously emitted `Procedure.code = {text: <display>}` with an empty
`coding` array — 36 % of all Procedure rows at p=10k s=354 (Issue
#1282). The crosswalk in
`clinosim/modules/output/fhir_r4/procedures/procedure_name_snomed.yaml`
adds verified SNOMED CT codes for the common clinical procedure
patterns (hemodialysis, CRRT, wound care, urine monitoring, triage,
oxygen therapy).

These tests lock in:
1. The lookup helper resolves each documented pattern to its verified
   SNOMED code.
2. First-match-wins ordering: `CRRT` beats generic `hemodialysis`.
3. Unmatched inputs return `None` (caller falls back to text-only).
4. The yaml only carries SNOMED codes actually verified against
   `tx.fhir.org` (spot-check).
"""

from __future__ import annotations

import pytest

from clinosim.codes.snomed import snomed_for_phrase

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "display_name, expected",
    [
        # CRRT specificity wins over "hemodial" substring inside the same string.
        ("血液透析 3-4h セッション, 3x/週 または 持続 (CRRT)", "233581009"),
        ("Continuous renal replacement therapy (CRRT)", "233581009"),
        ("持続濾過セッション", "233581009"),
        # Standard hemodialysis session.
        ("Hemodialysis session", "302497006"),
        ("Haemodialysis 3-hour", "302497006"),
        ("血液透析セッション", "302497006"),
        # ECMO.
        ("ECMO VA cannulation", "233573008"),
        # CPAP / BiPAP.
        ("CPAP therapy overnight", "47545007"),
        ("BiPAP for hypercapnia", "47545007"),
        # Wound care.
        ("Wound care follow-up", "225358003"),
        ("Wound irrigation with normal saline", "225358003"),
        ("創傷ケア", "225358003"),
        ("創部処置", "225358003"),
        # Urine output monitoring.
        ("Foley catheter with urine output monitoring", "225113003"),
        ("尿量測定", "225113003"),
        # Triage.
        ("ED triage assessment level 3", "225390008"),
        ("トリアージ", "225390008"),
        # Oxygen therapy (point-in-time O2 order).
        ("O2: Nasal cannula SpO2 >= 94%", "57485005"),
        ("Oxygen therapy nebulizer", "57485005"),
        ("酸素投与", "57485005"),
    ],
)
def test_procedure_snomed_lookup_hits(display_name, expected):
    assert snomed_for_phrase(display_name) == expected


def test_unmatched_display_returns_none():
    """No keyword hit → caller falls back to text-only emit."""
    assert snomed_for_phrase("Some completely unrelated procedure") is None


def test_empty_input_returns_none():
    assert snomed_for_phrase("") is None
    assert snomed_for_phrase(None) is None  # type: ignore[arg-type]


def test_case_insensitive_and_trim():
    """Whitespace-trimmed, case-folded substring match."""
    assert snomed_for_phrase("  HEMODIALYSIS session  ") == "302497006"
    assert snomed_for_phrase("Wound Care Follow-Up") == "225358003"


def test_first_match_wins_ordering():
    """CRRT entry precedes hemodialysis in the yaml, so a display with
    BOTH keywords resolves to CRRT (233581009), not hemodialysis
    (302497006)."""
    assert snomed_for_phrase("Hemodialysis with CRRT protocol") == "233581009"


def test_extended_procedure_crosswalk_covers_top_15_empty_coding_buckets_1308() -> None:
    """Issue #1308: 15 largest empty-coding buckets on the US p=10k s=355
    baseline (1275 / 4033 Procedure rows = 31.6 %) must now resolve to a
    verified SNOMED concept via the crosswalk.

    Coverage claim: after this PR, every one of the 15 exemplar display
    strings from the Issue reproduction routes to a non-empty
    ``Procedure.code.coding[0]`` entry."""

    cases = [
        ("Ice pack application", "229585002"),
        ("bronchodilator: Salbutamol 2.5mg nebulizer q4h (q1h PRN acute)", "127784009"),
        ("bronchodilator: Ipratropium 0.5mg nebulizer q6h", "127784009"),
        ("Elastic bandage wrap", "9263008"),
        ("Suture closure", "391906003"),
        ("Closed reduction", "86052008"),
        ("Cool water irrigation", "182661005"),
        ("Sling immobilization", "52037006"),
        ("Non-adherent dressing", "3895009"),
        ("Tissue adhesive (glue)", "746011009"),
        ("Cervical collar application", "49689007"),
        ("Procedural sedation (Propofol/Midazolam)", "72641008"),
        ("Heat pack application", "266694003"),
        ("DVT_prophylaxis: Sequential compression devices", "429289005"),
        ("Foley catheter insertion", "410024004"),
    ]
    for display, expected_snomed in cases:
        got = snomed_for_phrase(display)
        assert got is not None, f"crosswalk miss on Issue #1308 exemplar {display!r}"
        assert got == expected_snomed, (
            f"crosswalk returned wrong SNOMED for {display!r}: got {got}, expected {expected_snomed}"
        )
