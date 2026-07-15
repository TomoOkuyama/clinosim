"""AD-55 Module: hai — HAI onset sampling (CLABSI / CAUTI / VAP)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

# Canonical lowercase hai_type strings. MUST be defined BEFORE enricher
# import to avoid circular import (enricher imports HAI_TYPES for validation).
# These MUST be used everywhere a hai_type appears (HAIEvent construction,
# YAML key, lift table lookup, tests). The earlier mismatch (UPPERCASE YAML
# keys + lowercase enricher writes) silently no-op'd the entire Phase 3a
# lift in production; a YAML integrity test plus this single source of truth
# prevents that class of regression.
# Defined BEFORE submodule imports so enricher can import it without circular
# dependency (PR-93 adversarial review fix).
HAI_TYPES: tuple[str, ...] = ("clabsi", "cauti", "vap")

from clinosim.modules.hai.engine import (  # noqa: E402
    load_hai_codes,
    load_hai_organisms,
    load_hai_rates,
    load_hai_specimens,
    sample_hai_onset,
)
from clinosim.modules.hai.enricher import enrich_hai  # noqa: E402

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_HAI_ANTIBIOGRAM_PATH = _REF_DIR / "hai_antibiogram.yaml"


def _organisms_by_hai_type() -> dict[str, set[str]]:
    # Reuse the cached + validated canonical loader (engine.load_hai_organisms,
    # imported above) instead of re-reading hai_organisms.yaml raw. Returns a
    # fresh dict each call; the cached YAML is only read.
    table = load_hai_organisms().get("hai_organisms") or {}
    return {hai_type: {str(entry["snomed"]) for entry in entries} for hai_type, entries in table.items()}


@lru_cache(maxsize=1)
def load_hai_antibiogram() -> dict:  # type: ignore[type-arg]
    """Load and validate hai_antibiogram.yaml.

    Validates at import time so a typo (uppercase hai_type, unknown organism,
    unknown antibiotic, malformed probability triple) raises ValueError loudly
    instead of silently producing a no-op antibiogram lookup at runtime.
    Lesson from PR-90 silent no-op (xhigh review).
    """
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    with open(_HAI_ANTIBIOGRAM_PATH) as f:
        raw = yaml.safe_load(f) or {}
    abg = raw.get("hai_antibiogram") or {}
    # PR3b-3 stage-1 adversarial finding I2: empty top-level antibiogram would
    # silently disable downstream consumers (PR3b-3 D2 panel-eligible
    # filter — _panel_eligible_organisms returns {} → D2 skips all
    # encounters). Fail loud at load time (silent-no-op defense layer 2).
    if not abg:
        raise ValueError(
            "hai_antibiogram.yaml top-level is empty — would silently disable "
            "PR3b-3 D2 panel-eligible filter (PR-90 class silent no-op)"
        )
    valid_hai_types = set(HAI_TYPES)
    valid_organisms = _organisms_by_hai_type()
    valid_antibiotics = set(ANTIBIOTIC_LOINC_LOOKUP.keys())

    for hai_type, organisms in abg.items():
        # pr112-adv-3 Agent 1 cosmetic fix: check hai_type validity FIRST so
        # `{INVALID_TYPE: {}}` reports the more-actionable "unknown hai_type"
        # error before falling through to "bucket empty".
        if hai_type not in valid_hai_types:
            raise ValueError(
                f"hai_antibiogram.yaml: unknown hai_type {hai_type!r}, expected one of {sorted(valid_hai_types)}"
            )
        # PR3b-3 stage-2 adversarial finding (Agent 2 HIGH): per-hai_type
        # bucket empty is same silent-no-op class as I2 top-level empty —
        # `{hai_antibiogram: {clabsi: {}}}` would silently disable
        # _panel_eligible_organisms for clabsi → D2 skips every CLABSI
        # encounter. Fail loud per-bucket too.
        if not organisms:
            raise ValueError(
                f"hai_antibiogram.yaml: {hai_type!r} bucket empty — would "
                f"silently disable PR3b-3 D2 panel-eligible filter for "
                f"that hai_type (PR-90 class silent no-op)"
            )
        for snomed, abx_table in organisms.items():
            allowed_snomeds = valid_organisms.get(hai_type, set())
            if snomed not in allowed_snomeds:
                raise ValueError(
                    f"hai_antibiogram.yaml: organism {snomed!r} not in hai_organisms.yaml for hai_type {hai_type!r}"
                )
            for abx_key, triple in abx_table.items():
                if abx_key not in valid_antibiotics:
                    raise ValueError(
                        f"hai_antibiogram.yaml: unknown antibiotic key "
                        f"{abx_key!r} (must be one of ANTIBIOTIC_LOINC_LOOKUP)"
                    )
                if not isinstance(triple, list) or len(triple) != 3:
                    raise ValueError(
                        f"hai_antibiogram.yaml: triple for {hai_type}/{snomed}/"
                        f"{abx_key} must be length 3, got {triple!r}"
                    )
                if abs(sum(triple) - 1.0) > 0.01:
                    raise ValueError(
                        f"hai_antibiogram.yaml: triple for {hai_type}/{snomed}/"
                        f"{abx_key} must sum to ~1.0, got {sum(triple):.3f}"
                    )
    return abg


__all__ = [
    "HAI_TYPES",
    "load_hai_antibiogram",
    "load_hai_rates",
    "load_hai_codes",
    "load_hai_organisms",
    "load_hai_specimens",
    "sample_hai_onset",
    "enrich_hai",
]
