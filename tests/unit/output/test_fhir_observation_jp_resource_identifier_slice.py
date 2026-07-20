"""Regression: JP Observation.identifier:resourceIdentifier slice conformance.

Guards session 57 chain A (v2 feedback §【最優先 1】, -7.3pp headroom).

* For JP output, every Observation must expose an `identifier[]` entry
  whose `.system` equals the JP-CLINS
  ``JP_Observation_LabResult_eCS`` profile's
  `identifier:resourceIdentifier.system` patternUri
  (``http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier``).
* For US output, the internal clinosim namespace
  (``urn:clinosim:observation-id``) is preserved as the only identifier.
* Both cases keep `value = Observation.id` so downstream consumers can
  round-trip clinosim resources.

Also pins the spec patternUri by reading the JP-CLINS StructureDefinition
JSON directly. Any future spec revision that changes the required URI
must regenerate both the constant in ``fhir_r4_adapter`` and the pinned
literal here (feedback_verify_fhir_profile_uri_from_spec rule).
"""

from __future__ import annotations

import json
from pathlib import Path

from clinosim.modules.output.fhir_r4_adapter import (
    _CLINOSIM_OBSERVATION_ID_SYSTEM,
    _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM,
    _populate_observation_identifier_and_last_updated,
)

_JP_CLINS_ECS_SD = (
    Path(__file__).resolve().parents[3]
    / ".."
    / "fhir-jp-validator"
    / "tx-server-build"
    / "terminology"
    / "fhir-server"
    / "clinical-information-sharing#1.12.0"
    / "package"
    / "StructureDefinition-JP-Observation-LabResult-eCS.json"
)


# === walker behavior ===


def test_jp_observation_prepends_resource_identifier_slice() -> None:
    obs = {"resourceType": "Observation", "id": "obs-jp-1"}
    _populate_observation_identifier_and_last_updated(obs, country="JP")
    ids = obs["identifier"]
    assert len(ids) == 2, f"JP identifier list must be 2-element, got {ids}"
    assert ids[0]["system"] == _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM
    assert ids[0]["value"] == "obs-jp-1"
    assert ids[1]["system"] == _CLINOSIM_OBSERVATION_ID_SYSTEM
    assert ids[1]["value"] == "obs-jp-1"


def test_us_observation_keeps_clinosim_namespace_only() -> None:
    obs = {"resourceType": "Observation", "id": "obs-us-1"}
    _populate_observation_identifier_and_last_updated(obs, country="US")
    ids = obs["identifier"]
    assert len(ids) == 1
    assert ids[0]["system"] == _CLINOSIM_OBSERVATION_ID_SYSTEM
    assert ids[0]["value"] == "obs-us-1"


def test_default_country_empty_uses_clinosim_namespace() -> None:
    """Backward-compat: pre-signature-change callers pass no country arg."""
    obs = {"resourceType": "Observation", "id": "obs-default"}
    _populate_observation_identifier_and_last_updated(obs)
    ids = obs["identifier"]
    assert len(ids) == 1
    assert ids[0]["system"] == _CLINOSIM_OBSERVATION_ID_SYSTEM


def test_builder_populated_identifier_preserved_and_jp_slice_prepended() -> None:
    """Issue #336: builder-populated identifier (例: microbiology の
    HAI_EVENT_ID_SYSTEM) は保持されるが、JP canonical resourceIdentifier
    slice が必要なため walker で必ず prepend される。従来 walker が全体
    skip していたため v9 obs で 1 件 slice min=1 error 発火 → fix。"""
    obs = {
        "resourceType": "Observation",
        "id": "obs-preset",
        "identifier": [{"system": "http://example.org/pre-existing", "value": "X"}],
    }
    _populate_observation_identifier_and_last_updated(obs, country="JP")
    systems = [i["system"] for i in obs["identifier"]]
    # 既存 identifier は保持
    assert "http://example.org/pre-existing" in systems
    # JP canonical resourceIdentifier slice が prepend されている(slice discriminator satisfy)
    assert _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM in systems
    assert systems[0] == _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM
    # 内部 round-trip namespace も追加(既存 downstream consumer 用)
    assert _CLINOSIM_OBSERVATION_ID_SYSTEM in systems


def test_non_observation_resource_is_ignored() -> None:
    """Walker no-op on non-Observation resource types."""
    cond = {"resourceType": "Condition", "id": "cond-1"}
    _populate_observation_identifier_and_last_updated(cond, country="JP")
    assert "identifier" not in cond


# === spec alignment ===


def test_jp_clins_ecs_spec_pin_resource_identifier_patternuri() -> None:
    if not _JP_CLINS_ECS_SD.exists():
        import pytest

        pytest.skip(f"JP-CLINS eCS spec not available at {_JP_CLINS_ECS_SD}")
    with open(_JP_CLINS_ECS_SD) as f:
        sd = json.load(f)
    target: dict = {}
    for e in sd.get("differential", {}).get("element", []):
        if e.get("id") == "Observation.identifier:resourceIdentifier.system":
            target = e
            break
    assert target, "spec element resourceIdentifier.system not found"
    assert target.get("patternUri") == _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM, (
        f"spec patternUri drifted from constant; got {target.get('patternUri')!r}"
    )
