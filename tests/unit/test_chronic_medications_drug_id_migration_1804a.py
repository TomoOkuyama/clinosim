"""Issue #1804 Phase 2.a — chronic_medications.yaml → drug_id migration.

Phase 1a (#1794) + Phase 1b (#1803) delivered the drug-identity Single
Source of Truth. Phase 2.a migrates ``chronic_medications.yaml``'s
``medications:`` entries from the per-row ``drug: "X" / drug_ja: "Y"``
duplicate pair to a single ``drug_id`` reference that resolves the
display via ``clinosim.codes.drugs.resolve_drug(drug_id)``.

These tests lock in:

  * The migration coverage (every migratable entry carries ``drug_id``).
  * The catalog-pointer integrity (every ``drug_id`` resolves against
    ``drugs.yaml``).
  * The legacy fallback for entries that could not migrate yet
    (Rivaroxaban dose-embedded JP/US duality, Tegafur-Gimeracil-Oteracil
    S-1 combo without a clean IN-level RxCUI).
"""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import get_drug
from clinosim.locale.loader import load_chronic_medications

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_medication_entries() -> list[tuple[str, dict]]:
    """Return ``[(icd, entry), ...]`` for every medication entry across
    the ICD blocks. Includes both migrated (drug_id) and legacy
    (drug + drug_ja) entries."""
    data = load_chronic_medications()
    out: list[tuple[str, dict]] = []
    for icd, block in data.items():
        if not isinstance(block, dict):
            continue
        for entry in block.get("medications") or []:
            if isinstance(entry, dict):
                out.append((icd, entry))
    return out


# Legacy-OK list: entries where catalog mapping is not yet possible.
_LEGACY_OK_DRUGS: set[str] = {
    "Rivaroxaban 20mg",  # dose-embedded JP/US duality, Phase 2.a.ii
    "Tegafur-Gimeracil-Oteracil",  # S-1 JP combo, no clean IN-level RxCUI
}


# ---------------------------------------------------------------------------
# Coverage: every migratable entry carries drug_id
# ---------------------------------------------------------------------------


def test_every_entry_has_either_drug_id_or_is_legacy_ok():
    """Each medication entry must either (a) carry a ``drug_id`` so the
    activator resolves display via the catalog, or (b) match the
    enumerated legacy-OK list (dose-embedded Rivaroxaban, Tegafur
    S-1 combo). An unexpected un-migrated entry is a Phase 2.a defect."""
    offenders: list[tuple[str, str]] = []
    for icd, entry in _iter_medication_entries():
        if entry.get("drug_id"):
            continue
        legacy_drug = str(entry.get("drug") or "")
        if legacy_drug in _LEGACY_OK_DRUGS:
            continue
        offenders.append((icd, legacy_drug))
    assert not offenders, (
        f"{len(offenders)} entries in chronic_medications.yaml lack a "
        f"drug_id and are NOT in the legacy-OK allow-list "
        f"({_LEGACY_OK_DRUGS}): {offenders}"
    )


# ---------------------------------------------------------------------------
# Integrity: every drug_id resolves against drugs.yaml
# ---------------------------------------------------------------------------


def test_every_drug_id_resolves_against_drugs_catalog():
    """A dangling drug_id would leave the activator with no display SoT
    and silently fall through to an empty name. The resolver must
    return a non-None record for every drug_id in the yaml."""
    dangling: list[tuple[str, str]] = []
    for icd, entry in _iter_medication_entries():
        drug_id = entry.get("drug_id") or ""
        if not drug_id:
            continue
        if get_drug(str(drug_id)) is None:
            dangling.append((icd, drug_id))
    assert not dangling, f"{len(dangling)} entries carry a drug_id with no catalog record in drugs.yaml: {dangling}"


def test_resolved_display_is_non_empty_for_every_migrated_entry():
    """A catalog record whose ``names.en`` or ``names.ja`` is empty
    would surface as a blank drug on US / JP output. The parse-time
    yaml validation already rejects such entries (``_parse_catalog``
    raises), but this test gives chronic_medications the direct
    assertion so a drift in the catalog surfaces here too."""
    blanks: list[tuple[str, str]] = []
    for icd, entry in _iter_medication_entries():
        drug_id = entry.get("drug_id") or ""
        if not drug_id:
            continue
        rec = get_drug(str(drug_id))
        assert rec is not None  # covered by test_every_drug_id_resolves
        if not rec.names.get("en") or not rec.names.get("ja"):
            blanks.append((icd, drug_id))
    assert not blanks, f"migrated entries with blank catalog display: {blanks}"


# ---------------------------------------------------------------------------
# Legacy fallback: Rivaroxaban dose-embedded + Tegafur combo still work
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("legacy_drug", sorted(_LEGACY_OK_DRUGS))
def test_legacy_entries_still_carry_drug_and_drug_ja(legacy_drug: str):
    """The dose-embedded Rivaroxaban variants and the S-1 combo stay in
    the legacy ``drug: "X" / drug_ja: "Y"`` format; downstream
    (activator / resolve_med_name) must still read them via the legacy
    path. The migration must not accidentally drop their JA display."""
    hits = [entry for icd, entry in _iter_medication_entries() if entry.get("drug") == legacy_drug]
    assert hits, f"legacy entry {legacy_drug!r} missing from chronic_medications.yaml"
    for entry in hits:
        assert entry.get("drug") == legacy_drug
        assert entry.get("drug_ja"), f"legacy {legacy_drug} entry must retain drug_ja for JP display: {entry}"


# ---------------------------------------------------------------------------
# Headcount: Phase 2.a migrated 79 entries (76 initial + 3 INN-aliased)
# ---------------------------------------------------------------------------


def test_phase_2a_migration_covers_most_entries():
    """Headcount gate: a Phase 2.a regression that silently un-migrates
    many entries fails this bound. The number is deliberately a lower
    bound (``>= 70``) rather than an exact match so future PRs that
    migrate the legacy 3 entries don't need to bump this test."""
    all_entries = _iter_medication_entries()
    migrated = sum(1 for _, e in all_entries if e.get("drug_id"))
    assert migrated >= 70, (
        f"expected >= 70 chronic_medications entries migrated to drug_id; got {migrated}/{len(all_entries)}"
    )
