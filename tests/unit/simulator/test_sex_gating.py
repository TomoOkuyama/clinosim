"""Sex-gating for ICD-10 diagnosis dispatch — Issue #947.

Six female patients in the p=6389 JP cohort were emitting a Condition with
``code.text = "急性前立腺炎"`` (acute prostatitis, N41.0) — anatomically
impossible. Root cause: the diagnosis-dispatch table (differential-final
picker, implied-chronic table, discharge-Dx → chronic propagation) did
not consult ``Patient.gender`` before assigning the code. Pre-fix,
``simulator/inpatient.py`` and ``simulator/helpers.py`` each carried an
inline ``_SEX_RESTRICTED_ICD = {"N40": "M"}`` covering exactly one code
(BPH); every other sex-locked code (N41 prostatitis, N70–N77 female PID,
O00–O9A pregnancy, C50–C63 sex-specific malignancies) was silently
emit-able onto opposite-sex patients whenever the RNG happened to pick it.

Fix: canonical lock list lives at
``clinosim/locale/shared/icd10_sex_restrictions.yaml``; every dispatch
site funnels through ``clinosim.simulator.sex_gating.is_sex_locked_for``.
Differential picker walks candidates (non-RNG); static tables skip.

These tests exercise the helper directly + spot-check the fixed engine
API so a regression (a caller dropping the ``patient_sex`` kwarg, a
future code addition without the yaml entry) fails loudly in unit tests
before it reaches a p=1000 review.
"""

from __future__ import annotations

from clinosim.modules.diagnosis.engine import get_current_diagnosis_code
from clinosim.simulator.sex_gating import (
    is_sex_locked_for,
    pick_sex_compatible_dx_code,
)
from clinosim.types.diagnosis import DiagnosisCandidate, DifferentialDiagnosis


def test_n41_prostatitis_locked_for_female() -> None:
    """The exact code from Issue #947 (N41.0 急性前立腺炎) must be
    identified as male-only, so a female patient never gets it."""
    assert is_sex_locked_for("N41.0", "F") is True
    assert is_sex_locked_for("N41.0", "female") is True
    assert is_sex_locked_for("N41.0", "M") is False
    assert is_sex_locked_for("N41.0", "male") is False


def test_n40_bph_locked_for_female() -> None:
    """N40 (BPH) — the pre-fix inline table already covered this; the
    unified table must still lock it."""
    assert is_sex_locked_for("N40", "F") is True
    assert is_sex_locked_for("N40.0", "F") is True  # sub-code inherits base
    assert is_sex_locked_for("N40", "M") is False


def test_pregnancy_codes_locked_for_male() -> None:
    """O00–O9A pregnancy chapter must be locked for males."""
    for code in ("O00", "O80", "O99", "Z34", "Z37"):
        assert is_sex_locked_for(code, "M") is True, code
        assert is_sex_locked_for(code, "F") is False, code


def test_female_pelvic_inflammatory_locked_for_male() -> None:
    """N70–N77 (salpingitis, oophoritis, PID) locked for males."""
    for code in ("N70", "N71", "N76"):
        assert is_sex_locked_for(code, "M") is True, code
        assert is_sex_locked_for(code, "F") is False, code


def test_male_genital_malignancy_locked_for_female() -> None:
    """C60–C63 male-genital malignancies locked for females."""
    for code in ("C60", "C61", "C62", "C63"):
        assert is_sex_locked_for(code, "F") is True, code
        assert is_sex_locked_for(code, "M") is False, code


def test_c50_breast_cancer_not_sex_locked() -> None:
    """C50 (乳がん) — ~1% real-world male incidence (MHLW 患者調査/SEER).
    The interim female-only lock is lifted (Issue #957 male-C50 activation);
    prevalence is now controlled purely by demographics.chronic_prevalence
    ``by_sex`` bands so the gate must NOT reject C50 for either sex."""
    for code in ("C50", "C50.9", "C50.919", "C50.929"):
        assert is_sex_locked_for(code, "M") is False, code
        assert is_sex_locked_for(code, "F") is False, code


def test_other_female_breast_and_genital_codes_stay_locked() -> None:
    """Guard against over-unlocking: C51–C58 (vulva, vagina, cervix, uterus,
    ovary, placenta) remain female-only. Only C50 (breast) had a real male
    incidence — the sibling codes stay locked."""
    for code in ("C51", "C52", "C53", "C54", "C55", "C56", "C57", "C58"):
        assert is_sex_locked_for(code, "M") is True, code
        assert is_sex_locked_for(code, "F") is False, code


def test_neutral_codes_not_locked() -> None:
    """UTI (N39.0), pneumonia (J18.9), hypertension (I10) — these are
    NOT sex-locked and must remain emit-able for either sex."""
    for code in ("N39.0", "J18.9", "I10", "E11.9", "R69", "Z09"):
        assert is_sex_locked_for(code, "M") is False, code
        assert is_sex_locked_for(code, "F") is False, code


