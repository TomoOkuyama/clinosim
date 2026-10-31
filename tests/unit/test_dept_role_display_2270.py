"""Issue #2270: department, specialty, role and practitioner names come from
data tables, with no raw ids or title-cased slugs."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest
import yaml

from clinosim.locale.loader import (
    department_display,
    department_specialty_snomed,
    load_clinician_roles,
    load_department_display,
    role_display,
)
from clinosim.modules._shared import practitioner_name
from clinosim.modules.document.narrative._template_helpers import _resolve_staff_name
from clinosim.modules.output.fhir_r4.demographics.practitioner import _build_practitioner_role
from clinosim.modules.staff.engine import generate_roster

pytestmark = pytest.mark.unit

_CONFIG = Path(__file__).resolve().parents[2] / "clinosim" / "config"


def _roster_map(scale: str, country: str) -> dict[str, dict]:
    cfg = yaml.safe_load((_CONFIG / f"hospital_{scale}.yaml").read_text(encoding="utf-8"))
    roster = generate_roster(scale, country, np.random.default_rng(1), cfg)
    return {m.staff_id: dataclasses.asdict(m) for m in roster.members}


@pytest.mark.parametrize("scale", ["small", "large"])
def test_every_roster_department_and_role_has_en_and_ja(scale: str) -> None:
    staff = _roster_map(scale, "JP").values()
    departments = load_department_display()
    roles = load_clinician_roles()
    for s in staff:
        dept, role = s.get("department", ""), s.get("role", "")
        assert dept in departments and departments[dept].get("ja") and departments[dept].get("en"), dept
        assert role in roles and roles[role].get("title", {}).get("ja"), role


@pytest.mark.parametrize("country", ["US", "JP"])
def test_specialty_follows_the_department_table(country: str) -> None:
    roster_map = _roster_map("large", country)
    for staff_id, s in roster_map.items():
        res = _build_practitioner_role(staff_id, roster_map, country)
        assert res is not None
        code = department_specialty_snomed(s.get("department", ""))
        spec = res["specialty"][0]
        if code:
            assert spec["coding"][0]["code"] == code
        else:
            # No title-cased slug: the role title from the role table.
            lang = "ja" if country == "JP" else "en"
            assert spec["text"] == role_display(s["role"], lang)


def test_department_display_never_title_cases() -> None:
    assert department_display("laboratory", "ja") == "検査科"
    assert department_display("not_a_department", "en") == "not a department"


def test_practitioner_name_has_one_resolver_without_raw_ids() -> None:
    roster = {"DR-IM-001": {"name": "山田 太郎"}}
    assert practitioner_name("DR-IM-001", roster) == "山田 太郎"
    assert practitioner_name("XYZ-999", roster) == ""
    assert _resolve_staff_name("DR-IM-001", roster) == "山田 太郎"
    assert _resolve_staff_name("XYZ-999", roster) == ""
