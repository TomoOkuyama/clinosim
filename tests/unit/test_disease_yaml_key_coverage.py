"""FP-YAML-KEY-COVERAGE — Consumer-Site Coverage Test for disease YAML nested keys.

Session 40 pattern (mirrors ``test_diagnosis_code_coverage.py``,
``test_completeness_invariants.py``, and ``test_initial_state_impact_validation.py``):
a lightweight consumer-derived invariant test that catches YAML author typos
(silent-drop C1 class) at nested-container keys — WITHOUT the structural cost
of sub-model definitions.

The Pydantic ``extra="forbid"`` gate on ``DiseaseProtocol`` (FP-YAML-3, session 38)
only protects the top-level key set. Nested containers (`order_protocols`,
`complications[].state_impact`, `diagnostic`, etc.) are typed as
``dict[str, Any]`` so a typo'd key inside them silently drops the author's
intent — the same class of bug as session 40's ``anion_gap_status`` /
``consciousness`` / ``neurological_status`` deltas.

Rather than mass sub-model refactoring (which fights against author velocity
and adds ripple through simulator code), this test defines the *canonical
key allowlist* per nested container and walks every disease YAML. Additions
land in the allowlist first — the diff on the allowlist is intentional and
review-visible, matching the ``test_diagnosis_code_coverage.py`` model.

The initial survey (session 40) discovered **2 real silent-drop offenders in
urinary_tract_infection.yaml**: ``diagnostic.presenting_symptoms`` (8 authored
symptoms, top-level ``presenting_symptoms`` is what the type declares) and
``diagnostic.initial_differentials`` (5 entries, zero-consumer field).
"""

from __future__ import annotations

import glob
import os

import pytest
import yaml

pytestmark = pytest.mark.unit


ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DISEASE_YAMLS = sorted(glob.glob(os.path.join(ROOT, "clinosim/modules/disease/reference_data/*.yaml")))


# --- Canonical nested-key allowlists -----------------------------------------
#
# Add a key here BEFORE (or with) its use in a disease YAML. The allowlist
# diff surfaces the intent in code review just as the codes/data/*.yaml diff
# does for new diagnosis codes. A key present in a YAML but absent here is a
# silent-drop risk — either wire the consumer or delete the authored entry.

ORDER_PROTOCOLS_KEYS = frozenset(
    {
        "admission_orders",
        "daily_monitoring",
        "discharge_criteria",
        "trigger_orders",
    }
)

ORDER_PROTOCOLS_ADMISSION_ORDERS_KEYS = frozenset(
    {
        "labs",
        "imaging",
        "supportive",
        "procedures",
        "consults",
        "pulmonary_function",
    }
)

ORDER_PROTOCOLS_DISCHARGE_CRITERIA_KEYS = frozenset(
    {
        "japan",
        "us",
    }
)

DIAGNOSTIC_KEYS = frozenset(
    {
        "diagnostic_difficulty",
        "differential",
        "confirmation_threshold",
        "diagnosis_progression",
        "likelihood_ratios",
    }
)

COMPLICATION_ENTRY_KEYS = frozenset(
    {
        "name",
        "description",
        "state_impact",
        "actions",
        "probability_per_day",
        "onset_day_range",
        "risk_factors",
        "detection",
        "note",
        # Cascade / parent-triggered complications
        "cascade",
        "parent_complication",
        "probability_given_parent",
        "onset_days_after_parent",
    }
)

OUTCOME_BENCHMARKS_KEYS = frozenset({"japan", "us"})

EXPECTED_LAB_DISTRIBUTIONS_KEYS = frozenset({"admission", "discharge"})
EXPECTED_VITAL_DISTRIBUTIONS_KEYS = frozenset({"admission", "discharge"})


def _yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _report(offenders: list[tuple[str, str, set[str]]]) -> str:
    return "\n".join(f"  {os.path.basename(path)} :: {loc} :: {sorted(keys)}" for path, loc, keys in offenders)


