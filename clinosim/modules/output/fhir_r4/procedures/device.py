"""FHIR R4 Device + DeviceUseStatement builders (AD-55 Module: device).

Reads list[DeviceRecord] from ctx.record.extensions['device'] and emits
one Device + one DeviceUseStatement per record. PR-A introduces this
file; Phase 2 will add _fhir_hai.py beside it. The ctx-taking builders
import the shared BundleContext from _fhir_common, so this module never
imports back through the adapter (no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key, resolve_lang
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.lib.common import BundleContext
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

# Issue #854 Bucket A: opaque id + identifier[] round-trip for Device
# and DeviceUseStatement (same pattern PR #357 established for antibiotic
# MedicationRequest and PR #863 widened to all MR paths). The CIF
# ``DeviceRecord.device_id`` (e.g. ``dev-ENC-POP-000297-444117387516-
# mechanical-ventilator-2``, 55 chars) becomes the structural key input;
# both resolvers hash the same key so ``DUS.device.reference`` stays
# byte-consistent with ``Device.id`` by construction. Constants are
# PUBLIC (no underscore) so downstream readers can import them for
# identifier[]-based lookup without string-parsing the (now opaque) ids.
DEVICE_KEY_SYSTEM = structural_key_system("device-key")
DEVICE_USE_STATEMENT_KEY_SYSTEM = structural_key_system("device-use-statement-key")


def _resolve_device_id(structural_key: str) -> str:
    """Return the FHIR Device.id for a CIF DeviceRecord (Issue #854 Bucket A).

    Shape: ``dev-{sha256(structural_key)[:12]}``. The 4-char prefix retains
    the pre-#854 ``dev-`` identity so URLs stay recognizable as Devices;
    the compound CIF ``device_id`` is preserved in
    ``Device.identifier[]`` for round-trip.
    """
    return derive_opaque_id("dev-", structural_key)


def _resolve_device_use_statement_id(structural_key: str) -> str:
    """Return the FHIR DeviceUseStatement.id for a CIF DeviceRecord (Issue #854).

    Shape: ``dus-{sha256(structural_key)[:12]}``. Uses the SAME
    ``structural_key`` (CIF ``device_id``) as :func:`_resolve_device_id`
    so a consumer can trivially pair a DUS with its Device by hashing
    the round-tripped structural key from either resource's
    ``identifier[]``.
    """
    return derive_opaque_id("dus-", structural_key)


def _extensions_device_list(ctx: BundleContext) -> list:
    """Pull list[DeviceRecord] off ctx.record.extensions['device'] safely."""
    ext = get_attr_or_key(ctx.record, "extensions", {}) or {}
    return ext.get("device", []) or []


def _bb_device(ctx: BundleContext) -> list[dict]:
    """Build FHIR Device resources from CIF extensions['device']."""
    devices = _extensions_device_list(ctx)
    if not devices:
        return []
    lang = resolve_lang(ctx.country)
    out: list[dict] = []
    for d in devices:
        snomed = get_attr_or_key(d, "snomed_code", "")
        device_id = get_attr_or_key(d, "device_id", "")
        removal_date = get_attr_or_key(d, "removal_date", None)
        if not snomed or not device_id:
            continue
        display = code_lookup("snomed-ct", snomed, lang) or snomed
        resource: dict[str, Any] = {
            "resourceType": "Device",
            "id": _resolve_device_id(device_id),
            "identifier": [wrap_as_identifier(device_id, DEVICE_KEY_SYSTEM)],
            "status": "inactive" if removal_date else "active",
            "type": {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": snomed,
                        "display": display,
                    }
                ],
                "text": display,
            },
            "patient": patient_ref(ctx.patient_id),
        }
        out.append(resource)
    return out


def _bb_device_use(ctx: BundleContext) -> list[dict]:
    """Build FHIR DeviceUseStatement resources from CIF extensions['device']."""
    devices = _extensions_device_list(ctx)
    if not devices:
        return []
    out: list[dict] = []
    for d in devices:
        device_id = get_attr_or_key(d, "device_id", "")
        get_attr_or_key(d, "encounter_id", "")
        placement_date = get_attr_or_key(d, "placement_date", "")
        removal_date = get_attr_or_key(d, "removal_date", None)
        if not device_id or not placement_date:
            continue
        period: dict[str, Any] = {"start": placement_date}
        if removal_date:
            period["end"] = removal_date
        resource: dict[str, Any] = {
            "resourceType": "DeviceUseStatement",
            "id": _resolve_device_use_statement_id(device_id),
            "identifier": [wrap_as_identifier(device_id, DEVICE_USE_STATEMENT_KEY_SYSTEM)],
            "status": "completed" if removal_date else "active",
            "subject": patient_ref(ctx.patient_id),
            # Issue #854 Bucket A: device.reference goes through the SAME
            # _resolve_device_id derivation as Device.id so DUS→Device
            # cross-reference stays byte-consistent (pair by construction).
            "device": {"reference": f"Device/{_resolve_device_id(device_id)}"},
            "timingPeriod": period,
        }
        # feedback FB-F3: FHIR R4 DeviceUseStatement には `context` field 無し
        # (R3 から R4 で削除)。encounter は Device.patient から間接参照。
        # 元の resource["context"] emit は unknown property として validator error。
        # encounter 情報を保持したい場合は識別子 extension を使う必要あるが、
        # 現状は削除で spec 準拠を優先(将来 JP Core が拡張定義したら再追加)。
        out.append(resource)
    return out
