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
    """All shipped YAMLs must still import PASS after Layer 2 + Layer 3 raises.

    Task 4 migrated the 6 legacy-marker entries; no shipped YAML now trips any
    of the 3 layers.
    """
    load_disease_protocol.cache_clear()
    for p in _REF_DIR.glob("*.yaml"):
        disease_id = p.stem
        try:
            load_disease_protocol(disease_id)
        except Exception as e:
            pytest.fail(f"{disease_id} failed to load: {e}")


# ---------------------------------------------------------------------------
# Layer 2: legacy marker `code_*: "procedure"|"N/A"` must raise
# ---------------------------------------------------------------------------


def test_legacy_procedure_marker_code_yj_rejected(tmp_path, monkeypatch):
    """`code_yj: "procedure"` is a pre-Issue-460 marker; must migrate to type=procedure."""
    monkeypatch.setattr("clinosim.modules.disease.protocol._REF_DIR", tmp_path)
    load_disease_protocol.cache_clear()
    _write_disease_yaml(
        tmp_path,
        """
drugs:
  escalation:
    japan:
      - {drug: Hemodialysis, code_yj: procedure, dose: 3-4h}
""",
    )
    with pytest.raises(ValueError, match="legacy non-code marker"):
        load_disease_protocol("test_disease")


def test_legacy_na_marker_code_rxnorm_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("clinosim.modules.disease.protocol._REF_DIR", tmp_path)
    load_disease_protocol.cache_clear()
    _write_disease_yaml(
        tmp_path,
        """
drugs:
  escalation:
    us:
      - {drug: Kyphoplasty, code_rxnorm: N/A, dose: under fluoroscopy}
""",
    )
    with pytest.raises(ValueError, match="legacy non-code marker"):
        load_disease_protocol("test_disease")


def test_real_code_value_not_rejected(tmp_path, monkeypatch):
    """Layer 2 only rejects the 2 sentinel values; real codes pass."""
    monkeypatch.setattr("clinosim.modules.disease.protocol._REF_DIR", tmp_path)
    load_disease_protocol.cache_clear()
    _write_disease_yaml(
        tmp_path,
        """
drugs:
  escalation:
    japan:
      - {drug: Real drug, code_yj: "1234567890", dose: 1g IV daily, route: IV}
""",
    )
    protocol = load_disease_protocol("test_disease")
    assert protocol.disease_id == "test_disease"


# ---------------------------------------------------------------------------
# Layer 3: type=procedure + route co-occurrence must raise
# ---------------------------------------------------------------------------


def test_type_procedure_with_route_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("clinosim.modules.disease.protocol._REF_DIR", tmp_path)
    load_disease_protocol.cache_clear()
    _write_disease_yaml(
        tmp_path,
        """
drugs:
  escalation:
    japan:
      - {drug: Hemodialysis, type: procedure, dose: 3-4h, route: EXTRACORPOREAL}
""",
    )
    with pytest.raises(ValueError, match="must not carry a `route` field"):
        load_disease_protocol("test_disease")


def test_type_medication_with_route_still_accepted(tmp_path, monkeypatch):
    """Layer 3 only rejects type=procedure + route. type=medication + route is legit."""
    monkeypatch.setattr("clinosim.modules.disease.protocol._REF_DIR", tmp_path)
    load_disease_protocol.cache_clear()
    _write_disease_yaml(
        tmp_path,
        """
drugs:
  escalation:
    japan:
      - {drug: Vasopressin, type: medication, dose: 0.03u/min, route: IV}
""",
    )
    protocol = load_disease_protocol("test_disease")
    assert protocol.disease_id == "test_disease"