class TestOrderProtocolsKeyCoverage:
    def test_top_level_keys_allowlisted(self) -> None:
        offenders = []
        for path in DISEASE_YAMLS:
            op = _yaml(path).get("order_protocols") or {}
            if not isinstance(op, dict):
                continue
            unknown = set(op.keys()) - ORDER_PROTOCOLS_KEYS
            if unknown:
                offenders.append((path, "order_protocols", unknown))
        assert not offenders, (
            "Unknown keys under order_protocols (author typo silent-drop risk). "
            "Either add the key to ORDER_PROTOCOLS_KEYS or fix the YAML:\n" + _report(offenders)
        )

    def test_admission_orders_keys_allowlisted(self) -> None:
        offenders = []
        for path in DISEASE_YAMLS:
            op = _yaml(path).get("order_protocols") or {}
            ao = op.get("admission_orders") or {}
            if not isinstance(ao, dict):
                continue
            unknown = set(ao.keys()) - ORDER_PROTOCOLS_ADMISSION_ORDERS_KEYS
            if unknown:
                offenders.append((path, "order_protocols.admission_orders", unknown))
        assert not offenders, "Unknown keys under order_protocols.admission_orders:\n" + _report(offenders)

    def test_discharge_criteria_keys_allowlisted(self) -> None:
        offenders = []
        for path in DISEASE_YAMLS:
            op = _yaml(path).get("order_protocols") or {}
            dc = op.get("discharge_criteria") or {}
            if not isinstance(dc, dict):
                continue
            unknown = set(dc.keys()) - ORDER_PROTOCOLS_DISCHARGE_CRITERIA_KEYS
            if unknown:
                offenders.append((path, "order_protocols.discharge_criteria", unknown))
        assert not offenders, _report(offenders)


class TestDiagnosticKeyCoverage:
    def test_diagnostic_keys_allowlisted(self) -> None:
        offenders = []
        for path in DISEASE_YAMLS:
            diag = _yaml(path).get("diagnostic") or {}
            if not isinstance(diag, dict):
                continue
            unknown = set(diag.keys()) - DIAGNOSTIC_KEYS
            if unknown:
                offenders.append((path, "diagnostic", unknown))
        assert not offenders, (
            "Unknown keys under diagnostic (session 40 finding: "
            "urinary_tract_infection had presenting_symptoms + initial_differentials "
            "misplaced here — both are dead / silent-dropped):\n" + _report(offenders)
        )


class TestComplicationEntryKeyCoverage:
    def test_complication_entry_keys_allowlisted(self) -> None:
        offenders = []
        for path in DISEASE_YAMLS:
            for i, c in enumerate(_yaml(path).get("complications") or []):
                if not isinstance(c, dict):
                    continue
                unknown = set(c.keys()) - COMPLICATION_ENTRY_KEYS
                if unknown:
                    name = c.get("name") or f"[{i}]"
                    offenders.append((path, f"complications[{name!r}]", unknown))
        assert not offenders, _report(offenders)


class TestOutcomeBenchmarksKeyCoverage:
    def test_outcome_benchmarks_keys_allowlisted(self) -> None:
        offenders = []
        for path in DISEASE_YAMLS:
            ob = _yaml(path).get("outcome_benchmarks") or {}
            if not isinstance(ob, dict):
                continue
            unknown = set(ob.keys()) - OUTCOME_BENCHMARKS_KEYS
            if unknown:
                offenders.append((path, "outcome_benchmarks", unknown))
        assert not offenders, _report(offenders)


