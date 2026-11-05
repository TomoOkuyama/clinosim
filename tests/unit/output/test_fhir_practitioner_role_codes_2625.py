"""Issue #2625: a PractitionerRole names the occupation and the department's specialty."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest
import yaml

from clinosim.locale.loader import department_display, load_clinician_roles, role_display
from clinosim.modules.output.fhir_r4.demographics.practitioner import _build_practitioner_role
from clinosim.modules.staff.engine import generate_roster

pytestmark = pytest.mark.unit

_CONFIG = Path(__file__).resolve().parents[3] / "clinosim" / "config"


def _roster_map(scale: str, country: str) -> dict[str, dict]:
    cfg = yaml.safe_load((_CONFIG / f"hospital_{scale}.yaml").read_text(encoding="utf-8"))
    roster = generate_roster(scale, country, np.random.default_rng(1), cfg)
    return {m.staff_id: dataclasses.asdict(m) for m in roster.members}


def _roles(scale: str, country: str) -> list[tuple[dict, dict]]:
    roster = _roster_map(scale, country)
    out = []
    for staff_id, staff in roster.items():
        res = _build_practitioner_role(staff_id, roster, country)
        assert res is not None
        out.append((staff, res))
    return out


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("scale", ["small", "large"])
def test_every_practitioner_role_has_a_coded_occupation(scale: str, country: str) -> None:
    for staff, res in _roles(scale, country):
        codings = [c for cc in res.get("code", []) for c in cc.get("coding", [])]
        assert codings, (staff["role"], staff["staff_id"])
        assert all(c.get("code") and c.get("system") for c in codings)


def test_a_laboratory_technician_is_not_an_ict_professional() -> None:
    for staff, res in _roles("large", "US"):
        if staff["role"] == "lab_technician":
            [coding] = res["code"][0]["coding"]
            assert (coding["system"], coding["code"]) == ("http://snomed.info/sct", "159282002")


@pytest.mark.parametrize("country", ["US", "JP"])
def test_a_specialty_names_the_department_not_the_profession(country: str) -> None:
    lang = "ja" if country == "JP" else "en"
    titles = {role_display(r, lang) for r in load_clinician_roles()}
    for staff, res in _roles("large", country):
        spec = res["specialty"][0]
        assert spec["text"] not in titles or spec["text"] == department_display(staff["department"], lang), (
            staff["role"],
            staff["department"],
            spec,
        )


def test_clinical_departments_carry_a_snomed_specialty() -> None:
    coded = {staff["department"] for staff, res in _roles("large", "US") if res["specialty"][0].get("coding")}
    for dept in ("emergency_medicine", "general_surgery", "orthopedics", "oncology", "primary_care"):
        if any(s["department"] == dept for s, _ in _roles("large", "US")):
            assert dept in coded, dept
