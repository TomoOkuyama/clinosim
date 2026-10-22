"""Oxygen device-mode → SNOMED CT concept resolver (Phase 3.β.3, #1808 follow-up).

Mirrors Phase 3.β.6 ``stage_to_snomed`` / Phase 3.β.2 ``blood_group_to_snomed``:
``clinosim/codes/data/oxygen-device-to-snomed.yaml`` holds the internal
device-mode → SNOMED code pointers; this module is the loader that
``fhir_r4/procedures/oxygen_therapy.py`` uses in place of the retired
module-local ``_SNOMED_DEVICE_BY_MODE`` dict.

The SNOMED display is still resolved via
``clinosim.codes.lookup("snomed-ct", code, lang)`` against the authority
yaml — this catalog carries only the pointer, keeping the display SoT
in ``snomed-ct.yaml``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

_DATA_FILE = Path(__file__).parent / "data" / "oxygen-device-to-snomed.yaml"


@cache
def _load_catalog() -> dict[str, str]:
    """Load the device-mode → SNOMED code mapping. Fail-loud on missing
    file — downstream FHIR Procedure.usedCode coding depends on it."""
    if not _DATA_FILE.exists():
        raise FileNotFoundError(f"oxygen-device-to-snomed.yaml not found at {_DATA_FILE}")
    with _DATA_FILE.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    devices = raw.get("devices") or {}
    if not isinstance(devices, dict):
        raise ValueError(f"oxygen-device-to-snomed.yaml: 'devices' must be a mapping, got {type(devices).__name__}")
    return {str(k): str(v) for k, v in devices.items() if v}


def resolve_device_snomed(device_mode: str) -> str | None:
    """Return the SNOMED CT concept id for oxygen-device-mode
    ``device_mode``, or None when the mode has no catalog entry.

    The None return keeps the FHIR emitter's existing silent-skip
    behaviour for unknown values (same as the retired
    ``_SNOMED_DEVICE_BY_MODE.get(device_mode)``)."""
    if not device_mode:
        return None
    return _load_catalog().get(device_mode)


def all_device_modes() -> tuple[str, ...]:
    """Return every registered device mode (sorted). Used by integrity
    tests + audit scripts."""
    return tuple(sorted(_load_catalog().keys()))