class TestDistributionKeyCoverage:
    def test_expected_lab_distributions_keys_allowlisted(self) -> None:
        offenders = []
        for path in DISEASE_YAMLS:
            eld = _yaml(path).get("expected_lab_distributions") or {}
            if not isinstance(eld, dict):
                continue
            unknown = set(eld.keys()) - EXPECTED_LAB_DISTRIBUTIONS_KEYS
            if unknown:
                offenders.append((path, "expected_lab_distributions", unknown))
        assert not offenders, _report(offenders)

    def test_expected_vital_distributions_keys_allowlisted(self) -> None:
        offenders = []
        for path in DISEASE_YAMLS:
            evd = _yaml(path).get("expected_vital_distributions") or {}
            if not isinstance(evd, dict):
                continue
            unknown = set(evd.keys()) - EXPECTED_VITAL_DISTRIBUTIONS_KEYS
            if unknown:
                offenders.append((path, "expected_vital_distributions", unknown))
        assert not offenders, _report(offenders)


ENCOUNTER_YAMLS = sorted(glob.glob(os.path.join(ROOT, "clinosim/modules/encounter/reference_data/*.yaml")))


ENCOUNTER_TOP_KEYS = frozenset(
    {
        # Core (every encounter YAML)
        "age_distribution",
        "chief_complaint",
        "condition_id",
        "department",
        "disposition",
        "encounter_type",
        "icd10_code",
        "icd10_display",
        "incidence_modifier",
        "narrative",
        "seasonal",
        "sex_ratio_female",
        "treatment",
        "workup",
        # Common but optional
        "discharge_instructions",
        "discharge_prescriptions",
        "ed_stay_hours",
        "severity_distribution",
        "probability",
        "scenarios",
        "initial_state_impact",
        "followup_instructions",
        "prescriptions",
        "visit_duration_minutes",
        "acid_base_type",
        # Consumer-wired special cases
        "prescriptions_renewed",  # consumed by outpatient.py:212
    }
)

ENCOUNTER_WORKUP_KEYS = frozenset({"labs", "vitals", "imaging"})


class TestEncounterYamlKeyCoverage:
    def test_top_level_keys_allowlisted(self) -> None:
        offenders = []
        for path in ENCOUNTER_YAMLS:
            unknown = set(_yaml(path).keys()) - ENCOUNTER_TOP_KEYS
            if unknown:
                offenders.append((path, "encounter-top-level", unknown))
        assert not offenders, (
            "Unknown top-level keys in encounter YAML (session 40 finding: "
            "rib_fracture.admission_criteria + wrist_fracture.surgical_referral "
            "= unwired 'intent' — silent-drop of admission/referral logic):\n" + _report(offenders)
        )

    def test_workup_keys_allowlisted(self) -> None:
        offenders = []
        for path in ENCOUNTER_YAMLS:
            wk = _yaml(path).get("workup") or {}
            if not isinstance(wk, dict):
                continue
            unknown = set(wk.keys()) - ENCOUNTER_WORKUP_KEYS
            if unknown:
                offenders.append((path, "workup", unknown))
        assert not offenders, (
            "Unknown workup keys (session 40: dialysis_session.workup.vitals_pre_and_post "
            "was a nested-structure typo/unwired intent):\n" + _report(offenders)
        )


class TestAllowlistsAreNonEmpty:
    """Guard against a typo in the allowlists themselves accidentally silencing
    every test into a trivial pass (e.g. renaming ORDER_PROTOCOLS_KEYS)."""

    def test_all_allowlists_have_entries(self) -> None:
        assert len(ORDER_PROTOCOLS_KEYS) >= 3
        assert len(ORDER_PROTOCOLS_ADMISSION_ORDERS_KEYS) >= 3
        assert len(ORDER_PROTOCOLS_DISCHARGE_CRITERIA_KEYS) == 2
        assert len(DIAGNOSTIC_KEYS) >= 3
        assert len(COMPLICATION_ENTRY_KEYS) >= 8
        assert len(OUTCOME_BENCHMARKS_KEYS) == 2
        assert len(EXPECTED_LAB_DISTRIBUTIONS_KEYS) == 2
        assert len(EXPECTED_VITAL_DISTRIBUTIONS_KEYS) == 2
        assert len(ENCOUNTER_TOP_KEYS) >= 15
        assert len(ENCOUNTER_WORKUP_KEYS) == 3
