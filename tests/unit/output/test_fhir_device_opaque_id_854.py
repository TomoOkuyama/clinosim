"""Issue #854 Bucket A: Device + DeviceUseStatement opaque id + identifier round-trip.

Pattern reused from PR #357 (Issue #349 Phase 1b — antibiotic MR) and PR #863
(Issue #853 — all MR + MA). Both `Device.id` and `DeviceUseStatement.id`
become opaque hashes of the CIF `DeviceRecord.device_id`; the compound key
is preserved in `identifier[]` under distinct system URIs. `DUS.device.reference`
resolves through the same `_resolve_device_id` derivation as `Device.id` so
cross-references stay byte-consistent by construction.

Pre-#854 (compound-id-as-key) shape:
- Device.id                    = "dev-ENC-POP-000297-444117387516-mechanical-ventilator-2" (55 chars)
- DUS.id                       = "dus-dev-ENC-POP-000297-444117387516-mechanical-ventilator-2" (59 chars)
- DUS.device.reference         = "Device/dev-ENC-POP-000297-444117387516-mechanical-ventilator-2"

Post-#854 (opaque):
- Device.id                    = "dev-<12hex>"  (16 chars, fixed)
- DUS.id                       = "dus-<12hex>"  (16 chars, fixed — SAME 12 hex as Device.id)
- DUS.device.reference         = "Device/dev-<same 12hex>"
- Both carry identifier[{system, value: compound_cif_device_id}] for round-trip.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.lib.common import BundleContext
from clinosim.modules.output.fhir_r4.procedures.device import (
    DEVICE_KEY_SYSTEM,
    DEVICE_USE_STATEMENT_KEY_SYSTEM,
    _bb_device,
    _bb_device_use,
    _resolve_device_id,
    _resolve_device_use_statement_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_DEV_PATTERN = re.compile(r"^dev-[0-9a-f]{12}$")
_OPAQUE_DUS_PATTERN = re.compile(r"^dus-[0-9a-f]{12}$")

_CIF_DEVICE_ID = "dev-ENC-POP-000297-444117387516-mechanical-ventilator-2"
_CIF_DEVICE_ID_2 = "dev-ENC-POP-000123-987654321012-cvc-0"


# === resolver contracts (unit) ===


def test_resolve_device_id_is_opaque() -> None:
    result = _resolve_device_id(_CIF_DEVICE_ID)
    assert _OPAQUE_DEV_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 16  # "dev-" (4) + 12 hex


def test_resolve_device_use_statement_id_is_opaque() -> None:
    result = _resolve_device_use_statement_id(_CIF_DEVICE_ID)
    assert _OPAQUE_DUS_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 16  # "dus-" (4) + 12 hex


def test_dev_and_dus_share_same_12hex_for_same_structural_key() -> None:
    """Both resolvers hash the SAME structural_key so a viewer can pair
    DUS ↔ Device by matching the trailing 12 hex chars. Only the 4-char
    prefix differs (dev- vs dus-)."""
    dev = _resolve_device_id(_CIF_DEVICE_ID)
    dus = _resolve_device_use_statement_id(_CIF_DEVICE_ID)
    assert dev[4:] == dus[4:]
    assert dev != dus


def test_resolvers_are_deterministic() -> None:
    assert _resolve_device_id(_CIF_DEVICE_ID) == _resolve_device_id(_CIF_DEVICE_ID)
    assert _resolve_device_use_statement_id(_CIF_DEVICE_ID) == _resolve_device_use_statement_id(_CIF_DEVICE_ID)


def test_resolvers_distinguish_different_structural_keys() -> None:
    assert _resolve_device_id(_CIF_DEVICE_ID) != _resolve_device_id(_CIF_DEVICE_ID_2)
    assert _resolve_device_use_statement_id(_CIF_DEVICE_ID) != _resolve_device_use_statement_id(_CIF_DEVICE_ID_2)


# === identifier system URIs are stable canonical constants ===


def test_device_key_system_uri() -> None:
    assert DEVICE_KEY_SYSTEM == "urn:clinosim:identifier:device-key"


def test_device_use_statement_key_system_uri() -> None:
    assert DEVICE_USE_STATEMENT_KEY_SYSTEM == "urn:clinosim:identifier:device-use-statement-key"


# === _bb_device + _bb_device_use end-to-end ===


def _ctx_with_device(*, country: str = "JP", placement_date: str = "2026-05-06T08:00:00") -> BundleContext:
    """Minimal BundleContext exercising the extensions['device'] emit path."""
    return BundleContext(
        record={
            "patient_id": "POP-000297",
            "extensions": {
                "device": [
                    {
                        "device_id": _CIF_DEVICE_ID,
                        "snomed_code": "706172005",
                        "encounter_id": "ENC-POP-000297-444117387516",
                        "placement_date": placement_date,
                        "removal_date": None,
                    }
                ],
            },
        },
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="POP-000297",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="M",
    )


def test_bb_device_emits_opaque_id() -> None:
    devices = _bb_device(_ctx_with_device())
    assert len(devices) == 1
    assert _OPAQUE_DEV_PATTERN.match(devices[0]["id"]), f"got {devices[0]['id']!r}"


def test_bb_device_carries_structural_key_identifier() -> None:
    devices = _bb_device(_ctx_with_device())
    assert len(devices) == 1
    idents = devices[0].get("identifier") or []
    assert len(idents) == 1
    assert idents[0] == {"system": DEVICE_KEY_SYSTEM, "value": _CIF_DEVICE_ID}


def test_bb_device_use_emits_opaque_id() -> None:
    duses = _bb_device_use(_ctx_with_device())
    assert len(duses) == 1
    assert _OPAQUE_DUS_PATTERN.match(duses[0]["id"]), f"got {duses[0]['id']!r}"


def test_bb_device_use_carries_structural_key_identifier() -> None:
    duses = _bb_device_use(_ctx_with_device())
    assert len(duses) == 1
    idents = duses[0].get("identifier") or []
    assert len(idents) == 1
    assert idents[0] == {"system": DEVICE_USE_STATEMENT_KEY_SYSTEM, "value": _CIF_DEVICE_ID}


def test_bb_device_use_reference_matches_device_id() -> None:
    """The critical cross-reference invariant: DUS.device.reference must
    resolve to exactly Device.id."""
    ctx = _ctx_with_device()
    device = _bb_device(ctx)[0]
    dus = _bb_device_use(ctx)[0]
    assert dus["device"]["reference"] == f"Device/{device['id']}"


def test_bb_device_us_output_shape_unchanged() -> None:
    """US locale exercises the same emit path — opaque ids apply regardless of country."""
    ctx = _ctx_with_device(country="US")
    device = _bb_device(ctx)[0]
    dus = _bb_device_use(ctx)[0]
    assert _OPAQUE_DEV_PATTERN.match(device["id"])
    assert _OPAQUE_DUS_PATTERN.match(dus["id"])
    assert dus["device"]["reference"] == f"Device/{device['id']}"


def test_bb_device_use_empty_when_no_placement_date() -> None:
    """placement_date is required — a record without it produces no DUS."""
    ctx = _ctx_with_device(placement_date="")
    assert _bb_device_use(ctx) == []
