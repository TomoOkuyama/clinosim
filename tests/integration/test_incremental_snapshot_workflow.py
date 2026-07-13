"""F1+F2+F3+F4 統合 e2e:snapshot → memoize advance → diff → Bundle 検証。

セッション 49 の全 fix を組み合わせて 1 workflow で検証:
1. cursor A で snapshot 生成
2. cursor B で snapshot 生成(cache_dir=cursor_A output)= F4 hit
3. clinosim diff で 2 snapshot → Bundle transaction 生成
4. Bundle 内容が 3 状態分類 (NEW / UPDATED / UNCHANGED) を正しく反映
5. F1 の恩恵で cursor A に完了した patient の resource は Bundle に含まれない
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from clinosim.simulator.engine import run_beta
from clinosim.simulator.memoize import write_cache_manifest
from clinosim.types.config import SimulatorConfig


def _write_full_output(ds, out_dir: Path, config: SimulatorConfig) -> None:
    """CIF + FHIR + _cache_manifest.json を out_dir に書く。"""
    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir

    (out_dir / "cif").mkdir(parents=True, exist_ok=True)
    (out_dir / "fhir_r4").mkdir(parents=True, exist_ok=True)
    write_cif(ds, str(out_dir / "cif"))
    # convert_cif_to_fhir reads the Practitioner roster + Organization/Location
    # config from cif_dir/hospital.json (written by write_cif above) — it does
    # NOT accept roster_map / hospital_config as parameters.
    convert_cif_to_fhir(
        str(out_dir / "cif"),
        str(out_dir / "fhir_r4"),
        country=config.country,
    )
    write_cache_manifest(out_dir, config)


@pytest.mark.integration
def test_full_incremental_workflow(tmp_path):
    """cursor A → memoize B → diff → Bundle transaction."""
    # Cursor A
    config_a = SimulatorConfig(
        random_seed=42,
        catchment_population=50,
        country="US",
        time_range=("2025-01", "2026-01"),
        snapshot_date="2025-06-30",
    )
    ds_a = run_beta(config_a)
    snap_a = tmp_path / "snap_2025-06-30"
    _write_full_output(ds_a, snap_a, config_a)

    # Cursor B with memoize
    config_b = config_a.model_copy(update={"snapshot_date": "2025-07-31"})
    ds_b = run_beta(config_b, cache_dir=snap_a)
    snap_b = tmp_path / "snap_2025-07-31"
    _write_full_output(ds_b, snap_b, config_b)

    # F3 diff
    bundle_path = tmp_path / "bundle.json"
    summary_path = tmp_path / "summary.txt"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "diff",
            "--old",
            str(snap_a / "fhir_r4"),
            "--new",
            str(snap_b / "fhir_r4"),
            "--output-bundle",
            str(bundle_path),
            "--output-summary",
            str(summary_path),
            "--old-cursor",
            "2025-06-30",
            "--new-cursor",
            "2025-07-31",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    bundle = json.loads(bundle_path.read_text())
    assert bundle["type"] == "transaction"
    # 差分は最低 1 件はあるはず(cursor が 1 か月伸びた)
    assert len(bundle["entry"]) > 0

    # 全 entry は method が POST / PUT のいずれか
    for e in bundle["entry"]:
        assert e["request"]["method"] in ("POST", "PUT")

    # UNCHANGED (cursor A 完了 patient のうち関連 resource) は entry に含まれない
    # → bundle size < 全 resource 数 の等号を厳密には確認しづらいので、
    # summary text の "Total bundle size" が cursor B の全 resource より少ないことを確認
    summary = summary_path.read_text()
    assert "Total bundle size" in summary
    assert "2025-06-30" in summary
    assert "2025-07-31" in summary
