"""Issue #854 Bucket A: Procedure opaque id + identifier round-trip (all 3 emit paths).

Extends PR #863's opaque-id pattern (Issue #853 non-HAI MR + MA) to
`Procedure`. Three distinct emit sites all resolve through the same shared
`_resolve_procedure_id` helper so `.id` shape is consistent regardless of
the source path:

- `procedures.py::_build_procedure` — CIF-driven procedures (surgery / bedside
  / rehab), sample pre-#854 id: `ENC-POP-000003-635459597438-PROC-POP-000003-002`
- `inline_bb.py::_bb_procedures` — order-derived Procedures, sample pre-#854
  id: `proc-order-ORD-ENC-POP-000004-346099516150-ED-T0`
- `oxygen_therapy.py` — O2-therapy Procedures, sample pre-#854 id:
  `proc-o2-ENC-POP-000170-152552432067`

Post-#854 all three emit `proc-<12hex>` (17 chars, fixed). The compound
structural_key is preserved on `identifier[]` under `PROCEDURE_KEY_SYSTEM`
so consumers can recover the source-path-specific compound verbatim.

`Procedure.reasonReference[]` still points at `Condition/*` (Bucket B —
those ids stay compound until a future PR).
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.procedures.procedures import (
    PROCEDURE_KEY_SYSTEM,
    _build_procedure,
    _resolve_procedure_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_PROC_PATTERN = re.compile(r"^proc-[0-9a-f]{12}$")


# === _resolve_procedure_id (unit — direct helper) ===


def test_resolve_procedure_id_opaque_shape() -> None:
    """Fixed 17 chars: `proc-` (5) + 12 hex."""
    result = _resolve_procedure_id("proc-order-ORD-ENC-POP-000004-346099516150-ED-T0")
    assert _OPAQUE_PROC_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 17


def test_resolve_procedure_id_is_deterministic() -> None:
    key = "proc-order-ORD-ENC-POP-000012-abc-DEV-D2-NIV-BiPA"
    assert _resolve_procedure_id(key) == _resolve_procedure_id(key)


def test_resolve_procedure_id_distinguishes_different_structural_keys() -> None:
    """Distinct source-path structural keys yield distinct opaque ids."""
    order_key = "proc-order-ORD-ENC-POP-000004-346099516150-ED-T0"
    o2_key = "proc-o2-ENC-POP-000170-152552432067"
    cif_key = "ENC-POP-000003-635459597438-PROC-POP-000003-002"
    a = _resolve_procedure_id(order_key)
    b = _resolve_procedure_id(o2_key)
    c = _resolve_procedure_id(cif_key)
    assert len({a, b, c}) == 3


def test_procedure_key_system_uri() -> None:
    assert PROCEDURE_KEY_SYSTEM == "urn:clinosim:identifier:procedure-key"


# === _build_procedure (CIF-driven emit path) ===


def _cif_proc(*, encounter_id: str = "ENC-POP-000003-635459597438", procedure_id: str = "") -> dict:
    """Minimal CIF procedure fixture — matches what procedures.py accepts."""
    return {
        "procedure_id": procedure_id or "PROC-POP-000003-002",
        "encounter_id": encounter_id,
        "procedure_type": "cholecystectomy",
        "start_datetime": "2026-06-15T09:00:00",
        "end_datetime": "2026-06-15T11:00:00",
        "procedure_code": "",
        "procedure_code_jp": "",
        "procedure_code_us": "",
    }


def test_build_procedure_id_is_opaque_us() -> None:
    resource = _build_procedure(_cif_proc(), patient_id="POP-000003", index=0, country="US")
    assert _OPAQUE_PROC_PATTERN.match(resource["id"]), f"got {resource['id']!r}"


def test_build_procedure_id_is_opaque_jp() -> None:
    resource = _build_procedure(_cif_proc(), patient_id="POP-000003", index=0, country="JP")
    assert _OPAQUE_PROC_PATTERN.match(resource["id"]), f"got {resource['id']!r}"


def test_build_procedure_carries_structural_key_identifier() -> None:
    """The compound `{encounter_id}-{procedure_id}` is preserved verbatim on identifier[]."""
    resource = _build_procedure(_cif_proc(), patient_id="POP-000003", index=0, country="JP")
    idents = resource.get("identifier") or []
    structural = [i for i in idents if i.get("system") == PROCEDURE_KEY_SYSTEM]
    assert len(structural) == 1
    assert structural[0]["value"] == "ENC-POP-000003-635459597438-PROC-POP-000003-002"


def test_build_procedure_structural_key_without_encounter_id_falls_back_to_base_pid() -> None:
    """When encounter_id is missing, the structural key is just base_pid — matches
    the pre-#854 fallback shape."""
    resource = _build_procedure(_cif_proc(encounter_id=""), patient_id="POP-000003", index=0, country="US")
    idents = resource["identifier"]
    structural = [i for i in idents if i.get("system") == PROCEDURE_KEY_SYSTEM]
    assert structural[0]["value"] == "PROC-POP-000003-002"


def test_build_procedure_structural_key_uses_index_when_procedure_id_missing() -> None:
    """When procedure_id is empty, base_pid defaults to `proc-{patient_id}-{index:03d}`."""
    resource = _build_procedure(_cif_proc(procedure_id="__empty__"), patient_id="POP-000003", index=7, country="US")
    # procedure_id="__empty__" is truthy; test the empty-string case explicitly
    proc = _cif_proc()
    proc["procedure_id"] = ""
    resource = _build_procedure(proc, patient_id="POP-000003", index=7, country="US")
    idents = resource["identifier"]
    structural = [i for i in idents if i.get("system") == PROCEDURE_KEY_SYSTEM]
    assert structural[0]["value"] == "ENC-POP-000003-635459597438-proc-POP-000003-007"


def test_build_procedure_same_key_reproduces_same_id() -> None:
    """Byte-diff invariant: two independent builds from the same fixture must agree."""
    a = _build_procedure(_cif_proc(), patient_id="POP-000003", index=0, country="JP")
    b = _build_procedure(_cif_proc(), patient_id="POP-000003", index=0, country="JP")
    assert a["id"] == b["id"]
