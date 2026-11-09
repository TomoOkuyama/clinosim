"""Allergy module engine (Tier 1 #3 α-min-1 PR1).

Loader + validator (silent-no-op defense) + POST_POPULATION enricher。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator, model_validator

from clinosim import determinism
from clinosim.age_bands import lookup_age_band, parse_age_band
from clinosim.codes import code_exists
from clinosim.datafiles import load_validated_yaml
from clinosim.modules._shared import normalize_probabilities
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.allergy import Allergy, AllergyReaction

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

SUPPORTED_ALLERGEN_CATEGORIES: frozenset[str] = frozenset({"medication", "food", "environment"})

OVERALL_ALLERGY_PREVALENCE = 0.15  # baseline calibrated (see brief Step 4)
CATEGORY_WEIGHTS = {"medication": 0.50, "food": 0.25, "environment": 0.25}

# ---------------------------------------------------------------------------
# Clinical + verification status distribution (Issue #637)
# Empirical tuning for the synthetic simulator, matched to observed EHR
# allergy-status distributions: ~85% active + confirmed, ~5% resolved
# (childhood food allergies outgrown), ~10% active + unconfirmed
# (patient-reported, not challenge-verified).
# ---------------------------------------------------------------------------

ALLERGY_FOOD_RESOLVED_MAX_EXCLUSIVE: float = 0.05
"""Probability draw cutoff below which a food-category allergy is
coded as ``clinical="resolved"`` + ``verification="confirmed"``.
Only fires for the food category — non-food allergies almost never
resolve at the population level, so the "resolved" bucket is
food-only by design."""

ALLERGY_UNCONFIRMED_MAX_EXCLUSIVE: float = 0.15
"""Cumulative probability draw cutoff (checked as ``elif`` after the
food-resolved branch) below which the allergy is coded as
``clinical="active"`` + ``verification="unconfirmed"``. Since the
first 5% is claimed by the food-resolved branch, this yields ~10%
unconfirmed across categories (5-15 %). Above this cutoff (the
remaining 85%) allergies are coded as active + confirmed."""


# A YAML number (not a numeric string or a bool-as-string).
_Number = StrictInt | StrictFloat


def _registered_snomed(code: str, where: str) -> str:
    """AD-30 chain: every SNOMED code must resolve in codes/data/snomed-ct.yaml
    (the CIF carries no fallback display for an unresolvable code)."""
    if not code_exists("snomed-ct", code, exact=True):
        raise ValueError(f"allergens.yaml {where} {code!r} not in codes/data/snomed-ct.yaml")
    return code


def _probability(value: _Number, where: str) -> _Number:
    if not 0 <= value <= 1:
        raise ValueError(f"allergens.yaml {where}: 0..1 expected, got {value!r}")
    return value


class _Reaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifestation_snomed: str
    severity: Literal["mild", "moderate", "severe"]

    @field_validator("manifestation_snomed")
    @classmethod
    def _registered(cls, code: str) -> str:
        if not code:
            raise ValueError("missing manifestation_snomed")
        return _registered_snomed(code, "manifestation_snomed")


class _Allergen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allergen_code: str
    prevalence: dict[str, Any]
    criticality: Any
    common_reactions: list[_Reaction] = Field(min_length=1)

    @field_validator("allergen_code")
    @classmethod
    def _registered(cls, code: str) -> str:
        return _registered_snomed(code, "allergen_code")

    @field_validator("prevalence")
    @classmethod
    def _adult_prevalence_is_a_probability(cls, prevalence: dict[str, Any]) -> dict[str, Any]:
        adult = prevalence.get("adult")
        if "adult" not in prevalence or not isinstance(adult, (int, float)):
            raise ValueError(f"prevalence: must have a numeric 'adult' key, got {adult!r}")
        _probability(adult, "prevalence.adult")
        return prevalence


class _NoKnownAllergy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allergen_code: str
    clinical_status: Any
    verification_status: Any

    @field_validator("allergen_code")
    @classmethod
    def _registered(cls, code: str) -> str:
        return _registered_snomed(code, "nka.allergen_code")


def _age_banded_probabilities(table: dict[str, _Number]) -> dict[str, _Number]:
    """Age-band keys ("0-17", "18-64", "65+") that cover every age from 0
    once, the last band open-ended; values are probabilities (Issue #2843)."""
    field = "polyallergy.probability_given_any_allergy"
    if not table:
        raise ValueError(f"{field}: at least one age band expected")
    bands = sorted(((parse_age_band(k), k) for k in table), key=lambda b: b[0][0])
    expected_lo = 0
    for i, ((lo, hi), key) in enumerate(bands):
        if lo != expected_lo:
            raise ValueError(f"{field}: band {key!r} starts at {lo}, expected {expected_lo} (gap or overlap)")
        _probability(table[key], field)
        if hi is None:
            if i != len(bands) - 1:
                raise ValueError(f"{field}: open-ended band {key!r} must be the last one")
            return table
        expected_lo = hi + 1
    raise ValueError(f"{field}: the last age band must be open-ended (e.g. '65+')")


class _Polyallergy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probability_given_any_allergy: dict[str, _Number]
    additional_count_weights: dict[Any, _Number] = Field(min_length=1)
    chronic_ill_bonus: _Number = 0.0
    chronic_ill_conditions: list[str] = Field(default_factory=list)

    _bands = field_validator("probability_given_any_allergy")(classmethod(lambda cls, v: _age_banded_probabilities(v)))

    @field_validator("additional_count_weights")
    @classmethod
    def _non_negative(cls, weights: dict[Any, _Number]) -> dict[Any, _Number]:
        negative = sorted(k for k, v in weights.items() if v < 0)
        if negative:
            raise ValueError(f"allergens.yaml polyallergy.additional_count_weights{negative}: non-negative expected")
        return weights


class _CrossReactivityRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_allergen_codes: Any
    boost_category: Any
    boost_weight_bonus: Any


class _ChildhoodFoodResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_age_cutoff: StrictInt
    annual_rate_child: _Number
    annual_rate_adult: _Number


class _LateOnsetDrugSensitivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adult_age_floor: StrictInt
    elderly_age_floor: StrictInt
    annual_rate_adult: _Number
    annual_rate_elderly: _Number


class _Aging(BaseModel):
    """Yearly allergy drift (read by ``population.aging._allergy_drift``)."""

    model_config = ConfigDict(extra="forbid")

    childhood_food_resolution: _ChildhoodFoodResolution | None = None
    late_onset_drug_sensitivity: _LateOnsetDrugSensitivity | None = None


class AllergenConfig(BaseModel):
    """Shape of allergens.yaml (silent-no-op defense): a non-empty entry list
    for exactly the supported categories, each entry with a registered
    allergen code, an adult prevalence in 0..1 and registered reaction
    manifestations; the ``nka`` / ``polyallergy`` blocks (Issue #942); and an
    optional well-formed ``cross_reactivity`` list."""

    model_config = ConfigDict(extra="forbid")

    allergens: dict[str, list[_Allergen]]
    nka: _NoKnownAllergy
    polyallergy: _Polyallergy
    cross_reactivity: list[_CrossReactivityRule] | None = None
    aging: _Aging | None = None
    # Issue #3108: youngest age (completed months) per category.
    minimum_age_months: dict[str, StrictInt]

    @field_validator("minimum_age_months")
    @classmethod
    def _every_category(cls, months: dict[str, int]) -> dict[str, int]:
        if set(months) != SUPPORTED_ALLERGEN_CATEGORIES:
            raise ValueError(
                f"allergens.yaml minimum_age_months: one entry per category expected, got {sorted(months)}"
            )
        negative = sorted(c for c, m in months.items() if m < 0)
        if negative:
            raise ValueError(f"allergens.yaml minimum_age_months{negative}: non-negative expected")
        return months

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        if not data:
            raise ValueError("allergens.yaml: empty top-level")
        return data

    @field_validator("allergens")
    @classmethod
    def _supported_categories_each_non_empty(cls, allergens: dict[str, list[_Allergen]]) -> dict[str, list[_Allergen]]:
        keys = set(allergens)
        if keys != SUPPORTED_ALLERGEN_CATEGORIES:
            missing, extra = SUPPORTED_ALLERGEN_CATEGORIES - keys, keys - SUPPORTED_ALLERGEN_CATEGORIES
            raise ValueError(
                f"allergens.yaml ↔ SUPPORTED_ALLERGEN_CATEGORIES drift: "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        empty = sorted(cat for cat, entries in allergens.items() if not entries)
        if empty:
            raise ValueError(f"allergens.yaml{empty}: empty list")
        return allergens


@lru_cache(maxsize=1)
def load_allergens() -> dict[str, Any]:
    """Load allergens.yaml + validate. Cached singleton.

    Returns only the ``allergens:`` bucket for backwards compatibility with
    all pre-#942 call sites. NKA / polyallergy / cross-reactivity blocks
    are read via :func:`load_allergen_config`.
    """
    return load_validated_yaml(_REF_DIR / "allergens.yaml", AllergenConfig)["allergens"]


@lru_cache(maxsize=1)
def load_allergen_config() -> dict[str, Any]:
    """Load full allergens.yaml (allergens + nka + polyallergy + cross_reactivity).

    Issue #942: the enricher needs the sibling blocks; kept separate from
    :func:`load_allergens` so legacy callers keep the plain allergen-catalog
    view.
    """
    return load_validated_yaml(_REF_DIR / "allergens.yaml", AllergenConfig)


def _make_nka(nka_cfg: dict[str, Any]) -> Allergy:
    """Build the NKA (No Known Allergies) positive-assertion CIF record.

    Category / reactions are intentionally empty — NKA is a resource-shape
    marker, not a substance/reaction record. The FHIR builder consumes
    ``is_nka`` and emits the SNOMED 716186003 code with the correct
    displays and clinical/verification status (Issue #942).
    """
    return Allergy(
        allergy_id="nka",
        allergen_code=str(nka_cfg["allergen_code"]),
        category="",  # NKA has no category (empty AllergyIntolerance.category[])
        criticality="unable-to-assess",  # criticality unknown for absence
        verification_status=str(nka_cfg["verification_status"]),
        clinical_status=str(nka_cfg["clinical_status"]),
        onset_date=None,
        reactions=[],  # no reactions for NKA
        is_nka=True,
    )


def age_months_at_start(person: Any, config: Any) -> int:
    """Completed months of age at the start of the simulation (Issue #3108):
    from the date of birth when the window is known (0 for a person born
    later), else the whole years of ``age``."""
    from clinosim.modules.population.mortality import sim_window

    window = sim_window(config)
    dob = getattr(person, "date_of_birth", None)
    if window is None or dob is None:
        return int(getattr(person, "age", 0) or 0) * 12
    start = window[0]
    months = (start.year - dob.year) * 12 + (start.month - dob.month) - (1 if start.day < dob.day else 0)
    return max(0, months)


def _documentable(allergies: list[Allergy], age_months: int, minimum: dict[str, int]) -> list[Allergy]:
    """The sampled allergies of a category the person is old enough to have
    on record (Issue #3108), renumbered from 1."""
    kept = [a for a in allergies if age_months >= int(minimum.get(a.category, 0))]
    for i, allergy in enumerate(kept):
        allergy.allergy_id = str(i + 1)
    return kept


def allergy_enricher(ctx: Any) -> None:
    """POST_POPULATION enricher: sample allergies per patient.

    Determinism via derive_sub_seed(master, ENRICHER_SEED_OFFSETS["allergy"],
    patient_id). Master stream unchanged.

    Sampling rule (Issue #942):
      1. per-patient sub-RNG (SHA256-derived) — master stream unchanged
      2. overall_allergy_prob gate (15%): patient carries ≥1 real allergen
      3. otherwise emit ONE NKA positive-assertion record (SNOMED 716186003)
      4. within the allergic branch, roll a polyallergy gate (age-conditional,
         with a chronic-illness bonus). Poly-positive patients get 2-4 total
         records; secondary allergens sampled without replacement from the
         allergen catalog. Cross-reactivity: if primary is penicillin, next
         allergen's category weights are shifted toward medication.
      5. an allergy of a category the patient is too young to have on
         record (``minimum_age_months``, age at the simulation start) is
         dropped after all draws (Issue #3108) — a newborn has none.
      6. every patient ends with ``allergies`` = list of ≥1 record — the
         empty list is never emitted (`feedback_empty_vs_wrong_assertion`).
    """
    cfg = load_allergen_config()
    allergens = cfg["allergens"]
    nka_cfg = cfg["nka"]
    poly_cfg = cfg["polyallergy"]
    cross_reactivity_rules = cfg.get("cross_reactivity", []) or []
    minimum_age_months = cfg["minimum_age_months"]

    categories = list(CATEGORY_WEIGHTS.keys())
    base_weights = [CATEGORY_WEIGHTS[c] for c in categories]

    # Flatten (category, entry) pairs for sampling-without-replacement in the
    # polyallergy branch. Pool order is stable (yaml load order) so RNG
    # index selection is reproducible.
    all_entries: list[tuple[str, dict[str, Any]]] = []
    for cat in categories:
        for entry in allergens[cat]:
            all_entries.append((cat, entry))

    poly_probs = poly_cfg["probability_given_any_allergy"]
    chronic_bonus = float(poly_cfg.get("chronic_ill_bonus", 0.0))
    chronic_prefixes = tuple(poly_cfg.get("chronic_ill_conditions", []) or [])
    additional_count_weights = poly_cfg["additional_count_weights"]
    poly_counts = sorted(int(k) for k in additional_count_weights.keys())
    poly_count_probs = [float(additional_count_weights[str(c)]) for c in poly_counts]

    for patient in ctx.population.persons.values():
        # PersonRecord uses person_id (Layer 1 naming); PatientProfile maps this to patient_id.
        pid = getattr(patient, "person_id", getattr(patient, "patient_id", ""))
        sub_seed = derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["allergy"], pid)
        rng = determinism.default_rng(sub_seed)

        # Gate: has the patient any real allergen at all?
        if rng.random() >= OVERALL_ALLERGY_PREVALENCE:
            # NKA positive-assertion: exactly 1 record, SNOMED 716186003.
            patient.allergies = [_make_nka(nka_cfg)]
            continue

        # ---- Real allergy branch ----
        # Pick primary allergen category-weighted.
        primary_cat = str(rng.choice(categories, p=normalize_probabilities(base_weights, fallback="raise")))
        primary_entries = allergens[primary_cat]
        primary_entry = primary_entries[int(rng.integers(0, len(primary_entries)))]
        primary_reaction = primary_entry["common_reactions"][0]

        # C1-17: sample clinical/verification status for the primary allergen.
        _stat_draw = float(rng.random())
        if _stat_draw < ALLERGY_FOOD_RESOLVED_MAX_EXCLUSIVE and primary_cat == "food":
            _clin_stat, _ver_stat = "resolved", "confirmed"
        elif _stat_draw < ALLERGY_UNCONFIRMED_MAX_EXCLUSIVE:
            _clin_stat, _ver_stat = "active", "unconfirmed"
        else:
            _clin_stat, _ver_stat = "active", "confirmed"

        allergies_out: list[Allergy] = [
            Allergy(
                allergy_id="1",
                allergen_code=primary_entry["allergen_code"],
                category=primary_cat,
                criticality=primary_entry["criticality"],
                verification_status=_ver_stat,
                clinical_status=_clin_stat,
                onset_date=None,
                reactions=[
                    AllergyReaction(
                        manifestation_snomed=primary_reaction["manifestation_snomed"],
                        severity=primary_reaction["severity"],
                    )
                ],
            )
        ]

        # ---- Polyallergy gate (age + chronic-illness conditional) ----
        age = int(getattr(patient, "age", 0) or 0)
        poly_prob = float(lookup_age_band(poly_probs, age, 0.0))
        chronic_list = getattr(patient, "chronic_conditions", []) or []
        if chronic_prefixes and any(isinstance(c, str) and c.startswith(chronic_prefixes) for c in chronic_list):
            poly_prob = min(0.85, poly_prob + chronic_bonus)

        if rng.random() < poly_prob:
            n_additional = int(
                rng.choice(
                    poly_counts,
                    p=normalize_probabilities(poly_count_probs, fallback="raise"),
                )
            )
            # Cross-reactivity: bias category weights if primary triggers a rule.
            secondary_cat_weights = list(base_weights)
            for rule in cross_reactivity_rules:
                if primary_entry["allergen_code"] in rule["trigger_allergen_codes"]:
                    boost_cat = str(rule["boost_category"])
                    if boost_cat in categories:
                        secondary_cat_weights[categories.index(boost_cat)] += float(rule["boost_weight_bonus"])

            used_codes = {primary_entry["allergen_code"]}
            for i in range(n_additional):
                # Draw category, then sample from that category's remaining entries.
                # Fall back across the whole catalog if the chosen category is exhausted.
                cat_choice = str(
                    rng.choice(
                        categories,
                        p=normalize_probabilities(secondary_cat_weights, fallback="raise"),
                    )
                )
                candidates = [e for e in allergens[cat_choice] if e["allergen_code"] not in used_codes]
                if not candidates:
                    candidates = [e for (_c, e) in all_entries if e["allergen_code"] not in used_codes]
                if not candidates:
                    break  # exhausted the catalog
                sec_entry = candidates[int(rng.integers(0, len(candidates)))]
                # Look up the real category of sec_entry (in case of catalog fallback).
                sec_cat = cat_choice
                for cat in categories:
                    if any(e["allergen_code"] == sec_entry["allergen_code"] for e in allergens[cat]):
                        sec_cat = cat
                        break
                sec_reaction = sec_entry["common_reactions"][0]
                # Secondary status draw — same 5/10/85 shape, independent of primary.
                _s_draw = float(rng.random())
                if _s_draw < ALLERGY_FOOD_RESOLVED_MAX_EXCLUSIVE and sec_cat == "food":
                    _sc, _sv = "resolved", "confirmed"
                elif _s_draw < ALLERGY_UNCONFIRMED_MAX_EXCLUSIVE:
                    _sc, _sv = "active", "unconfirmed"
                else:
                    _sc, _sv = "active", "confirmed"
                allergies_out.append(
                    Allergy(
                        allergy_id=str(len(allergies_out) + 1),
                        allergen_code=sec_entry["allergen_code"],
                        category=sec_cat,
                        criticality=sec_entry["criticality"],
                        verification_status=_sv,
                        clinical_status=_sc,
                        onset_date=None,
                        reactions=[
                            AllergyReaction(
                                manifestation_snomed=sec_reaction["manifestation_snomed"],
                                severity=sec_reaction["severity"],
                            )
                        ],
                    )
                )
                used_codes.add(sec_entry["allergen_code"])

        # Issue #3108: the draws above are made at every age; an allergy the
        # person is too young to have on record is dropped afterwards.
        kept = _documentable(
            allergies_out, age_months_at_start(patient, getattr(ctx, "config", None)), minimum_age_months
        )
        patient.allergies = kept or [_make_nka(nka_cfg)]
