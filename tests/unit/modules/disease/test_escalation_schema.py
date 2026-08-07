"""Import-time validation tests for drugs.escalation entry schema (Issue #460).

Layer 1 (Task 3): `type` field must be Literal["procedure","medication"] or absent
Layer 2 (Task 5): legacy marker `code_*: "procedure"|"N/A"` must be raised
Layer 3 (Task 5): `type: "procedure"` + `route:` co-occurrence must be raised
All shipped YAMLs must load PASS after Task 4 migration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.modules.disease.protocol import _REF_DIR, load_disease_protocol

_YAML_STUB = """
disease_id: test_disease
chief_complaint: {en: test, ja: test}
department: internal_medicine
icd_codes: {primary: "Z00.0"}
target_los: {mean: 5, sd: 1, min: 1, max: 30}
course_archetypes:
  typical: {trajectory: {}, probability: 1.0}
outcome_benchmarks: {}
incidence:
  japan:
    "25-34": {M: 50, F: 40}
  us:
    "25-34": {M: 50, F: 40}
severity:
  distribution: {mild: 0.5, moderate: 0.3, severe: 0.2}
"""


def _write_disease_yaml(tmp_path: Path, escalation_yaml: str) -> None:
    (tmp_path / "test_disease.yaml").write_text(_YAML_STUB + escalation_yaml)


# ---------------------------------------------------------------------------
# Layer 1: type must be Literal["procedure","medication"] or absent
# ---------------------------------------------------------------------------


def test_unknown_type_value_rejected(tmp_path, monkeypatch):
    """`type: "proc"` (misspelling) must raise at import."""
    monkeypatch.setattr("clinosim.modules.disease.protocol._REF_DIR", tmp_path)
    load_disease_protocol.cache_clear()
    _write_disease_yaml(
        tmp_path,
        """
drugs:
  escalation:
    japan:
      - {drug: Anything, type: proc, dose: 1x/day}
""",
    )
    with pytest.raises(ValueError, match="type"):
        load_disease_protocol("test_disease")


def test_valid_type_procedure_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr("clinosim.modules.disease.protocol._REF_DIR", tmp_path)
    load_disease_protocol.cache_clear()
    _write_disease_yaml(
        tmp_path,
        """
drugs:
  escalation:
    japan:
      - {drug: Hemodialysis, type: procedure, dose: 3-4h session}
""",
    )
    protocol = load_disease_protocol("test_disease")
    assert protocol.disease_id == "test_disease"


def test_valid_type_medication_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr("clinosim.modules.disease.protocol._REF_DIR", tmp_path)
    load_disease_protocol.cache_clear()
    _write_disease_yaml(
        tmp_path,
        """
drugs:
  escalation:
    japan:
      - {drug: Vasopressin, type: medication, dose: 0.03u/min IV, route: IV}
""",
    )
    protocol = load_disease_protocol("test_disease")
    assert protocol.disease_id == "test_disease"


def test_type_absent_accepted_backcompat(tmp_path, monkeypatch):
    """Absent type = keyword fallback path (backcompat for un-migrated YAMLs)."""
    monkeypatch.setattr("clinosim.modules.disease.protocol._REF_DIR", tmp_path)
    load_disease_protocol.cache_clear()
    _write_disease_yaml(
        tmp_path,
        """
drugs:
  escalation:
    japan:
      - {drug: Some drug, dose: q12h IV, route: IV}
""",
    )
    protocol = load_disease_protocol("test_disease")
    assert protocol.disease_id == "test_disease"


def test_all_shipped_disease_yamls_still_load():
    """All shipped YAMLs must still import PASS after Task 3.

    Task 4 will migrate 6 entries to type=procedure; Task 3 must not reject them.
    Pre-migration YAMLs (with legacy marker) also pass because Layer 2/3 raises
    are deferred to Task 5.
    """
    load_disease_protocol.cache_clear()
    for p in _REF_DIR.glob("*.yaml"):
        disease_id = p.stem
        try:
            load_disease_protocol(disease_id)
        except Exception as e:
            pytest.fail(f"{disease_id} failed to load: {e}")
