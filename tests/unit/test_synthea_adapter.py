"""P1-10 (session 46) — Synthea → clinosim eval adapter tests.

Fixture-based: crafts a minimal Synthea-style Bundle in a tmp dir,
runs the adapter, and asserts the output NDJSON layout matches what
`clinosim.eval.EvalEngine` expects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.eval.synthea_adapter import (
    bundle_dir_to_ndjson_layout,
    looks_like_synthea_output,
)


def _write_bundle(path: Path, resources: list[dict]) -> None:
    """Emit a minimal FHIR Bundle with `resources` in its entry list."""
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{"resource": r} for r in resources],
    }
    path.write_text(json.dumps(bundle), encoding="utf-8")


@pytest.mark.unit
def test_looks_like_synthea_flags_bundle_dir(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text("{}")
    assert looks_like_synthea_output(tmp_path)


@pytest.mark.unit
def test_looks_like_synthea_rejects_clinosim_layout(tmp_path: Path) -> None:
    (tmp_path / "fhir_r4").mkdir()
    (tmp_path / "fhir_r4" / "Patient.ndjson").write_text('{"resourceType":"Patient"}\n')
    assert not looks_like_synthea_output(tmp_path)


@pytest.mark.unit
def test_bundle_dir_to_ndjson_layout_fans_by_resource_type(tmp_path: Path) -> None:
    """Two Bundles with mixed resource types produce one NDJSON per
    ResourceType with the expected row counts."""
    in_dir = tmp_path / "synthea"
    in_dir.mkdir()
    _write_bundle(
        in_dir / "patient_a.json",
        [
            {"resourceType": "Patient", "id": "pa"},
            {"resourceType": "Encounter", "id": "ea1"},
            {"resourceType": "Encounter", "id": "ea2"},
            {"resourceType": "Observation", "id": "oa1"},
        ],
    )
    _write_bundle(
        in_dir / "patient_b.json",
        [
            {"resourceType": "Patient", "id": "pb"},
            {"resourceType": "Encounter", "id": "eb1"},
            {"resourceType": "Observation", "id": "ob1"},
            {"resourceType": "Observation", "id": "ob2"},
        ],
    )
    out = tmp_path / "normalized"
    counts = bundle_dir_to_ndjson_layout(in_dir, out)

    assert counts == {"Patient": 2, "Encounter": 3, "Observation": 3}
    # Layout matches clinosim's expectation.
    fhir = out / "fhir_r4"
    assert (fhir / "Patient.ndjson").exists()
    assert (fhir / "Encounter.ndjson").exists()
    assert (fhir / "Observation.ndjson").exists()
    # Line counts match.
    for rt, n in counts.items():
        assert sum(1 for _ in (fhir / f"{rt}.ndjson").open()) == n


@pytest.mark.unit
def test_conversion_is_deterministic(tmp_path: Path) -> None:
    """Running the adapter twice on the same input produces byte-identical
    NDJSON — critical for eval reproducibility across Synthea + clinosim."""
    in_dir = tmp_path / "synthea"
    in_dir.mkdir()
    _write_bundle(
        in_dir / "p0.json",
        [
            {"resourceType": "Patient", "id": "p0"},
            {"resourceType": "Encounter", "id": "e0"},
        ],
    )
    _write_bundle(
        in_dir / "p1.json",
        [
            {"resourceType": "Patient", "id": "p1"},
            {"resourceType": "Observation", "id": "obs-1"},
        ],
    )
    a = tmp_path / "run-a"
    b = tmp_path / "run-b"
    bundle_dir_to_ndjson_layout(in_dir, a)
    bundle_dir_to_ndjson_layout(in_dir, b)
    for rt in ("Patient", "Encounter", "Observation"):
        assert (a / "fhir_r4" / f"{rt}.ndjson").read_bytes() == (b / "fhir_r4" / f"{rt}.ndjson").read_bytes()


@pytest.mark.unit
def test_missing_input_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        bundle_dir_to_ndjson_layout(tmp_path / "no-such-dir", tmp_path / "out")


@pytest.mark.unit
def test_non_bundle_json_is_ignored(tmp_path: Path) -> None:
    """Random JSON files that aren't Bundles must not crash the adapter."""
    in_dir = tmp_path / "synthea"
    in_dir.mkdir()
    (in_dir / "settings.json").write_text('{"generator":"synthea","version":"3.0"}')
    _write_bundle(
        in_dir / "patient.json",
        [
            {"resourceType": "Patient", "id": "px"},
        ],
    )
    counts = bundle_dir_to_ndjson_layout(in_dir, tmp_path / "out")
    assert counts == {"Patient": 1}


@pytest.mark.unit
def test_output_ndjson_feeds_eval_engine(tmp_path: Path) -> None:
    """The normalized output must be consumable by EvalEngine end-to-end."""
    in_dir = tmp_path / "synthea"
    in_dir.mkdir()
    _write_bundle(
        in_dir / "b.json",
        [
            {"resourceType": "Patient", "id": "px", "identifier": [{"value": "x"}], "address": [{"country": "US"}]},
            {
                "resourceType": "Encounter",
                "id": "ex",
                "status": "finished",
                "period": {"start": "2026-01-01", "end": "2026-01-05"},
            },
        ],
    )
    out = tmp_path / "normalized"
    bundle_dir_to_ndjson_layout(in_dir, out)

    from clinosim.eval.engine import EvalEngine

    report = EvalEngine(cohort_dir=out).run()
    # Structural + clinical + locale.
    assert len(report.axes) == 3
    assert report.resource_counts["_flat"]["Patient"] == 1
    assert report.resource_counts["_flat"]["Encounter"] == 1
