"""Issue #336 — Observation walker が builder-populated identifier を
保持しつつ、JP_Observation_LabResult_eCS の resourceIdentifier slice を
必ず satisfy する。

v9 (seed=500 p=5000 master cbfacc6ebf) obs validation で 1 件 slice error:

    Slice 'Observation.identifier:resourceIdentifier': minimum required = 1,
    but only found 0
    (from JP_Observation_LabResult_eCS)
    mb-org-ENC-POP-002287-170531078110-0

Root cause: `_populate_observation_identifier_and_last_updated` の従来
`if not resource.get("identifier"):` は builder-populated identifier
(microbiology で HAI_EVENT_ID_SYSTEM)がある場合 walker 全体 skip →
JP-CLINS の canonical resourceInstance-identifier が付かず slice min=1 fail。

Fix: sibling MedicationRequest walker (line 1908-1924) と同じ
idempotent-prepend pattern。
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4_adapter import (
    _CLINOSIM_OBSERVATION_ID_SYSTEM,
    _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM,
    _populate_observation_identifier_and_last_updated,
)

pytestmark = pytest.mark.unit


_HAI_EVENT_ID_SYSTEM = "urn:clinosim:identifier:hai-event-id"


def test_walker_adds_jp_resource_identifier_when_no_identifier() -> None:
    """既存 identifier 無しの標準 Observation で JP output = 2 element 追加."""
    obs = {
        "resourceType": "Observation",
        "id": "obs-vs-123",
        "effectiveDateTime": "2026-01-01T09:00:00+09:00",
    }
    _populate_observation_identifier_and_last_updated(obs, "JP")
    ids = obs["identifier"]
    systems = [i["system"] for i in ids]
    assert _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM in systems
    assert _CLINOSIM_OBSERVATION_ID_SYSTEM in systems
    # canonical URI must come first (slice discriminator priority)
    assert systems[0] == _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM


def test_walker_preserves_hai_identifier_and_prepends_jp_slice() -> None:
    """Issue #336 regression: HAI-derived microbiology で walker が
    HAI id を保持しつつ、JP canonical slice を prepend する。"""
    obs = {
        "resourceType": "Observation",
        "id": "mb-org-ENC-POP-002287-170531078110-0",
        "identifier": [{"system": _HAI_EVENT_ID_SYSTEM, "value": "HAI-CLABSI-001"}],
        "effectiveDateTime": "2026-01-01T09:00:00+09:00",
    }
    _populate_observation_identifier_and_last_updated(obs, "JP")
    ids = obs["identifier"]
    systems = [i["system"] for i in ids]
    # 元 HAI id は保持されている
    assert _HAI_EVENT_ID_SYSTEM in systems
    # JP canonical slice が追加されている(slice discriminator satisfy)
    assert _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM in systems
    # internal round-trip も追加されている
    assert _CLINOSIM_OBSERVATION_ID_SYSTEM in systems
    # JP canonical は先頭(idempotent-prepend pattern)
    assert systems[0] == _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM


def test_walker_is_idempotent() -> None:
    """再実行しても identifier list に重複が入らない."""
    obs = {
        "resourceType": "Observation",
        "id": "obs-test",
        "effectiveDateTime": "2026-01-01T09:00:00+09:00",
    }
    _populate_observation_identifier_and_last_updated(obs, "JP")
    first = list(obs["identifier"])
    _populate_observation_identifier_and_last_updated(obs, "JP")
    second = list(obs["identifier"])
    assert first == second, "walker は idempotent であること(重複追加禁止)"


def test_walker_us_output_only_adds_internal_identifier() -> None:
    """US output では JP canonical URI は付けない."""
    obs = {
        "resourceType": "Observation",
        "id": "obs-us-test",
        "effectiveDateTime": "2026-01-01T09:00:00-05:00",
    }
    _populate_observation_identifier_and_last_updated(obs, "US")
    ids = obs["identifier"]
    systems = [i["system"] for i in ids]
    assert _CLINOSIM_OBSERVATION_ID_SYSTEM in systems
    assert _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM not in systems


def test_walker_us_preserves_hai_identifier() -> None:
    """US output でも既存 HAI id を保持する(microbiology のみ)."""
    obs = {
        "resourceType": "Observation",
        "id": "mb-org-test",
        "identifier": [{"system": _HAI_EVENT_ID_SYSTEM, "value": "HAI-VAP-001"}],
        "effectiveDateTime": "2026-01-01T09:00:00-05:00",
    }
    _populate_observation_identifier_and_last_updated(obs, "US")
    systems = [i["system"] for i in obs["identifier"]]
    assert _HAI_EVENT_ID_SYSTEM in systems
    assert _CLINOSIM_OBSERVATION_ID_SYSTEM in systems
    assert _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM not in systems
