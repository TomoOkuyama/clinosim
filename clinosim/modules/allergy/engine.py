"""Allergy module engine (Tier 1 #3 α-min-1 PR1).

Loader + validator (silent-no-op defense) + POST_POPULATION enricher。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.allergy import Allergy, AllergyReaction

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

SUPPORTED_ALLERGEN_CATEGORIES: frozenset[str] = frozenset(
    {"medication", "food", "environment"}
)

OVERALL_ALLERGY_PREVALENCE = 0.15   # baseline calibrated (see brief Step 4)
CATEGORY_WEIGHTS = {"medication": 0.50, "food": 0.25, "environment": 0.25}


def _validate_allergens(data: dict[str, Any]) -> None:
    """Fail-loud validation of allergens.yaml (silent-no-op defense Layer 3-6).

    Layer 3: empty top + per-bucket guards
    Layer 4: forward + reverse coverage vs SUPPORTED_ALLERGEN_CATEGORIES
    Layer 5: validator runs BEFORE data is returned (pre-register ordering)
    Layer 6: required-field check per entry + prevalence range 0..1
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
            f"allergens.yaml ↔ SUPPORTED_ALLERGEN_CATEGORIES drift: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
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
                raise ValueError(
                    f"allergens.yaml[{cat}][{i}].prevalence: must have 'adult' key"
                )
            adult_val = prev["adult"]
            if not isinstance(adult_val, (int, float)) or not (0 <= adult_val <= 1):
                raise ValueError(
                    f"allergens.yaml[{cat}][{i}].prevalence.adult: 0..1 expected, got {adult_val!r}"
                )
            reactions = e.get("common_reactions", [])
            if not reactions or not isinstance(reactions, list):
                raise ValueError(
                    f"allergens.yaml[{cat}][{i}].common_reactions: must be non-empty list"
                )


@lru_cache(maxsize=1)
def load_allergens() -> dict[str, Any]:
    """Load allergens.yaml + validate. Cached singleton."""
    with (_REF_DIR / "allergens.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_allergens(data)
    return data["allergens"]


def allergy_enricher(ctx: Any) -> None:
    """POST_POPULATION enricher: sample allergies per patient.

    Determinism via derive_sub_seed(master, ENRICHER_SEED_OFFSETS["allergy"],
    patient_id)。Master stream 不変。

    Sampling rule (α-min-1 baseline-calibrated):
      1. patient-level overall prob gate (15%、activator baseline 一致)
      2. gate 成立 patient のみ category-weighted single allergy (後続 phase で
         multi-allergy に拡張可)
    """
    allergens = load_allergens()
    categories = list(CATEGORY_WEIGHTS.keys())
    weights = [CATEGORY_WEIGHTS[c] for c in categories]

    for patient in ctx.population.persons.values():
        # PersonRecord uses person_id (Layer 1 naming); PatientProfile maps this to patient_id.
        pid = getattr(patient, "person_id", getattr(patient, "patient_id", ""))
        sub_seed = derive_sub_seed(
            ctx.master_seed, ENRICHER_SEED_OFFSETS["allergy"], pid
        )
        rng = np.random.default_rng(sub_seed)

        if rng.random() >= OVERALL_ALLERGY_PREVALENCE:
            patient.allergies = []  # 85% は no allergy
            continue

        # category-weighted single-allergy (future: extend to multi-allergy)
        category = str(rng.choice(categories, p=weights))
        entries = allergens[category]
        entry = entries[int(rng.integers(0, len(entries)))]
        reaction_entry = entry["common_reactions"][0]

        patient.allergies = [
            Allergy(
                allergy_id=f"al-{pid}-1",
                allergen_code=entry["allergen_code"],
                allergen_display=entry["allergen_display_en"],
                category=category,
                criticality=entry["criticality"],
                verification_status="confirmed",
                onset_date=None,
                reactions=[
                    AllergyReaction(
                        manifestation_snomed=reaction_entry["manifestation_snomed"],
                        manifestation_display=reaction_entry["manifestation_display_en"],
                        severity=reaction_entry["severity"],
                    )
                ],
            )
        ]