def test_unknown_or_missing_sex_never_blocks() -> None:
    """Patients with unknown/other/empty sex don't get blocked — there's
    no meaningful anatomy check to perform. The gate returns False and
    the caller emits without gating."""
    assert is_sex_locked_for("N41.0", "") is False
    assert is_sex_locked_for("N41.0", None) is False
    assert is_sex_locked_for("N41.0", "other") is False
    assert is_sex_locked_for("N41.0", "unknown") is False


def test_pick_sex_compatible_walks_candidates() -> None:
    """The candidate walker returns the first sex-compatible candidate
    from a probability-ranked list. Consumes no RNG state."""
    candidates = [
        DiagnosisCandidate(
            disease_code="prostatitis", icd_code="N41.0", display_name="Acute prostatitis", probability=0.50
        ),
        DiagnosisCandidate(
            disease_code="urinary_tract_infection", icd_code="N39.0", display_name="UTI", probability=0.30
        ),
        DiagnosisCandidate(disease_code="cystitis", icd_code="N30.0", display_name="Cystitis", probability=0.20),
    ]
    # Female patient — N41.0 skipped, N39.0 picked.
    picked = pick_sex_compatible_dx_code(candidates, "F")
    assert picked is not None and picked.icd_code == "N39.0"
    # Male patient — top pick N41.0 is fine.
    picked = pick_sex_compatible_dx_code(candidates, "M")
    assert picked is not None and picked.icd_code == "N41.0"


def test_pick_returns_none_when_all_locked() -> None:
    """When every candidate is locked for this sex, the helper returns
    None so the caller can fall back to the unresolved sentinel rather
    than silently emit a locked code."""
    candidates = [
        DiagnosisCandidate(disease_code="prostatitis", icd_code="N41.0", display_name="p", probability=0.6),
        DiagnosisCandidate(disease_code="bph", icd_code="N40", display_name="b", probability=0.4),
    ]
    assert pick_sex_compatible_dx_code(candidates, "F") is None


def test_engine_get_current_diagnosis_code_walks_when_sex_locked() -> None:
    """Regression for Issue #947: `get_current_diagnosis_code(..., patient_sex="F")`
    on a UTI differential where N41.0 tops the probability ranking must
    return the next-ranked sex-compatible code (N39.0), NOT N41.0."""
    diff = DifferentialDiagnosis(
        candidates=[
            DiagnosisCandidate(
                disease_code="prostatitis", icd_code="N41.0", display_name="prostatitis", probability=0.50
            ),
            DiagnosisCandidate(
                disease_code="urinary_tract_infection", icd_code="N39.0", display_name="UTI", probability=0.30
            ),
            DiagnosisCandidate(disease_code="cystitis", icd_code="N30.0", display_name="cystitis", probability=0.20),
        ],
        working_diagnosis="prostatitis",
    )
    code, _display = get_current_diagnosis_code(diff, patient_sex="F")
    # N41.x prostatitis must not appear; the next sex-compatible candidate
    # (urinary_tract_infection → N39.0 per builtin progression) or the
    # candidate's own icd (N39.0) is acceptable.
    assert not code.startswith("N41"), f"female patient got prostatitis code {code!r}"
    assert not code.startswith("N40"), f"female patient got BPH code {code!r}"


def test_engine_get_current_diagnosis_code_male_keeps_top() -> None:
    """Sanity: for a male patient the top pick (N41.0) is still returned —
    the gate must not over-block."""
    diff = DifferentialDiagnosis(
        candidates=[
            DiagnosisCandidate(
                disease_code="prostatitis", icd_code="N41.0", display_name="prostatitis", probability=0.60
            ),
            DiagnosisCandidate(
                disease_code="urinary_tract_infection", icd_code="N39.0", display_name="UTI", probability=0.40
            ),
        ],
        working_diagnosis="prostatitis",
    )
    code, _display = get_current_diagnosis_code(diff, patient_sex="M")
    assert code.startswith("N41") or code == "N41.0"


def test_engine_backward_compat_no_patient_sex() -> None:
    """Callers that don't pass `patient_sex` retain the pre-fix behavior —
    the top candidate wins. This preserves compatibility for any test /
    caller not yet migrated to the sex-gated signature."""
    diff = DifferentialDiagnosis(
        candidates=[
            DiagnosisCandidate(disease_code="prostatitis", icd_code="N41.0", display_name="p", probability=0.50),
            DiagnosisCandidate(
                disease_code="urinary_tract_infection", icd_code="N39.0", display_name="UTI", probability=0.30
            ),
        ],
        working_diagnosis="prostatitis",
    )
    code, _display = get_current_diagnosis_code(diff)
    # No patient_sex → walks nothing; top candidate wins (progression may
    # remap it, but it is one of the top candidate's ICDs, not the runner-up).
    assert code.startswith("N41") or code == "N41.0"
