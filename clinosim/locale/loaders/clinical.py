"""Clinical / population locale loaders — specialty routing, chronic
medications, pregnancy substitutions, perinatal / actuarial / mortality /
chemo configs, lab reference ranges, chronic follow-up, health screening,
IV infusion defaults.

Extracted from the historical god-file ``clinosim/locale/loader.py`` as
step C2a of the full-review Phase C locale split, continuing the B1
pattern (narrative loader cluster → ``locale/loaders/narrative.py``).

Every function is re-exported at module scope on ``clinosim.locale.loader``
so each historical ``from clinosim.locale.loader import load_X`` call
site keeps working unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from clinosim.locale._io import _LOCALE_DIR, _country_dir, _load_yaml


@lru_cache(maxsize=1)
def load_specialty_routing() -> list[dict[str, Any]]:
    """Load Phase 1 specialty-routing table (chronic → specialty + cadence).

    Issue #1698 Phase 1. Returns the ``routes:`` list from
    ``clinosim/locale/shared/specialty_routing.yaml`` or ``[]`` when the
    file is missing / malformed. Each row carries ``requires_chronic`` or
    ``requires_chronic_prefix`` (list[str]) + ``specialty`` (str) +
    ``cadence`` (str ∈ {"annual", "semi_annual", "quarterly"}) +
    ``clinical_basis`` (free-text citation).
    """
    data = _load_yaml(_LOCALE_DIR / "shared" / "specialty_routing.yaml", fallback={})
    routes = data.get("routes") if isinstance(data, dict) else None
    return list(routes) if isinstance(routes, list) else []


@lru_cache(maxsize=1)
def load_chronic_medications() -> dict[str, Any]:
    """Load chronic condition home medications and monitoring rules.

    Issue #458: import-time route vocabulary validation. Same silent-no-op
    class as the disease / encounter YAMLs; an unknown `route:` string here
    would silently emit `{"text": VALUE}` with no SNOMED coding on the FHIR
    side.
    """
    data = _load_yaml(_LOCALE_DIR / "shared" / "chronic_medications.yaml", fallback={})
    _validate_chronic_medications_route_vocabulary(data)
    return data


def _iter_route_values(data: Any) -> Iterator[str]:
    """Yield every `route:` string found anywhere in a nested YAML structure.

    Third copy of this walker (sibling to disease/protocol.py and
    encounter/protocol.py). Kept local so the `locale` package retains its
    "loader lives with the data" convention and does not depend on either.
    """
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "route" and isinstance(v, str):
                yield v
            else:
                yield from _iter_route_values(v)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_route_values(item)


def _validate_chronic_medications_route_vocabulary(data: Any) -> None:
    """Delegate to the single-sourced canonical validator (Issue #458)."""
    from clinosim.modules.output.fhir_r4.lib.reference_data import validate_yaml_route_value

    for raw in _iter_route_values(data):
        validate_yaml_route_value(raw, source="chronic_medications.yaml")


@lru_cache(maxsize=1)
def load_pregnancy_substitutions() -> dict[str, dict[str, Any]]:
    """Load pregnancy-contraindicated → pregnancy-safe drug substitution table
    (Issue #1321, META #1392 Cluster A part 5).

    Returned as ``{original_drug_name: {substitute: ..., dose: ..., ...}}``
    for direct O(1) lookup at outpatient prescription-renewal time. Falls
    back to empty dict if the YAML is missing (defensive)."""
    data = _load_yaml(_LOCALE_DIR / "shared" / "pregnancy_substitutions.yaml", fallback={})
    return data.get("substitutions", {}) or {}


@lru_cache(maxsize=1)
def load_perinatal_config() -> dict[str, Any]:
    """Load perinatal delivery configuration (Issue #957 Tier-3-B).

    Consumers query the ``encounter`` block for admission/discharge
    diagnosis + LOS + department, the ``procedure`` block for the
    JP/US billing code emitted on the delivery encounter, and the
    ``scheduling`` block for the delivery-month range used by the
    healthcare-calendar delivery-event scheduler.
    """
    return _load_yaml(_LOCALE_DIR / "shared" / "perinatal.yaml", fallback={})


@lru_cache(maxsize=1)
def load_actuarial_life_table() -> dict[str, Any]:
    """Load all-cause age × sex annual mortality qx for US + JP (Issue #1114 C11g-1).

    Top-level shape:
        annual_mortality_qx.<country>.<sex>.<age_lower> -> qx  (float, [0, 1])
        provenance.<country> -> {source, reference_year, document, tables_consulted}

    Values are 5-year band means of single-year qx from national period
    life tables (US CDC NVSR 71-01 2020; JP 厚労省 第23回完全生命表 2020).
    Data-only scaffold — no consumer yet; C11g-2 wires it into the
    population activator's natural-death step.
    """
    return _load_yaml(_LOCALE_DIR / "shared" / "actuarial_life_table.yaml", fallback={})


@lru_cache(maxsize=1)
def load_condition_mortality_smr() -> dict[str, Any]:
    """Load the sparse per-ICD SMR table used by the aging hook's
    ``_condition_reactive_mortality`` pass (Issue #1564 Phase 2).

    Top-level shape:
        smr_table.<icd> -> float (≥ 1.0 typically)
        combine_method -> str ("geometric_mean")
        max_excess_qx_per_year -> float (hard cap on added yearly qx)
    """
    return _load_yaml(_LOCALE_DIR / "shared" / "condition_mortality_smr.yaml", fallback={})


@lru_cache(maxsize=1)
def load_comorbidity_progression_multipliers() -> dict[str, Any]:
    """Load comorbidity interaction config for the aging hook's
    ``_disease_progression`` pass. Describes how one chronic condition
    accelerates another's stage progression — e.g. diabetes with poor
    glycemic control accelerating CKD stage transitions (diabetic
    nephropathy).

    Top-level shape:
        comorbidity_progression_multipliers.<target_icd>.<rule_name>
          .requires_any_chronic -> list[str] (any-match trigger ICDs)
          .glycemic_tiers -> list[{gc_lt: float, multiplier: float}]
                             (optional; applied in listed order, first
                             matching tier wins)
          .default_multiplier -> float (optional; applied when the
                             trigger matches but no gc tier matches)

    Looked up by ``_comorbidity_multiplier`` at the point of applying
    the Bernoulli draw on the target's annual_advance_probability.
    """
    return _load_yaml(_LOCALE_DIR / "shared" / "comorbidity_progression_multipliers.yaml", fallback={})


@lru_cache(maxsize=1)
def load_single_gene_diseases() -> dict[str, Any]:
    """Load per-disease single-gene inheritance config for Issue #1581
    Phase C.3. Returns the shape documented in
    ``clinosim/locale/shared/single_gene_diseases.yaml``.

    Top-level shape:
        single_gene_diseases.<icd>.display -> str
        single_gene_diseases.<icd>.inheritance_pattern -> str
          ("autosomal_recessive" | "x_linked_recessive")
        single_gene_diseases.<icd>.carrier_frequency_by_race ->
          dict[str, float]  # race → carrier frequency (hetero + homo)
    """
    return _load_yaml(_LOCALE_DIR / "shared" / "single_gene_diseases.yaml", fallback={})


@lru_cache(maxsize=1)
def load_chemo_regimens() -> dict[str, Any]:
    """Load chemotherapy regimen library + per-cancer assignment table.

    Issue #957 Tier-3-A: cycle-based chemotherapy scheduling. Consumers
    (population healthcare-calendar generator, chemo_visit emit path)
    query the top-level ``regimens`` dict for cycle interval / drugs /
    course_cycles, ``by_cancer`` for the per-cancer-code assignment
    probability distribution, ``procedure`` for the JP/US billing code
    on the emitted Procedure resource, and ``encounter`` for the visit
    reason string.
    """
    return _load_yaml(_LOCALE_DIR / "shared" / "chemo_regimens.yaml", fallback={})


@lru_cache(maxsize=8)
def load_reference_ranges(country: str) -> dict[str, Any]:
    """Load lab reference range data for a country.

    Returns dict with 'source_url', 'source_name', and 'ranges' keys.
    Example: load_reference_ranges("JP") -> {"ranges": {"CRP": [{"low": 0, ...}], ...}}
    """
    return _load_yaml(_country_dir(country) / "reference_range_lab.yaml", fallback={})


@lru_cache(maxsize=1)
def load_chronic_followup() -> dict[str, Any]:
    """Load chronic disease outpatient follow-up schedules."""
    return _load_yaml(_LOCALE_DIR / "shared" / "chronic_followup.yaml", fallback={})


@lru_cache(maxsize=1)
def load_health_screening_visit_reason() -> dict[str, Any]:
    """Load cross-locale visit-reason display for `health_screening` events.

    Keyed by screening sub-kind (`event.disease_id`); each entry carries
    `en` + `ja` display. A `fallback` key supplies the generic bilingual
    pair when a sub-kind has no explicit row. Consumed by
    ``clinosim/simulator/engine.py`` at the `generate_healthcare_calendar`
    emission point — hardcoded-review Phase A7.
    """
    return _load_yaml(
        _LOCALE_DIR / "shared" / "health_screening_visit_reason.yaml",
        fallback={},
    )


@lru_cache(maxsize=1)
def load_iv_infusion_defaults() -> dict[str, Any]:
    """Load per-drug default IV infusion rate / bolus duration catalog.

    Referenced by ``clinosim.modules.output.fhir_r4.lib.common
    .resolve_iv_infusion_default`` when emitting ``MedicationRequest
    .dosageInstruction.doseAndRate.rateQuantity`` (continuous drips) or
    ``dosageInstruction.timing.repeat.duration`` (intermittent bolus) for
    IV-route orders — Issue #966.

    Returned shape:

        {
          "drugs":  {<normalized name>: {"mode": ..., "rate_value": N, ...}},
          "aliases": {<shorthand>: <catalog key>},
          "default": {"mode": "bolus", "duration_min": 30},
        }

    Single source of truth for tunable clinical constants
    (feedback_constants_live_in_external_config.md); the Python side holds
    only mode dispatch logic and the fallback default block.
    """
    return _load_yaml(_LOCALE_DIR / "shared" / "iv_infusion_defaults.yaml", fallback={})
