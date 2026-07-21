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

from clinosim.modules._shared import sanitize_id_token
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


# Canonical id prefixes for antibiotic regimens / orders (PR3b-3 stage-2
# adversarial finding F3, 2026-06-29). Audit gates that filter MedicationRequest
# by antibiotic origin (clinosim/audit/axes/clinical.py narrow-rate gate) import
# these constants instead of duplicating literals, so a rename here triggers an
# ImportError downstream rather than a silent gate skip — same defense pattern
# as MB_ORG_ID_PREFIX in _fhir_microbiology.py.
ABX_REGIMEN_ID_PREFIX = "abx-"  # AntibioticRegimen.regimen_id
ABX_ORDER_REQ_PREFIX = "req-"  # Order.order_id = "req-" + regimen_id
ABX_ORDER_ID_PREFIX = ABX_ORDER_REQ_PREFIX + ABX_REGIMEN_ID_PREFIX  # composed prefix for readers
# ABX_NARROW_SUFFIX: shortened from "-narrowed" (9 chars) to "-n" (2 chars) in
# Issue #347 (session 63) to keep composed MedicationRequest.id
#   req- (4) + abx- (4) + hai-{enc_id 26}-{hai_type 3-6}-{index 1-2}- (~37)
#   + {drug_slug ≤15} + {suffix}
# under FHIR R4's 64-char Resource.id limit. Concrete failure that motivated
# the change: v16 (seed=700) validation on 2026-07-21 emitted
#   req-abx-hai-ENC-POP-000905-266868769799-vap-0-ceftriaxone-narrowed  (66)
# which HAPI rejected as `Invalid Resource id ... exceeds the max length of 64`.
# With the short suffix the same id is 59 chars.
ABX_NARROW_SUFFIX = "-n"  # narrowed regimen id suffix


FREQ_PER_DAY: dict[str, int] = {
    "q24h": 1,
    "q12h": 2,
    "q8h": 3,
    "q6h": 4,
    "q4h": 6,
}


