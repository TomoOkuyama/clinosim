"""F3: canonical hash + 3 状態分類 test。"""
from __future__ import annotations

import pytest

from clinosim.simulator.diff import canonical_hash, classify_resources


@pytest.mark.unit
def test_canonical_hash_stable_across_key_order():
    """dict key order 非依存で同 hash。"""
    r1 = {"resourceType": "Patient", "id": "p1", "name": [{"family": "Yamada"}]}
    r2 = {"id": "p1", "name": [{"family": "Yamada"}], "resourceType": "Patient"}
    assert canonical_hash(r1) == canonical_hash(r2)


def test_canonical_hash_ignores_meta_last_updated():
    """meta.lastUpdated が違っても同 hash(cursor 依存 field を除外)。"""
    r1 = {"resourceType": "Patient", "id": "p1",
          "meta": {"lastUpdated": "2026-05-31T00:00:00+09:00"}}
    r2 = {"resourceType": "Patient", "id": "p1",
          "meta": {"lastUpdated": "2026-06-01T00:00:00+09:00"}}
    assert canonical_hash(r1) == canonical_hash(r2)


def test_canonical_hash_ignores_meta_version_id():
    """meta.versionId が違っても同 hash。"""
    r1 = {"resourceType": "Patient", "id": "p1", "meta": {"versionId": "1"}}
    r2 = {"resourceType": "Patient", "id": "p1", "meta": {"versionId": "2"}}
    assert canonical_hash(r1) == canonical_hash(r2)


def test_canonical_hash_ignores_meta_source():
    """meta.source が違っても同 hash。"""
    r1 = {"resourceType": "Patient", "id": "p1", "meta": {"source": "a"}}
    r2 = {"resourceType": "Patient", "id": "p1", "meta": {"source": "b"}}
    assert canonical_hash(r1) == canonical_hash(r2)


def test_canonical_hash_preserves_meta_profile():
    """meta.profile は意味論的差分なので保持。"""
    r1 = {"resourceType": "Patient", "id": "p1", "meta": {"profile": ["a"]}}
    r2 = {"resourceType": "Patient", "id": "p1", "meta": {"profile": ["b"]}}
    assert canonical_hash(r1) != canonical_hash(r2)


def test_canonical_hash_detects_content_change():
    """resource 本体の差分は当然 hash 変化。"""
    r1 = {"resourceType": "Encounter", "id": "e1", "status": "in-progress"}
    r2 = {"resourceType": "Encounter", "id": "e1", "status": "finished"}
    assert canonical_hash(r1) != canonical_hash(r2)


def test_classify_resources_new_only():
    """new_by_id にしかない id は new_only に。"""
    old = {}
    new = {"p1": {"resourceType": "Patient", "id": "p1"}}
    new_only, updated, unchanged = classify_resources(old, new)
    assert len(new_only) == 1 and new_only[0]["id"] == "p1"
    assert updated == [] and unchanged == []


def test_classify_resources_updated_only():
    """両方にある id で hash 違えば updated。"""
    old = {"e1": {"resourceType": "Encounter", "id": "e1", "status": "in-progress"}}
    new = {"e1": {"resourceType": "Encounter", "id": "e1", "status": "finished"}}
    new_only, updated, unchanged = classify_resources(old, new)
    assert new_only == []
    assert len(updated) == 1 and updated[0]["status"] == "finished"
    assert unchanged == []


def test_classify_resources_unchanged():
    """両方にある id で hash 同一なら unchanged。"""
    r = {"resourceType": "Patient", "id": "p1", "name": [{"family": "Yamada"}]}
    new_only, updated, unchanged = classify_resources({"p1": r}, {"p1": dict(r)})
    assert new_only == [] and updated == []
    assert len(unchanged) == 1


def test_classify_resources_mixed():
    """3 状態混合。"""
    old = {
        "p1": {"resourceType": "Patient", "id": "p1", "name": [{"family": "A"}]},
        "e1": {"resourceType": "Encounter", "id": "e1", "status": "in-progress"},
    }
    new = {
        "p1": {"resourceType": "Patient", "id": "p1", "name": [{"family": "A"}]},  # unchanged
        "e1": {"resourceType": "Encounter", "id": "e1", "status": "finished"},     # updated
        "p2": {"resourceType": "Patient", "id": "p2", "name": [{"family": "B"}]}, # new
    }
    new_only, updated, unchanged = classify_resources(old, new)
    assert len(new_only) == 1 and new_only[0]["id"] == "p2"
    assert len(updated) == 1 and updated[0]["id"] == "e1"
    assert len(unchanged) == 1 and unchanged[0]["id"] == "p1"
