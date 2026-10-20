"""Glycemic_control retirement sweep.

Phase 1 Task 10. Pin that the retired per-patient fields / helpers
are gone and only the whitelisted protocol-override + helper
survivors remain.

See Phase 1 plan Task 10 brief + spec §7 Migration.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from clinosim.types.patient import ChronicCondition
from clinosim.types.population import PersonRecord


@pytest.mark.unit
def test_person_record_has_no_glycemic_trajectory_attribute() -> None:
    """PersonRecord.glycemic_trajectory is removed as a dataclass field."""
    assert "glycemic_trajectory" not in PersonRecord.__dataclass_fields__


@pytest.mark.unit
def test_person_record_has_longitudinal_history_attribute() -> None:
    """PersonRecord.longitudinal_history is the replacement field."""
    assert "longitudinal_history" in PersonRecord.__dataclass_fields__


@pytest.mark.unit
def test_chronic_condition_glycemic_control_is_unused_dead_field() -> None:
    """ChronicCondition.glycemic_control is NOT removed (safe to keep
    on the dataclass for backward compat with pickled fixtures), but
    the activator must not populate it any more."""
    cc = ChronicCondition(code="E11.9")
    assert cc.glycemic_control is None


@pytest.mark.unit
def test_remaining_glycemic_control_references_are_whitelisted() -> None:
    """Every surviving reference to `glycemic_control` /
    `glycemic_trajectory` under clinosim/ must be in the whitelist of
    legitimate retainers. A new unwhitelisted hit fails this test."""
    repo_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            "grep",
            "-rn",
            "-E",
            "--include=*.py",
            "--include=*.yaml",
            r"\bglycemic_control\b|\bglycemic_trajectory\b",
            str(repo_root / "clinosim"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    allowed_patterns = [
        # PhysiologicalState protocol-override hook — kept.
        r".*clinosim/types/clinical\.py:\d+:.*glycemic_control: float \| None",
        # ChronicCondition kept-for-backward-compat dead field.
        r".*clinosim/types/patient\.py:\d+:.*glycemic_control: float \| None",
        # DiseaseProtocol override hook — kept.
        r".*clinosim/modules/disease/protocol\.py:\d+:.*chronic_glycemic_control",
        # inpatient simulator protocol-override assignment — kept.
        r".*clinosim/simulator/inpatient\.py:\d+:.*"
        r"(?:chronic_glycemic_control|state\.glycemic_control|sampled glycemic_control)",
        # physiology.engine — the helper + fallback paths are kept.
        r".*clinosim/modules/physiology/engine\.py:\d+:.*(?:glycemic_control|_GLYCEMIC_)",
        # Activator local-only use (ChronicCondition.glycemic_control kwarg
        # is always None in the Phase 1 path; the local assignment is
        # kept so the dataclass kwarg stays named).
        r".*clinosim/modules/patient/activator\.py:\d+:.*glycemic_control = None",
        r".*clinosim/modules/patient/activator\.py:\d+:.*glycemic_control=glycemic_control",
        # Health-checkup backward-compat read: ChronicCondition.glycemic_control
        # is now never populated so this falls through to HBA1C_GC_FALLBACK.
        # Dead-code migration to longitudinal_history is a follow-up.
        r".*clinosim/modules/health_checkup/engine\.py:\d+:.*glycemic_control",
        r".*clinosim/modules/health_checkup/_checkup_thresholds\.py:\d+:.*glycemic_control",
        # Monitoring yaml comment — informational, references physiology engine behaviour.
        r".*clinosim/modules/monitoring/reference_data/medication_monitoring\.yaml:\d+:.*glycemic_control",
        # Explanatory comments about the retirement (kept for context) — any file.
        r".*clinosim/.*:\d+:\s*#.*(?:glycemic_control|glycemic_trajectory|_glycemic_|_GLYCEMIC_|_advance_glycemic_)",
        # yaml docstring / tutorial comments.
        r".*clinosim/locale/shared/stage_transition\.yaml:\d+:.*glycemic_trajectory",
        # Binary pyc files — grep sometimes picks them up.
        r"Binary file .*\.pyc matches",
        # Sepsis ICU bundle action name — unrelated to the retired axis.
        r".*clinosim/modules/disease/reference_data/sepsis\.yaml:\d+:.*glycemic_control",
        # Aging docstring explaining the historical pattern (comment).
        r".*clinosim/modules/population/aging\.py:\d+:\s+(?:#|Reads).*glycemic_control",
    ]
    offenders = []
    for line in result.stdout.splitlines():
        if any(re.match(pat, line) for pat in allowed_patterns):
            continue
        offenders.append(line)
    assert not offenders, "unwhitelisted glycemic refs:\n" + "\n".join(offenders)


@pytest.mark.unit
def test_locale_loader_glycemic_trajectory_removed() -> None:
    """load_glycemic_trajectory is retired from the locale loader."""
    from clinosim.locale import loader

    assert not hasattr(loader, "load_glycemic_trajectory")


@pytest.mark.unit
def test_locale_glycemic_trajectory_yaml_removed() -> None:
    """The yaml backing the retired trajectory config is gone."""
    repo_root = Path(__file__).resolve().parents[3]
    assert not (repo_root / "clinosim" / "locale" / "shared" / "glycemic_trajectory.yaml").exists()
