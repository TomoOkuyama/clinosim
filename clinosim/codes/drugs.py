"""Drug identity catalog loader — META #1792 Phase 1a.

Resolves an internal, authority-neutral ``drug_id`` (snake_case key)
to the display SoT and the pointers into the authority code-system
tables (RxNorm / YJ / HOT7).

Design: this module is the drug-identity Single Source of Truth. The
authority code tables themselves (``rxnorm.yaml``, ``yj.yaml``,
``hot7.yaml``) remain the canonical home of their respective codes with
their own ``metadata.source`` provenance — this module only names which
codes identify a given drug and what to display.

Downstream yamls migrate to ``drug_id`` references in Phase 2+ of
META #1792. Until then this catalog runs in parallel with the existing
``chronic_medications.yaml::drug_ja`` / ``drug_names_ja.yaml`` display
sources; the display-SoT invariant is enforced after the Phase 2
migration lands.

Usage::

    from clinosim.codes.drugs import resolve_drug

    rec = resolve_drug("atorvastatin")
    rec.names["en"]        # "Atorvastatin"
    rec.names["ja"]        # "アトルバスタチン"
    rec.codes.get("rxnorm")  # "83367"
    rec.display_for("US")  # "Atorvastatin"
    rec.display_for("JP")  # "アトルバスタチン"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

_DATA_FILE = Path(__file__).parent / "data" / "drugs.yaml"


@dataclass(frozen=True)
class DrugIdentity:
    """One drug's identity record.

    ``names`` carries the display SoT (``en`` + ``ja`` required). ``codes``
    maps authority keys (``rxnorm`` / ``yj`` / ``hot7``) to the code
    strings that identify this drug in each registry; omitted when the
    drug has no code in that registry. ``classes`` carries drug-class
    tags (optional, free-form).
    """

    drug_id: str
    names: dict[str, str]
    codes: dict[str, str] = field(default_factory=dict)
    classes: tuple[str, ...] = ()

    def display_for(self, country: str) -> str:
        """Return the locale-appropriate bare generic name.

        ``country`` is matched case-insensitively. ``"JP"`` returns the
        Japanese display; everything else returns English (US is the
        default). Unknown country never raises — EN is the fallback.
        """
        if (country or "").strip().upper() == "JP":
            return self.names.get("ja") or self.names.get("en", "")
        return self.names.get("en", "")


def _parse_catalog(raw: dict[str, Any]) -> dict[str, DrugIdentity]:
    """Build the ``drug_id -> DrugIdentity`` map from the parsed yaml.

    Validates that each entry has at least ``names.en`` and ``names.ja``
    (the display SoT invariant). Missing fields raise ``ValueError``
    with the drug_id so the yaml author sees exactly which row is bad.
    """
    out: dict[str, DrugIdentity] = {}
    for drug_id, body in (raw.get("drugs") or {}).items():
        if not isinstance(body, dict):
            raise ValueError(f"drugs.yaml: {drug_id!r} body must be a mapping, got {type(body).__name__}")
        names = body.get("names") or {}
        if not isinstance(names, dict):
            raise ValueError(f"drugs.yaml: {drug_id!r} names must be a mapping")
        if not names.get("en"):
            raise ValueError(f"drugs.yaml: {drug_id!r} missing required names.en")
        if not names.get("ja"):
            raise ValueError(f"drugs.yaml: {drug_id!r} missing required names.ja")
        codes = body.get("codes") or {}
        if not isinstance(codes, dict):
            raise ValueError(f"drugs.yaml: {drug_id!r} codes must be a mapping")
        classes = body.get("classes") or []
        if not isinstance(classes, list):
            raise ValueError(f"drugs.yaml: {drug_id!r} classes must be a list")
        out[str(drug_id)] = DrugIdentity(
            drug_id=str(drug_id),
            names={str(k): str(v) for k, v in names.items()},
            codes={str(k): str(v) for k, v in codes.items() if v},
            classes=tuple(str(c) for c in classes),
        )
    return out


@cache
def _load_catalog() -> dict[str, DrugIdentity]:
    """Load and cache the drug catalog. Fail-loud on missing file: the
    catalog is a required dependency of the loader, not optional."""
    if not _DATA_FILE.exists():
        raise FileNotFoundError(f"drugs.yaml not found at {_DATA_FILE}")
    with _DATA_FILE.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return _parse_catalog(raw)


def resolve_drug(drug_id: str) -> DrugIdentity:
    """Return the ``DrugIdentity`` for ``drug_id``.

    Raises ``KeyError`` with the drug_id when not catalogued. Callers
    that need to probe without raising should use :func:`get_drug`.
    """
    catalog = _load_catalog()
    rec = catalog.get(drug_id)
    if rec is None:
        raise KeyError(f"resolve_drug: {drug_id!r} not in drugs.yaml catalog")
    return rec


def get_drug(drug_id: str) -> DrugIdentity | None:
    """Return the ``DrugIdentity`` for ``drug_id``, or None when not catalogued."""
    return _load_catalog().get(drug_id)


def all_drug_ids() -> tuple[str, ...]:
    """Return every drug_id in the catalog (sorted). Used by integrity tests
    and by audit scripts that cross-reference drug_id usage in downstream yamls."""
    return tuple(sorted(_load_catalog().keys()))
