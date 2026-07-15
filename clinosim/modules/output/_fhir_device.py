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
from clinosim.modules.output._fhir_common import BundleContext


def _extensions_device_list(ctx: BundleContext) -> list:
    """Pull list[DeviceRecord] off ctx.record.extensions['device'] safely."""
    ext = get_attr_or_key(ctx.record, "extensions", {}) or {}
    return ext.get("device", []) or []


def _build_device(ctx: BundleContext) -> list[dict]:
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
            "id": device_id,
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
            "patient": {"reference": f"Patient/{ctx.patient_id}"},
        }
        out.append(resource)
    return out


def _build_device_use(ctx: BundleContext) -> list[dict]:
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
            "id": f"dus-{device_id}",
            "status": "completed" if removal_date else "active",
            "subject": {"reference": f"Patient/{ctx.patient_id}"},
            "device": {"reference": f"Device/{device_id}"},
            "timingPeriod": period,
        }
        # feedback FB-F3: FHIR R4 DeviceUseStatement には `context` field 無し
        # (R3 から R4 で削除)。encounter は Device.patient から間接参照。
        # 元の resource["context"] emit は unknown property として validator error。
        # encounter 情報を保持したい場合は識別子 extension を使う必要あるが、
        # 現状は削除で spec 準拠を優先(将来 JP Core が拡張定義したら再追加)。
        out.append(resource)
    return out
