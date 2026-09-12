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

from clinosim.modules.output.fhir_r4.procedures.procedure_name_snomed import (
    resolve_procedure_snomed,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "display_name, expected",
    [
        # CRRT specificity wins over "hemodial" substring inside the same string.
        (
            "血液透析 3-4h セッション, 3x/週 または 持続 (CRRT)",
            ("233581009", "Haemofiltration"),
        ),
        ("Continuous renal replacement therapy (CRRT)", ("233581009", "Haemofiltration")),
        ("持続濾過セッション", ("233581009", "Haemofiltration")),
        # Standard hemodialysis session.
        ("Hemodialysis session", ("302497006", "Haemodialysis")),
        ("Haemodialysis 3-hour", ("302497006", "Haemodialysis")),
        ("血液透析セッション", ("302497006", "Haemodialysis")),
        # ECMO.
        ("ECMO VA cannulation", ("233573008", "Extracorporeal membrane oxygenation")),
        # CPAP / BiPAP.
        ("CPAP therapy overnight", ("47545007", "Continuous positive airway pressure ventilation treatment")),
        ("BiPAP for hypercapnia", ("47545007", "Continuous positive airway pressure ventilation treatment")),
        # Wound care.
        ("Wound care follow-up", ("225358003", "Wound care")),
        ("Wound irrigation with normal saline", ("225358003", "Wound care")),
        ("創傷ケア", ("225358003", "Wound care")),
        ("創部処置", ("225358003", "Wound care")),
        # Urine output monitoring.
        ("Foley catheter with urine output monitoring", ("225113003", "Timed urine collection")),
        ("尿量測定", ("225113003", "Timed urine collection")),
        # Triage.
        ("ED triage assessment level 3", ("225390008", "Triage")),
        ("トリアージ", ("225390008", "Triage")),
        # Oxygen therapy (point-in-time O2 order).
        ("O2: Nasal cannula SpO2 >= 94%", ("57485005", "Oxygen therapy")),
        ("Oxygen therapy nebulizer", ("57485005", "Oxygen therapy")),
        ("酸素投与", ("57485005", "Oxygen therapy")),
    ],
)
def test_procedure_snomed_lookup_hits(display_name, expected):
    assert resolve_procedure_snomed(display_name) == expected


def test_unmatched_display_returns_none():
    """No keyword hit → caller falls back to text-only emit."""
    assert resolve_procedure_snomed("Some completely unrelated procedure") is None


def test_empty_input_returns_none():
    assert resolve_procedure_snomed("") is None
    assert resolve_procedure_snomed(None) is None  # type: ignore[arg-type]


def test_case_insensitive_and_trim():
    """Whitespace-trimmed, case-folded substring match."""
    assert resolve_procedure_snomed("  HEMODIALYSIS session  ")[0] == "302497006"
    assert resolve_procedure_snomed("Wound Care Follow-Up")[0] == "225358003"


def test_first_match_wins_ordering():
    """CRRT entry precedes hemodialysis in the yaml, so a display with
    BOTH keywords resolves to CRRT (233581009), not hemodialysis
    (302497006)."""
    got = resolve_procedure_snomed("Hemodialysis with CRRT protocol")
    assert got == ("233581009", "Haemofiltration")


def test_only_verified_snomed_codes():
    """Sanity: every code in the crosswalk is one of the seven verified
    2026-09-12. This guards against yaml drift adding an unverified code
    without a corresponding tx.fhir.org lookup — repo policy
    (`feedback_verify_fhir_profile_uri_from_spec`)."""
    from clinosim.modules.output.fhir_r4.procedures.procedure_name_snomed import _load_entries

    verified = {
        "233581009",  # Haemofiltration
        "302497006",  # Haemodialysis
        "233573008",  # ECMO
        "47545007",  # CPAP ventilation
        "225358003",  # Wound care
        "225113003",  # Timed urine collection
        "225390008",  # Triage
        "57485005",  # Oxygen therapy
        # Issue #1308: extended crosswalk for ED / inpatient minor procedures.
        "447094002",  # Bronchodilator therapy
        "385763009",  # Inhalation therapy
        "18946005",  # Skin closure (suture / staple / tissue adhesive)
        "268400002",  # Closed reduction of fracture
        "79733001",  # Application of sling (also used for cervical collar)
        "385760008",  # Application of dressing to wound
        "229886001",  # Cold pack application
        "386305005",  # Warm pack application
        "241689008",  # Procedural sedation
        "229586001",  # Application of intermittent pneumatic compression (SCD)
        "244042001",  # Insertion of urinary bladder catheter (Foley)
    }
    for _match, snomed, _display in _load_entries():
        assert snomed in verified, (
            f"crosswalk carries unverified SNOMED {snomed} — verify via tx.fhir.org "
            f"$lookup before adding + update this test's `verified` set"
        )


def test_extended_procedure_crosswalk_covers_top_15_empty_coding_buckets_1308() -> None:
    """Issue #1308: 15 largest empty-coding buckets on the US p=10k s=355
    baseline (1275 / 4033 Procedure rows = 31.6 %) must now resolve to a
    verified SNOMED concept via the crosswalk.

    Coverage claim: after this PR, every one of the 15 exemplar display
    strings from the Issue reproduction routes to a non-empty
    ``Procedure.code.coding[0]`` entry."""
    from clinosim.modules.output.fhir_r4.procedures.procedure_name_snomed import resolve_procedure_snomed

    cases = [
        ("Ice pack application", "229886001"),
        ("bronchodilator: Salbutamol 2.5mg nebulizer q4h (q1h PRN acute)", "447094002"),
        ("bronchodilator: Ipratropium 0.5mg nebulizer q6h", "447094002"),
        ("Elastic bandage wrap", "385760008"),
        ("Suture closure", "18946005"),
        ("Closed reduction", "268400002"),
        ("Cool water irrigation", "229886001"),
        ("Sling immobilization", "79733001"),
        ("Non-adherent dressing", "385760008"),
        ("Tissue adhesive (glue)", "18946005"),
        ("Cervical collar application", "79733001"),
        ("Procedural sedation (Propofol/Midazolam)", "241689008"),
        ("Heat pack application", "386305005"),
        ("DVT_prophylaxis: Sequential compression devices", "229586001"),
        ("Foley catheter insertion", "244042001"),
    ]
    for display, expected_snomed in cases:
        got = resolve_procedure_snomed(display)
        assert got is not None, f"crosswalk miss on Issue #1308 exemplar {display!r}"
        assert got[0] == expected_snomed, (
            f"crosswalk returned wrong SNOMED for {display!r}: got {got[0]}, expected {expected_snomed}"
        )
