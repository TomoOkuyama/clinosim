"""F3: canonical hash + 3 状態分類 test。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from clinosim.simulator.diff import (
    build_diff_bundle,
    canonical_hash,
    classify_resources,
    format_summary,
    load_ndjson_by_id,
)


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


# ===== Task 5: load_ndjson_by_id + build_diff_bundle + format_summary =====


def _write_ndjson(path: Path, resources: list[dict]) -> None:
    """Helper: list[dict] を NDJSON file に書き込み。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in resources:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


@pytest.mark.unit
def test_load_ndjson_by_id():
    """Single NDJSON file を {id: resource} dict に読み込み。"""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "Patient.ndjson"
        _write_ndjson(p, [
            {"resourceType": "Patient", "id": "p1"},
            {"resourceType": "Patient", "id": "p2"},
        ])
        result = load_ndjson_by_id(p)
        assert set(result.keys()) == {"p1", "p2"}


@pytest.mark.unit
def test_build_diff_bundle_all_new():
    """old_dir が空で new_dir に新規 resource → 全て POST。"""
    with tempfile.TemporaryDirectory() as tmp:
        old_dir = Path(tmp) / "old"
        new_dir = Path(tmp) / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        _write_ndjson(new_dir / "Patient.ndjson", [
            {"resourceType": "Patient", "id": "p1"},
        ])

        bundle = build_diff_bundle(
            old_dir,
            new_dir,
            bundle_id="test",
            last_updated="2026-06-01T00:00:00+09:00",
        )
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "transaction"
        assert len(bundle["entry"]) == 1
        e = bundle["entry"][0]
        assert e["request"]["method"] == "POST"
        assert e["request"]["url"] == "Patient"


@pytest.mark.unit
def test_build_diff_bundle_updated():
    """old_dir と new_dir で id 同一だが content 異なる → PUT。"""
    with tempfile.TemporaryDirectory() as tmp:
        old_dir = Path(tmp) / "old"
        new_dir = Path(tmp) / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        _write_ndjson(old_dir / "Encounter.ndjson", [
            {"resourceType": "Encounter", "id": "e1", "status": "in-progress"},
        ])
        _write_ndjson(new_dir / "Encounter.ndjson", [
            {"resourceType": "Encounter", "id": "e1", "status": "finished"},
        ])

        bundle = build_diff_bundle(
            old_dir,
            new_dir,
            bundle_id="test",
            last_updated="2026-06-01T00:00:00+09:00",
        )
        assert len(bundle["entry"]) == 1
        e = bundle["entry"][0]
        assert e["request"]["method"] == "PUT"
        assert e["request"]["url"] == "Encounter/e1"
        assert e["resource"]["status"] == "finished"


@pytest.mark.unit
def test_build_diff_bundle_unchanged_skipped():
    """old と new で id + content 同一 → Bundle entry に含めない。"""
    with tempfile.TemporaryDirectory() as tmp:
        old_dir = Path(tmp) / "old"
        new_dir = Path(tmp) / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        r = {"resourceType": "Patient", "id": "p1", "name": [{"family": "A"}]}
        _write_ndjson(old_dir / "Patient.ndjson", [r])
        _write_ndjson(new_dir / "Patient.ndjson", [r])

        bundle = build_diff_bundle(
            old_dir,
            new_dir,
            bundle_id="test",
            last_updated="2026-06-01T00:00:00+09:00",
        )
        assert bundle["entry"] == []


@pytest.mark.unit
def test_build_diff_bundle_mixed_types():
    """複数 resource type、new + updated 混合。"""
    with tempfile.TemporaryDirectory() as tmp:
        old_dir = Path(tmp) / "old"
        new_dir = Path(tmp) / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        _write_ndjson(old_dir / "Patient.ndjson", [
            {"resourceType": "Patient", "id": "p1"}
        ])
        _write_ndjson(new_dir / "Patient.ndjson", [
            {"resourceType": "Patient", "id": "p1"},
            {"resourceType": "Patient", "id": "p2"},  # new
        ])
        _write_ndjson(new_dir / "Encounter.ndjson", [
            {"resourceType": "Encounter", "id": "e1", "status": "finished"},  # new
        ])

        bundle = build_diff_bundle(
            old_dir,
            new_dir,
            bundle_id="test",
            last_updated="2026-06-01T00:00:00+09:00",
        )
        methods = [e["request"]["method"] for e in bundle["entry"]]
        assert methods.count("POST") == 2
        assert methods.count("PUT") == 0


@pytest.mark.unit
def test_format_summary_basic():
    """Bundle transaction の summary text。cursors + resource types + counts。"""
    with tempfile.TemporaryDirectory() as tmp:
        old_dir = Path(tmp) / "old"
        new_dir = Path(tmp) / "new"
        old_dir.mkdir()
        new_dir.mkdir()
        _write_ndjson(new_dir / "Patient.ndjson", [
            {"resourceType": "Patient", "id": "p1"}
        ])
        bundle = build_diff_bundle(
            old_dir,
            new_dir,
            bundle_id="test",
            last_updated="2026-06-01T00:00:00+09:00",
        )
        summary = format_summary(
            bundle,
            old_cursor="2026-05-31",
            new_cursor="2026-06-01",
        )
        assert "2026-05-31" in summary
        assert "2026-06-01" in summary
        assert "Patient" in summary
        assert "1" in summary  # 1 entry


# ===== Task 6: CLI smoke test =====


@pytest.mark.unit
def test_cli_diff_smoke(tmp_path):
    """clinosim diff subcommand smoke test — subprocess invoke。"""
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write_ndjson(new_dir / "Patient.ndjson", [{"resourceType": "Patient", "id": "p1"}])

    bundle_path = tmp_path / "bundle.json"
    summary_path = tmp_path / "summary.txt"

    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "diff",
         "--old", str(old_dir),
         "--new", str(new_dir),
         "--output-bundle", str(bundle_path),
         "--output-summary", str(summary_path),
         "--old-cursor", "2026-05-31",
         "--new-cursor", "2026-06-01"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    bundle = json.loads(bundle_path.read_text())
    assert bundle["type"] == "transaction"
    assert len(bundle["entry"]) == 1
    summary = summary_path.read_text()
    assert "2026-05-31" in summary
    assert "2026-06-01" in summary
