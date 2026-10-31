"""META #1792 Phase 6 — catalog referential integrity CI gate.

Two invariants locked at CI time:

1. **Every ``drug_id`` reference in any clinosim yaml must resolve
   against ``clinosim/codes/data/drugs.yaml``.** A new disease yaml
   that spells ``drug_id: nonexistant_drug`` would otherwise emit a
   silent empty item via the dual-path resolver's catalog miss.

2. **Every drug_id in the catalog must carry at least ONE authority
   code pointer — ``codes.rxnorm`` (US-NLM), ``codes.yj`` (JP MHLW),
   or ``codes.hot7`` (JP MEDIS clinical master).** US-locale FHIR
   output resolves ``MedicationRequest.medicationCodeableConcept.coding``
   from ``codes.rxnorm``; JP-locale resolves it from ``codes.yj`` /
   ``codes.hot7``. A drug_id with none of the three would land on
   the pre-#1765 silent-drop path for its target locale. The invariant
   now admits JP-only drugs (META #1849 Phase 5 Step 2.b YJ-only +
   Step 2 HOT7-only fallback for drugs whose NLM RxCUI is NotCurrent).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clinosim.codes.drugs import all_drug_ids, resolve_drug

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_YAML_SCAN_ROOTS = (
    _REPO_ROOT / "clinosim" / "locale",
    _REPO_ROOT / "clinosim" / "modules" / "disease" / "reference_data",
)
# Any value after ``drug_id:``, stripped of quotes and trailing comma.
# The scan accepts both ``- drug_id: aspirin`` (block form) and
# ``- {drug_id: aspirin, ...}`` (flow form).
_DRUG_ID_LINE_RE = re.compile(r"\bdrug_id\s*:\s*([^,}\s]+)")


def _iter_yaml_drug_id_refs() -> list[tuple[Path, int, str]]:
    """Yield (path, line_no, drug_id) across the referential-scope yaml tree."""
    hits: list[tuple[Path, int, str]] = []
    for root in _YAML_SCAN_ROOTS:
        if not root.exists():
            continue
        for yaml_path in root.rglob("*.yaml"):
            # The catalog itself defines drug_ids (left-hand side keys);
            # skip it to avoid false "every key is a drug_id reference"
            # readings. The invariant is about USE sites, not the
            # definition site.
            if yaml_path.name == "drugs.yaml":
                continue
            with yaml_path.open(encoding="utf-8") as f:
                for lineno, line in enumerate(f, start=1):
                    for m in _DRUG_ID_LINE_RE.finditer(line):
                        raw = m.group(1).strip().strip("\"'")
                        if raw:
                            hits.append((yaml_path, lineno, raw))
    return hits


def test_every_drug_id_reference_resolves_against_catalog() -> None:
    """Static referential integrity: every ``drug_id:`` use in a
    downstream yaml must resolve against the drugs.yaml catalog.

    Catches the regression class where a disease yaml or locale
    override spells a drug_id that was never registered — the
    dual-path resolver's catalog miss would silently emit an empty
    item.
    """
    hits = _iter_yaml_drug_id_refs()
    # Shape invariant: the scan must find at least one hit. A zero
    # count would mean the regex drifted silently (bug-detector
    # dead-letter class).
    assert hits, (
        "no drug_id references found under locale/ or disease reference_data/; "
        "the scan regex has probably drifted. Confirm by grepping manually."
    )

    offenders: list[str] = []
    seen: set[str] = set()
    for path, lineno, drug_id in hits:
        seen.add(drug_id)
        try:
            resolve_drug(drug_id)
        except KeyError:
            offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {drug_id!r}")

    assert not offenders, (
        "drug_id references that do not resolve against clinosim/codes/data/drugs.yaml:\n" + "\n".join(offenders)
    )


# Drugs with no RxNorm ingredient and no JP product in the clinosim-shipped
# YJ CodeSystem: emitted in the eCS ``nocoded`` slice (Issue #2347).
_UNCODED_BY_DESIGN = {
    # Non-lactated Ringer's: the MHLW master lists only the unified-name
    # リンゲル液 (3319539A1015 / A2011), absent from JP_MedicationCodeYJ_CS_full.
    "ringer_solution",
}


def test_every_catalog_drug_has_authority_pointer() -> None:
    """Catalog shape invariant: every drug_id in drugs.yaml carries at
    least ONE authority code pointer — ``codes.rxnorm`` (US-NLM),
    ``codes.yj`` (JP MHLW), or ``codes.hot7`` (JP MEDIS clinical master).

    US-locale FHIR output resolves ``MedicationRequest.medicationCode``
    from ``codes.rxnorm``; JP-locale FHIR output resolves it from
    ``codes.yj`` or ``codes.hot7`` (the FHIR emit path dispatches to the
    correct canonical URI per code format). A drug_id with none of the
    three pointers would land on the pre-#1765 silent-drop path for its
    target locale. This invariant freezes the coverage #1820 (Phase 2.e)
    achieved while admitting:
      - JP-only drugs with YJ registration (Cefcapene pivoxil /
        Nafamostat / Elcatonin / Daikenchuto, META #1849 Phase 5
        Step 2.b);
      - JP-only drugs with HOT7-only registration (Camostat mesilate,
        BCG intravesical — RxCUI NotCurrent or absent, YJ not
        registered for the specific clinical form; META #1849 Phase 5
        Step 2 HOT7 fallback).
    """
    offenders: list[str] = []
    for drug_id in all_drug_ids():
        rec = resolve_drug(drug_id)
        if drug_id in _UNCODED_BY_DESIGN:
            continue
        if not any(rec.codes.get(key) for key in ("rxnorm", "yj", "hot7")):
            offenders.append(drug_id)
    assert not offenders, (
        "catalog drug_ids missing ALL authority pointers "
        "(codes.rxnorm / codes.yj / codes.hot7 — cannot resolve under either locale):\n  " + "\n  ".join(offenders)
    )


def test_catalog_scan_finds_known_sample() -> None:
    """Sanity check: the scan should find a well-known drug_id use.

    Pins the scan against future accidental breakage (e.g. a regex
    tweak that misses the block form) by asserting at least one
    recent migration's drug_id was observed.
    """
    hits = _iter_yaml_drug_id_refs()
    seen = {drug_id for _p, _l, drug_id in hits}
    # ``aspirin`` was migrated to the catalog by #1836 (cardiac
    # cluster) in acute_mi.yaml::discharge_oral.japan. If this
    # disappears the scan is lying.
    assert "aspirin" in seen, (
        "sample drug_id 'aspirin' not seen by the scan; the regex or the scan roots likely drifted"
    )
