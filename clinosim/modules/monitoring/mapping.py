"""YAML loader for the chronic-medication → monitoring-lab mapping (Issue #757).

Loads `reference_data/medication_monitoring.yaml` into a lookup structure
consumed by `enrich_medication_monitoring`. The loader is intentionally
minimal:

- No caching decorator — the enricher is called once per POST_RECORDS pass
  per run, and the file is small (<10 KB expected for the full pair set).
- Returns plain dicts, validated at load against the ``extra="forbid"``
  Pydantic model ``_MonitoringFile`` (configuration spec), so a typo in the
  YAML fails loud instead of surfacing as a silent "drug never matched"
  downstream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

from clinosim.codes.drugs import drug_display, medication_matches
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.loaders.demographics import load_code_mapping

_YAML_PATH = Path(__file__).parent / "reference_data" / "medication_monitoring.yaml"


class _Rationale(BaseModel):
    model_config = ConfigDict(extra="forbid")
    en: str = Field(min_length=1)
    ja: str = Field(min_length=1)


class _MonitoringLab(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lab: str = Field(min_length=1)
    interval_months: StrictInt = Field(ge=1)  # Issue #2143
    rationale: _Rationale

    @model_validator(mode="after")
    def _lab_has_a_code(self) -> _MonitoringLab:
        # The order and its result carry the same code (Issue #2301).
        if not monitoring_lab_code(self.lab):
            raise ValueError(f"lab {self.lab!r} has no code in locale/us/code_mapping_lab.yaml")
        return self


class _MonitoringRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The chronic follow-up gate (Issue #2786).
    per_visit_probability: StrictFloat | StrictInt = Field(ge=0, le=1)
    drugs: list[str] = []
    classes: list[str] = []
    monitoring: list[_MonitoringLab] = Field(min_length=1)

    @model_validator(mode="after")
    def _selects_catalog_drugs(self) -> _MonitoringRule:
        _validate_drug_selector("monitoring rule", {"drugs": self.drugs, "classes": self.classes})
        return self


class _MonitoringFile(BaseModel):
    """Shape of ``medication_monitoring.yaml``, the one drug → monitoring-lab
    table of both monitoring paths (Issue #2786)."""

    model_config = ConfigDict(extra="forbid")
    mappings: dict[str, _MonitoringRule] = Field(min_length=1)


def load_medication_monitoring(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the drug → monitoring-labs mapping.

    Returns a dict keyed by rule name (as declared in YAML) whose value is
    ``{"per_visit_probability", "drugs", "classes", "monitoring": [{lab,
    interval_months, rationale}, ...]}``. Tests can override the file path
    via the optional ``path`` argument.

    Raises ``ValueError`` (``pydantic.ValidationError``) on any shape
    violation, an unknown key, a drug or class not in the drug catalog, or a
    lab with no code in the lab code mapping.
    """
    return load_validated_yaml(path or _YAML_PATH, _MonitoringFile)["mappings"]


def monitoring_lab_code(lab: str) -> str:
    """Return the order code for a monitoring lab: its LOINC from the shared lab
    code mapping, the same code its results carry (Issue #2301). Empty when the
    lab is not mapped."""
    return load_code_mapping("lab", "US").get(lab, "")


def matched_medication_names(current_medications: list, mapping: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Map each matched monitoring rule to the (English, Japanese) name of the
    drug the patient actually takes (Issue #2294).

    A rule's class covers other drugs of the class (the Atorvastatin rule
    matches every statin), so order text must name the patient's
    drug, not the rule key. A medication without a Japanese name takes the
    drug catalog's (Issue #2271).
    """
    out: dict[str, tuple[str, str]] = {}
    for drug, entry in mapping.items():
        for med in current_medications or []:
            name = str(getattr(med, "drug_name", None) or (med if isinstance(med, str) else ""))
            if medication_matches(med, entry.get("drugs") or (), entry.get("classes") or ()):
                name_ja = str(getattr(med, "drug_name_ja", "") or "")
                if not name_ja:
                    name_ja = drug_display(name, "ja") or ""
                out[drug] = (name or drug, name_ja or name or drug)
                break
    return out


def match_drugs(current_medications: list, mapping: dict[str, Any]) -> list[str]:
    """Return the list of canonical drug names the patient is on.

    A medication matches a rule by catalog identity: its ``drug_id`` is in
    the rule's ``drugs`` or belongs to one of its ``classes`` (Issue #2371),
    so "Warfarin 3mg PO", "ワルファリン" and "Coumadin" all match the
    Warfarin rule.

    `current_medications` accepts either `HomeMedication` dataclass entries
    (with `.drug_name` attribute) or plain strings (defensive fallback for
    tests / legacy call sites); other shapes are silently skipped.
    """
    matched: list[str] = []
    for drug, entry in mapping.items():
        for med in current_medications or []:
            if medication_matches(med, entry.get("drugs") or (), entry.get("classes") or ()):
                matched.append(drug)
                break
    return matched


def _validate_drug_selector(where: str, entry: dict[str, Any]) -> None:
    """A monitoring rule selects drugs by catalog ``drugs`` ids and / or
    catalog ``classes``; both must exist in the drug catalog (Issue #2371)."""
    from clinosim.codes.drugs import all_drug_ids, drug_classes, get_drug

    drugs, classes = entry.get("drugs") or [], entry.get("classes") or []
    if not isinstance(drugs, list) or not isinstance(classes, list) or not (drugs or classes):
        raise ValueError(f"{where}: needs a non-empty 'drugs' and / or 'classes' list")
    unknown = [d for d in drugs if get_drug(str(d)) is None]
    if unknown:
        raise ValueError(f"{where}: drugs not in the drug catalog: {unknown}")
    known_classes = {c for d in all_drug_ids() for c in drug_classes(d)}
    bad = [c for c in classes if c not in known_classes]
    if bad:
        raise ValueError(f"{where}: classes no catalog drug has: {bad}")
