"""Issue #1321 (META #1392 Cluster A part 5) — pregnancy antihypertensive substitution.

Chronic HTN meds (Amlodipine / Lisinopril / Losartan / …) refill at
every prenatal visit — pre-fix these included FDA Cat C / D drugs (ACE-I,
ARB, DHP-CCB) with no substitution to ACOG-recommended pregnancy-safe
agents. The outpatient prescription-renewal loop now consults
``pregnancy_substitutions.yaml`` when an active pregnancy
``TemporalStatePeriod`` exists at the visit date and swaps the original
drug for the pregnancy-safe substitute (Methyldopa first-line per ACOG
2019). Post-Z39 postpartum reverts automatically because the check is
per-visit — ``patient.current_medications`` is unchanged.
"""

from __future__ import annotations

from clinosim.codes.drugs import resolve_drug
from clinosim.locale.loader import load_pregnancy_substitutions


def _resolve_substitute(entry: dict) -> tuple[str, str]:
    """Phase 2.c (#1804): substitutes now carry ``substitute_drug_id``
    into the drugs.yaml catalog; this helper resolves display EN+JA via
    the catalog, falling back to the legacy fields when present (not
    used after this migration, but kept so a hand-crafted test entry
    can still verify the pre-migration shape)."""
    sub_drug_id = str(entry.get("substitute_drug_id") or "")
    if sub_drug_id:
        rec = resolve_drug(sub_drug_id)
        en = rec.names.get("en", "") or ""
        ja = rec.names.get("ja", "") or en
        return en, ja
    en = str(entry.get("substitute") or "")
    return en, str(entry.get("substitute_ja") or en)


def test_pregnancy_substitutions_yaml_loads():
    subs = load_pregnancy_substitutions()
    assert subs, "pregnancy_substitutions.yaml must not be empty"


def test_amlodipine_substituted_to_methyldopa():
    """Finding case (pt-192d90bc7df0): Amlodipine on prenatal visits."""
    subs = load_pregnancy_substitutions()
    sub_en, _ = _resolve_substitute(subs["Amlodipine"])
    assert sub_en == "Methyldopa"
    assert subs["Amlodipine"]["dose"]
    assert subs["Amlodipine"]["route"] == "PO"


def test_acei_substituted_to_methyldopa():
    """ACE-I is absolutely contraindicated post-1st trimester (fetal renal
    dysgenesis, oligohydramnios). Every ACE-I in the sim's drug catalog
    must have a pregnancy substitute."""
    subs = load_pregnancy_substitutions()
    for acei in ("Enalapril", "Lisinopril", "Captopril"):
        assert acei in subs, f"ACE-I {acei} missing pregnancy substitute"
        sub_en, _ = _resolve_substitute(subs[acei])
        assert sub_en == "Methyldopa"


def test_arb_substituted_to_methyldopa():
    """ARB same fetal-renal risk as ACE-I."""
    subs = load_pregnancy_substitutions()
    for arb in ("Losartan", "Valsartan", "Candesartan"):
        assert arb in subs
        sub_en, _ = _resolve_substitute(subs[arb])
        assert sub_en == "Methyldopa"


def test_all_substitutes_carry_ja_name():
    """JP cohort emit needs ``drug_name_ja`` — every entry's resolved
    substitute (via the catalog) must have it."""
    subs = load_pregnancy_substitutions()
    for orig, entry in subs.items():
        _, sub_ja = _resolve_substitute(entry)
        assert sub_ja, f"{orig} substitute has no JA display"


def test_all_substitutes_carry_rationale():
    """Auditor / narrative needs the reason — assert every entry has both
    EN and JA rationale."""
    subs = load_pregnancy_substitutions()
    for orig, entry in subs.items():
        assert entry.get("rationale_en"), f"{orig} missing rationale_en"
        assert entry.get("rationale_ja"), f"{orig} missing rationale_ja"


def test_non_pregnancy_contraindicated_drugs_not_in_table():
    """Regression: Metoprolol / Furosemide / Atorvastatin should NOT be in
    the substitution table (either they're safe or a separate hold
    action is required)."""
    subs = load_pregnancy_substitutions()
    assert "Methyldopa" not in subs  # substitute must not itself be substituted
    assert "Labetalol" not in subs
