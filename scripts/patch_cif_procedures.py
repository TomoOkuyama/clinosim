#!/usr/bin/env python3
"""Patch an existing CIF tar.gz to conform with the new Procedure schema.

Changes applied to each procedure record:
  1. Remove procedure_name (AD-30: CIF stores only codes)
  2. Add procedure_code_jp and procedure_code_us (for multilingual FHIR coding)

Mapping sources:
  - Surgery codes: clinosim/modules/disease/reference_data/*.yaml
    (procedure.procedure_code_jp / procedure_code_us)
  - Bedside codes: clinosim/modules/procedure/engine.py _BEDSIDE_PROCEDURES
"""
from __future__ import annotations

import json
import re
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _load_bedside_map() -> dict[str, tuple[str, str]]:
    """Return {K/D/G/J code: (jp_code, us_code)}."""
    from clinosim.modules.procedure.engine import _BEDSIDE_PROCEDURES
    out: dict[str, tuple[str, str]] = {}
    for _proc_type, cpt, kcode, *_rest in _BEDSIDE_PROCEDURES:
        out[kcode] = (kcode, cpt)
        out[cpt] = (kcode, cpt)
    return out


def _load_disease_surgery_map() -> dict[str, tuple[str, str]]:
    """Return {any_code: (jp_code, us_code)} from disease YAMLs + hardcoded specials."""
    import yaml
    out: dict[str, tuple[str, str]] = {}
    dis_dir = REPO / "clinosim" / "modules" / "disease" / "reference_data"
    for f in dis_dir.glob("*.yaml"):
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        proc = d.get("procedure") or {}
        jp = proc.get("procedure_code_jp", "")
        us = proc.get("procedure_code_us", "")
        if jp and us:
            out[jp] = (jp, us)
            out[us] = (jp, us)
    # Hardcoded (hip_fracture has two variants handled at runtime — not in YAML)
    hardcoded = {
        "K0461": ("K0461", "27236"),  # ORIF femur
        "K0811": ("K0811", "27125"),  # Hemiarthroplasty
        "27236": ("K0461", "27236"),
        "27125": ("K0811", "27125"),
    }
    out.update(hardcoded)
    return out


def _build_code_map() -> dict[str, tuple[str, str]]:
    m = {}
    m.update(_load_bedside_map())
    m.update(_load_disease_surgery_map())
    return m


def patch_procedure(proc: dict, code_map: dict[str, tuple[str, str]]) -> tuple[dict, bool]:
    """Patch a single procedure dict. Returns (patched_proc, was_changed)."""
    changed = False
    # 1. Remove procedure_name
    if "procedure_name" in proc:
        proc.pop("procedure_name")
        changed = True
    # 2. Populate procedure_code_jp / procedure_code_us
    if "procedure_code_jp" not in proc or "procedure_code_us" not in proc:
        code = proc.get("procedure_code", "")
        if code in code_map:
            jp, us = code_map[code]
            proc["procedure_code_jp"] = jp
            proc["procedure_code_us"] = us
            changed = True
        else:
            # Unknown code — leave as-is (secondary coding will be omitted at export)
            proc.setdefault("procedure_code_jp", code if code.startswith(("K", "D", "G", "J")) else "")
            proc.setdefault("procedure_code_us", code if code and not code.startswith(("K", "D", "G", "J")) else "")
            changed = True
    return proc, changed


def patch_cif_tarball(tar_path: Path, out_path: Path) -> dict:
    """Extract, patch procedures, repack."""
    code_map = _build_code_map()
    print(f"Loaded {len(code_map)} code mappings")

    stats = {"patients_scanned": 0, "procedures_total": 0, "procedures_patched": 0,
             "unmapped_codes": set()}

    with tempfile.TemporaryDirectory() as tmpd:
        workdir = Path(tmpd)
        # Extract
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(workdir)

        # Patch every patient JSON
        patients_root = next(workdir.rglob("patients"), None)
        if patients_root is None:
            print("ERROR: no patients/ directory found in tarball")
            return stats

        for pf in patients_root.rglob("*.json"):
            try:
                p = json.loads(pf.read_text(encoding="utf-8"))
            except Exception:
                continue
            stats["patients_scanned"] += 1
            procs = p.get("procedures") or []
            if not procs:
                continue
            changed = False
            for pr in procs:
                if not isinstance(pr, dict):
                    continue
                stats["procedures_total"] += 1
                code = pr.get("procedure_code", "")
                if code and code not in code_map:
                    stats["unmapped_codes"].add(code)
                _, c = patch_procedure(pr, code_map)
                if c:
                    stats["procedures_patched"] += 1
                    changed = True
            if changed:
                pf.write_text(
                    json.dumps(p, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

        # Repack — skip macOS resource forks (._*) and hidden files
        dirs = [d for d in workdir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if not dirs:
            print("ERROR: no directory in workdir after extraction")
            return stats
        top_dir = dirs[0]

        def _filter(tarinfo):
            """Skip macOS AppleDouble files and OS metadata."""
            name = Path(tarinfo.name).name
            if name.startswith("._") or name == ".DS_Store":
                return None
            return tarinfo

        with tarfile.open(out_path, "w:gz") as tar:
            tar.add(top_dir, arcname=top_dir.name, filter=_filter)

    stats["unmapped_codes"] = sorted(stats["unmapped_codes"])
    return stats


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: patch_cif_procedures.py <input.tar.gz> <output.tar.gz>")
        sys.exit(1)
    stats = patch_cif_tarball(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"\n=== Patch stats ===")
    print(f"  Patients scanned: {stats['patients_scanned']}")
    print(f"  Procedures total: {stats['procedures_total']}")
    print(f"  Procedures patched: {stats['procedures_patched']}")
    print(f"  Unmapped codes: {stats['unmapped_codes']}")
