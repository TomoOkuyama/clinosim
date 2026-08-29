"""Allergy module engine (Tier 1 #3 α-min-1 PR1).

Loader + validator (silent-no-op defense) + POST_POPULATION enricher。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

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


def _code_in_data(system: str, code: str) -> bool:
    """Direct membership check in codes/data/<system>.yaml.

    `lookup()` returns the code itself as fallback for unknown entries (not
    None), so it can't distinguish "code exists" from "code absent". Direct
    `cs.codes` membership IS the authoritative check (same pattern as
    `hai/engine.py:_code_in_data`).
    """
    from clinosim.codes.loader import _load_system

    cs = _load_system(system)
    if cs is None:
        raise ValueError(
            f"_code_in_data: code system {system!r} not registered in "
            f"clinosim/codes/data/ — system itself is missing, not the code"
        )
    return code in cs.codes


def _validate_allergens(data: dict[str, Any]) -> None:
    """Fail-loud validation of allergens.yaml (silent-no-op defense Layer 3-6).

    Layer 3: empty top + per-bucket guards
    Layer 4: forward + reverse coverage vs SUPPORTED_ALLERGEN_CATEGORIES
    Layer 5: validator runs BEFORE data is returned (pre-register ordering)
    Layer 6: required-field check per entry + prevalence range 0..1
    Layer 6b (AD-30 chain): allergen_code + every common_reactions[].manifestation_snomed
      must resolve in codes/data/snomed-ct.yaml (safety net now that the CIF
      no longer carries a fallback display string for unresolvable codes).
    """
    if not data:
        raise ValueError("allergens.yaml: empty top-level")
    allergens = data.get("allergens")
    if not allergens or not isinstance(allergens, dict):
        raise ValueError("allergens.yaml: missing or empty 'allergens' key")
    yaml_keys = set(allergens.keys())
    if yaml_keys != set(SUPPORTED_ALLERGEN_CATEGORIES):
        missing = SUPPORTED_ALLERGEN_CATEGORIES - yaml_keys
        extra = yaml_keys - SUPPORTED_ALLERGEN_CATEGORIES
        raise ValueError(
            f"allergens.yaml ↔ SUPPORTED_ALLERGEN_CATEGORIES drift: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    required_entry_fields = (
        "allergen_code",
        "allergen_display_en",
        "allergen_display_ja",
        "prevalence",
        "criticality",
        "common_reactions",
    )
    for cat, entries in allergens.items():
        if not entries or not isinstance(entries, list):
            raise ValueError(f"allergens.yaml[{cat}]: empty list")
        for i, e in enumerate(entries):
            for f in required_entry_fields:
                if f not in e:
                    raise ValueError(f"allergens.yaml[{cat}][{i}]: missing {f!r}")
            prev = e["prevalence"]
            if not isinstance(prev, dict) or "adult" not in prev:
                raise ValueError(f"allergens.yaml[{cat}][{i}].prevalence: must have 'adult' key")
            adult_val = prev["adult"]
            if not isinstance(adult_val, (int, float)) or not (0 <= adult_val <= 1):
                raise ValueError(f"allergens.yaml[{cat}][{i}].prevalence.adult: 0..1 expected, got {adult_val!r}")
            reactions = e.get("common_reactions", [])
            if not reactions or not isinstance(reactions, list):
                raise ValueError(f"allergens.yaml[{cat}][{i}].common_reactions: must be non-empty list")
            allergen_code = e["allergen_code"]
            if not _code_in_data("snomed-ct", allergen_code):
                raise ValueError(
                    f"allergens.yaml[{cat}][{i}].allergen_code {allergen_code!r} not in codes/data/snomed-ct.yaml"
                )
            for j, rxn in enumerate(reactions):
                manifestation_snomed = rxn.get("manifestation_snomed", "")
                if not manifestation_snomed:
                    raise ValueError(f"allergens.yaml[{cat}][{i}].common_reactions[{j}]: missing manifestation_snomed")
                if not _code_in_data("snomed-ct", manifestation_snomed):
                    raise ValueError(
                        f"allergens.yaml[{cat}][{i}].common_reactions[{j}].manifestation_snomed "
                        f"{manifestation_snomed!r} not in codes/data/snomed-ct.yaml"
                    )


@lru_cache(maxsize=1)
def load_allergens() -> dict[str, Any]:
    """Load allergens.yaml + validate. Cached singleton.

    Returns only the ``allergens:`` bucket for backwards compatibility with
    all pre-#942 call sites. NKA / polyallergy / cross-reactivity blocks
    are read via :func:`load_allergen_config`.
    """
    with (_REF_DIR / "allergens.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_allergens(data)
    _validate_nka_and_polyallergy(data)
    return data["allergens"]


@lru_cache(maxsize=1)
def load_allergen_config() -> dict[str, Any]:
    """Load full allergens.yaml (allergens + nka + polyallergy + cross_reactivity).

    Issue #942: the enricher needs the sibling blocks; kept separate from
    :func:`load_allergens` so legacy callers keep the plain allergen-catalog
    view.
    """
    with (_REF_DIR / "allergens.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_allergens(data)
    _validate_nka_and_polyallergy(data)
    return data


def _validate_nka_and_polyallergy(data: dict[str, Any]) -> None:
    """Fail-loud on missing / malformed Issue #942 config blocks."""
    nka = data.get("nka")
    if not nka or not isinstance(nka, dict):
        raise ValueError("allergens.yaml: missing 'nka' block (Issue #942)")
    for k in ("allergen_code", "code_text_ja", "code_text_en", "clinical_status", "verification_status"):
        if k not in nka:
            raise ValueError(f"allergens.yaml.nka: missing {k!r}")
    if not _code_in_data("snomed-ct", nka["allergen_code"]):
        raise ValueError(f"allergens.yaml.nka.allergen_code {nka['allergen_code']!r} not in codes/data/snomed-ct.yaml")
    poly = data.get("polyallergy")
    if not poly or not isinstance(poly, dict):
        raise ValueError("allergens.yaml: missing 'polyallergy' block (Issue #942)")
    probs = poly.get("probability_given_any_allergy")
    if not isinstance(probs, dict):
        raise ValueError("allergens.yaml.polyallergy.probability_given_any_allergy: must be dict")
    for k in ("child", "adult", "elderly"):
        if k not in probs:
            raise ValueError(f"allergens.yaml.polyallergy.probability_given_any_allergy: missing {k!r}")
        v = probs[k]
        if not isinstance(v, (int, float)) or not (0 <= v <= 1):
            raise ValueError(f"allergens.yaml.polyallergy.probability_given_any_allergy[{k}]: 0..1 expected, got {v!r}")
    weights = poly.get("additional_count_weights")
    if not isinstance(weights, dict) or not weights:
        raise ValueError("allergens.yaml.polyallergy.additional_count_weights: must be non-empty dict")
    for k, v in weights.items():
        if not isinstance(v, (int, float)) or v < 0:
            raise ValueError(f"allergens.yaml.polyallergy.additional_count_weights[{k}]: non-negative expected")
    # cross_reactivity is optional but if present must be well-formed.
    xr = data.get("cross_reactivity")
    if xr is not None:
        if not isinstance(xr, list):
            raise ValueError("allergens.yaml.cross_reactivity: must be a list")
        for i, rule in enumerate(xr):
            if not isinstance(rule, dict):
                raise ValueError(f"allergens.yaml.cross_reactivity[{i}]: must be dict")
            for k in ("trigger_allergen_codes", "boost_category", "boost_weight_bonus"):
                if k not in rule:
                    raise ValueError(f"allergens.yaml.cross_reactivity[{i}]: missing {k!r}")


def _age_bucket(age: int) -> str:
    """Map integer age to polyallergy age bucket key."""
    if age < 18:
        return "child"
    if age < 65:
        return "adult"
    return "elderly"


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
      5. every patient ends with ``allergies`` = list of ≥1 record — the
         empty list is never emitted (`feedback_empty_vs_wrong_assertion`).
    """
    cfg = load_allergen_config()
    allergens = cfg["allergens"]
    nka_cfg = cfg["nka"]
    poly_cfg = cfg["polyallergy"]
    cross_reactivity_rules = cfg.get("cross_reactivity", []) or []

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
        rng = np.random.default_rng(sub_seed)

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
        poly_prob = float(poly_probs[_age_bucket(age)])
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

        patient.allergies = allergies_out