def _validate_narrow_ladder(data: dict[str, dict[str, list[str]]]) -> None:
    """4-way cross-validation: every (hai_type, organism, drug_key) entry must
    be in HAI_TYPES + hai_antibiogram + ANTIBIOTIC_DRUGS, AND every
    (hai_type, organism) in the antibiogram MUST have a ladder entry
    (reverse-coverage = adversarial-1 fix). Empty top-level / empty drug
    list also rejected. Raises ValueError at load time to surface
    silent-no-op risk (PR-90 教訓 / CLAUDE.md silent-no-op defense triplet)."""
    from clinosim.modules.hai import load_hai_antibiogram  # local: avoid circular import

    if not data:
        raise ValueError("narrow_ladder.yaml: empty narrow_ladder (PR-90 class silent no-op)")

    antibiogram = load_hai_antibiogram()
    valid_hai_types = set(HAI_TYPES)
    valid_drugs = set(ANTIBIOTIC_DRUGS.keys())

    # Forward: every ladder entry is valid
    for hai_type, organism_map in data.items():
        if hai_type not in valid_hai_types:
            raise ValueError(
                f"narrow_ladder.yaml: unknown hai_type {hai_type!r}, expected one of {sorted(valid_hai_types)}"
            )
        if not organism_map:
            raise ValueError(
                f"narrow_ladder.yaml: hai_type {hai_type!r} has empty organism map (PR-90 class silent no-op)"
            )
        for organism_snomed, drug_list in organism_map.items():
            if not drug_list:
                raise ValueError(
                    f"narrow_ladder.yaml: empty drug list for {hai_type}/{organism_snomed} (PR-90 class silent no-op)"
                )
            if organism_snomed not in antibiogram.get(hai_type, {}):
                raise ValueError(
                    f"narrow_ladder.yaml: organism {organism_snomed!r} not in antibiogram for hai_type {hai_type!r}"
                )
            antibiogram_drugs = set(antibiogram[hai_type][organism_snomed].keys())
            for drug_key in drug_list:
                if drug_key not in valid_drugs:
                    raise ValueError(f"narrow_ladder.yaml: drug_key {drug_key!r} not in ANTIBIOTIC_DRUGS")
                if drug_key not in antibiogram_drugs:
                    raise ValueError(
                        f"narrow_ladder.yaml: drug_key {drug_key!r} for "
                        f"{hai_type}/{organism_snomed} not in antibiogram "
                        f"(combination is clinically irrelevant — see "
                        f"hai_antibiogram.yaml omission rationale)"
                    )

    # Reverse: every (hai_type, organism) in antibiogram must have a ladder entry
    # (adversarial-1 fix). Otherwise a new antibiogram organism silently no-ops
    # narrow attempts for that organism — exact PR-90 class regression.
    for hai_type, organisms in antibiogram.items():
        ladder_organisms = set(data.get(hai_type, {}).keys())
        missing = set(organisms.keys()) - ladder_organisms
        if missing:
            raise ValueError(
                f"narrow_ladder.yaml: hai_type {hai_type!r} missing ladder "
                f"entries for antibiogram organism(s) {sorted(missing)}. "
                f"Every (hai_type, organism) in hai_antibiogram.yaml MUST have "
                f"a corresponding ladder entry, otherwise narrow Pass 2 "
                f"silently no-ops for that organism (PR-90 class regression)."
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

    # Adversarial-2 stage-3 fix (Agent A2 sibling sweep): reverse-coverage.
    # Every HAI_TYPES member MUST have an empirical regimen, otherwise a new
    # HAI_TYPE addition (e.g., 'ssi') would silently no-op PR3b-1 empirical
    # emission for that type until first KeyError at runtime. Matches the
    # same defense pattern adv-1 introduced for narrow_ladder (PR-90 class).
    missing_hai = set(HAI_TYPES) - set(data)
    if missing_hai:
        raise ValueError(
            f"hai_empirical.yaml missing HAI_TYPES key(s) {sorted(missing_hai)}. "
            f"Every HAI_TYPES member MUST have an empirical regimen, otherwise "
            f"PR3b-1 enricher silently no-ops for that type (PR-90 class)."
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


# Long drug names would blow the 64-char FHIR id budget once composed with the
# `req-abx-{hai_id}-` prefix (~49 chars leaves ~15 for the slug). Keep the slug
# clinically recognizable rather than truncating mid-word.
# Issue #347 (session 63): expanded coverage to all HAI empirical drugs whose
# canonical drug_key exceeds 10 chars, since worst-case composition
# `req-abx-{hai_id 37}-{slug}-n` gives {slug} a ~14-char budget once the
# narrowed suffix is present. `ceftriaxone` (11) hit the limit in v16
# (2026-07-21). Sibling drugs added preemptively even when their length would
# fit today, so a future HAI YAML edit does not silently reintroduce a >64 id.
_DRUG_SLUG_OVERRIDES: dict[str, str] = {
    "piperacillin_tazobactam": "pip-tazo",
    "trimethoprim_sulfamethoxazole": "tmp-smx",
    "ceftriaxone": "cft",
    "cefepime": "cfp",
    "meropenem": "mero",
    "vancomycin": "vanc",
    "amikacin": "amk",
    "levofloxacin": "levo",
    "linezolid": "lnz",
    "daptomycin": "dap",
    "ciprofloxacin": "cipro",
}


def _drug_slug(drug_key: str) -> str:
    """Canonical drug_key -> FHIR-id-safe slug for regimen_id.

    FHIR R4 restricts `Resource.id` to ``[A-Za-z0-9\\-\\.]{1,64}`` (session
    52 fix, iris4h-ai P0 finding 2026-07-17). Route the drug_key through
    ``sanitize_id_token`` so any ``_`` / ``/`` / space gets normalized to
    ``-`` before it lands in an id string. Long drug names get a short
    clinical override so the composed id (``req-abx-{hai_id}-{slug}``,
    ~49 chars overhead, up to 51 with the ``-n`` narrowed suffix) stays
    under the 64-char limit.
    """
    slug = _DRUG_SLUG_OVERRIDES.get(drug_key.lower())
    if slug is not None:
        return slug
    return sanitize_id_token(drug_key.lower(), max_len=15)


# FHIR R4 Resource.id max length. Used by the guard below and by tests.
_FHIR_ID_MAX_LENGTH = 64


def _check_fhir_id_length(id_value: str, resource_kind: str) -> None:
    """Fail-loud guard: raises ValueError if the constructed id exceeds
    the FHIR R4 Resource.id max length of 64. Same defensive spirit as
    ``sanitize_id_token``; caught here at the builder rather than at
    HAPI validation time when the offending resource may already have
    been persisted and referenced from other bundles.

    Issue #347 (session 63): the composed
    ``req-abx-{hai_id}-{drug_slug}-narrowed`` id hit 66 chars in v16
    (2026-07-21) with drug_key=ceftriaxone. This guard would have
    surfaced the problem at generate time instead of only at validation.
    """
    if len(id_value) > _FHIR_ID_MAX_LENGTH:
        raise ValueError(
            f"{resource_kind} id {id_value!r} is {len(id_value)} chars, "
            f"exceeds FHIR R4 Resource.id max length {_FHIR_ID_MAX_LENGTH}. "
            f"Add an entry to `_DRUG_SLUG_OVERRIDES` or shorten the id prefix."
        )


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
        regimen_id = f"{ABX_REGIMEN_ID_PREFIX}{hai_event.hai_id}-{slug}"
        # Issue #347 guard: the composed Order.id later prepends "req-" (4 chars),
        # so validate the total downstream id length here rather than at HAPI time.
        _check_fhir_id_length(ABX_ORDER_REQ_PREFIX + regimen_id, "MedicationRequest")
        out.append(
            AntibioticRegimen(
                regimen_id=regimen_id,
                hai_event_id=hai_event.hai_id,
                encounter_id=hai_event.encounter_id,
                drug_key=drug["drug_key"],
                dose=drug["dose"],
                route=drug["route"],
                frequency=drug["frequency"],
                start_datetime=start_datetime,
                duration_days=duration_days,
                intent="empirical",
            )
        )
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
        out.append(
            MedicationAdministration(
                order_id=order_id,
                drug_name=ANTIBIOTIC_DRUGS.get(regimen.drug_key, {}).get("name", regimen.drug_key),
                scheduled_datetime=sched,
                actual_datetime=sched,
                status="given",
                dose=regimen.dose,
                route=regimen.route,
            )
        )
    return out


# ---------------------------------------------------------------------------
# PR3b-3: narrow / de-escalation pure helpers (consumed by enricher Pass 2)
# ---------------------------------------------------------------------------


class NarrowOutcome(Enum):
    """Three dispatched outcomes of narrow_outcome (PR3b-3 spec §2.4)."""

    NO_CHANGE = "no_change"  # case (iii): no target or target == single empirical
    ELIMINATION = "elimination"  # case (ii): target in multi-drug empirical, keep target
    SWITCH = "switch"  # case (i): target is a new drug not in empirical


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
    empirical_start: datetime,
    reported: datetime,
    total_course: int,
) -> int:
    """Total course minus elapsed empirical days. Clamps at 0 (no negative)."""
    elapsed = (reported - empirical_start).days
    return max(0, total_course - elapsed)
