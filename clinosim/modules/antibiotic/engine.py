"""Pure functions for the antibiotic module (PR3b-1).

load_hai_empirical reads reference_data/hai_empirical.yaml once and
validates keys against HAI_TYPES + ANTIBIOTIC_DRUGS canonical
constants — surfacing case-mismatch / typo class of bugs at import
time (PR-90 教訓). build_regimens + generate_mar_doses produce the
typed records the enricher attaches to the CIF record.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS, ANTIBIOTIC_LOINC_LOOKUP
from clinosim.modules.hai import HAI_TYPES
from clinosim.types.antibiotic import AntibioticRegimen
from clinosim.types.encounter import MedicationAdministration
from clinosim.types.hai import HAIEvent
from clinosim.types.microbiology import SusceptibilityResult

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_HAI_EMPIRICAL_YAML = _REF_DIR / "hai_empirical.yaml"
_NARROW_LADDER_YAML = _REF_DIR / "narrow_ladder.yaml"


FREQ_PER_DAY: dict[str, int] = {
    "q24h": 1,
    "q12h": 2,
    "q8h":  3,
    "q6h":  4,
    "q4h":  6,
}


def _validate_narrow_ladder(data: dict[str, dict[str, list[str]]]) -> None:
    """3-way cross-validation: every (hai_type, organism, drug_key) entry must
    be in HAI_TYPES + hai_antibiogram + ANTIBIOTIC_DRUGS. Raises ValueError
    at load time to surface silent-no-op risk (PR-90 教訓 / CLAUDE.md
    silent-no-op defense triplet)."""
    from clinosim.modules.hai import load_hai_antibiogram  # local: avoid circular import

    antibiogram = load_hai_antibiogram()
    valid_hai_types = set(HAI_TYPES)
    valid_drugs = set(ANTIBIOTIC_DRUGS.keys())

    for hai_type, organism_map in data.items():
        if hai_type not in valid_hai_types:
            raise ValueError(
                f"narrow_ladder.yaml: unknown hai_type {hai_type!r}, "
                f"expected one of {sorted(valid_hai_types)}"
            )
        for organism_snomed, drug_list in organism_map.items():
            if organism_snomed not in antibiogram.get(hai_type, {}):
                raise ValueError(
                    f"narrow_ladder.yaml: organism {organism_snomed!r} "
                    f"not in antibiogram for hai_type {hai_type!r}"
                )
            antibiogram_drugs = set(antibiogram[hai_type][organism_snomed].keys())
            for drug_key in drug_list:
                if drug_key not in valid_drugs:
                    raise ValueError(
                        f"narrow_ladder.yaml: drug_key {drug_key!r} "
                        f"not in ANTIBIOTIC_DRUGS"
                    )
                if drug_key not in antibiogram_drugs:
                    raise ValueError(
                        f"narrow_ladder.yaml: drug_key {drug_key!r} for "
                        f"{hai_type}/{organism_snomed} not in antibiogram "
                        f"(combination is clinically irrelevant — see "
                        f"hai_antibiogram.yaml omission rationale)"
                    )


@lru_cache(maxsize=1)
def load_narrow_ladder() -> dict[str, dict[str, list[str]]]:
    """Load + 3-way validate the PR3b-3 narrow ladder. Returns
    ``{hai_type: {organism_snomed: [drug_key, ...]}}`` where the list is the
    narrow→broad preference order."""
    raw = yaml.safe_load(_NARROW_LADDER_YAML.read_text(encoding="utf-8"))
    data = {k: dict(v) for k, v in dict(raw["narrow_ladder"]).items()}
    _validate_narrow_ladder(data)
    return data


@lru_cache(maxsize=1)
def load_hai_empirical() -> dict[str, dict[str, Any]]:
    """Load + validate empirical regimens.

    Returns ``{hai_type: {"duration_days": int, "drugs": [{"drug_key", "dose",
    "route", "frequency"}, ...]}}``. Raises ``ValueError`` at import time if
    keys violate ``HAI_TYPES`` or any drug_key violates ``ANTIBIOTIC_DRUGS``.
    """
    raw = yaml.safe_load(_HAI_EMPIRICAL_YAML.read_text(encoding="utf-8"))
    data = dict(raw["hai_empirical"])

    unknown_hai = set(data) - set(HAI_TYPES)
    if unknown_hai:
        raise ValueError(
            f"hai_empirical.yaml has unknown hai_type keys "
            f"{sorted(unknown_hai)} - must use HAI_TYPES {HAI_TYPES} "
            f"(case-sensitive)"
        )

    for hai_type, cfg in data.items():
        for drug in cfg["drugs"]:
            if drug["drug_key"] not in ANTIBIOTIC_DRUGS:
                raise ValueError(
                    f"hai_empirical.yaml [{hai_type}]: unknown drug_key "
                    f"{drug['drug_key']!r} - must be in canonical "
                    f"ANTIBIOTIC_DRUGS {ANTIBIOTIC_DRUGS}"
                )

    return data


def _drug_slug(drug_key: str) -> str:
    """canonical drug_key -> URL-safe slug for regimen_id."""
    return drug_key.lower().replace("/", "_")


def build_regimens(
    hai_event: HAIEvent,
    start_datetime: datetime,
) -> list[AntibioticRegimen]:
    """Build the empirical regimens for one HAI event.

    Returns one AntibioticRegimen per drug in the HAI type's empirical
    config. Raises ``KeyError`` if hai_event.hai_type is not present
    in hai_empirical.yaml (already gated by load_hai_empirical's
    import-time validation, so this is defense-in-depth).
    """
    cfg = load_hai_empirical()[hai_event.hai_type]
    duration_days = int(cfg["duration_days"])
    out: list[AntibioticRegimen] = []
    for drug in cfg["drugs"]:
        slug = _drug_slug(drug["drug_key"])
        out.append(AntibioticRegimen(
            regimen_id=f"abx-{hai_event.hai_id}-{slug}",
            hai_event_id=hai_event.hai_id,
            encounter_id=hai_event.encounter_id,
            drug_key=drug["drug_key"],
            dose=drug["dose"],
            route=drug["route"],
            frequency=drug["frequency"],
            start_datetime=start_datetime,
            duration_days=duration_days,
            intent="empirical",
        ))
    return out


def generate_mar_doses(
    regimen: AntibioticRegimen,
    snapshot_datetime: datetime,
    order_id: str,
) -> list[MedicationAdministration]:
    """Materialize per-dose MAR records spanning [start_dt, start_dt + duration_days).

    Doses are evenly spaced (24h / freq_per_day) starting at
    ``regimen.start_datetime``. Doses after ``snapshot_datetime`` are
    truncated (AD-32). Raises ``KeyError`` if ``regimen.frequency``
    is not in ``FREQ_PER_DAY``.
    """
    freq = FREQ_PER_DAY[regimen.frequency]
    spacing = timedelta(hours=24 // freq)
    total_doses = regimen.duration_days * freq
    out: list[MedicationAdministration] = []
    for i in range(total_doses):
        sched = regimen.start_datetime + spacing * i
        if sched > snapshot_datetime:
            break
        out.append(MedicationAdministration(
            order_id=order_id,
            drug_name=ANTIBIOTIC_DRUGS.get(regimen.drug_key, {}).get(
                "name", regimen.drug_key
            ),
            scheduled_datetime=sched,
            actual_datetime=sched,
            status="given",
            dose=regimen.dose,
            route=regimen.route,
        ))
    return out


# ---------------------------------------------------------------------------
# PR3b-3: narrow / de-escalation pure helpers (consumed by enricher Pass 2)
# ---------------------------------------------------------------------------


class NarrowOutcome(Enum):
    """Three dispatched outcomes of narrow_outcome (PR3b-3 spec §2.4)."""
    NO_CHANGE = "no_change"     # case (iii): no target or target == single empirical
    ELIMINATION = "elimination"  # case (ii): target in multi-drug empirical, keep target
    SWITCH = "switch"            # case (i): target is a new drug not in empirical


def select_narrow_target(
    susceptibilities: list[SusceptibilityResult],
    ladder_for_organism: list[str],
) -> str | None:
    """Walk ladder top-down. Return the first drug_key whose
    SusceptibilityResult.interpretation == 'S'. Returns None if no S in
    ladder (all-non-S, empty ladder, or empty susceptibilities)."""
    susc_by_loinc = {s.antibiotic_loinc: s.interpretation for s in susceptibilities}
    for drug_key in ladder_for_organism:
        loinc = ANTIBIOTIC_LOINC_LOOKUP.get(drug_key)
        if loinc is None:
            continue  # defensive: drug_key not in central LOINC lookup
        if susc_by_loinc.get(loinc) == "S":
            return drug_key
    return None


def narrow_outcome(
    narrow_target: str | None,
    empirical_regimens: list[AntibioticRegimen],
) -> NarrowOutcome:
    """Dispatch the three narrowing-by-elimination cases (PR3b-3 spec §2.4)."""
    if narrow_target is None:
        return NarrowOutcome.NO_CHANGE
    empirical_drug_keys = {r.drug_key for r in empirical_regimens}
    if narrow_target not in empirical_drug_keys:
        return NarrowOutcome.SWITCH
    # narrow_target in empirical_drug_keys
    if len(empirical_drug_keys) == 1:
        # case (iii): single empirical equals target → nothing to narrow
        return NarrowOutcome.NO_CHANGE
    # case (ii): multi-empirical, keep target drop others
    return NarrowOutcome.ELIMINATION


def narrow_duration_days(
    empirical_start: datetime, reported: datetime, total_course: int,
) -> int:
    """Total course minus elapsed empirical days. Clamps at 0 (no negative)."""
    elapsed = (reported - empirical_start).days
    return max(0, total_course - elapsed)
