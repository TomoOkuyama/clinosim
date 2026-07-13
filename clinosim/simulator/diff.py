"""FHIR snapshot diff — 2 snapshot output の差分を FHIR Bundle transaction に変換 (F3, session 49)。

Approach C の operational cover。clinosim 自身は決定的な snapshot generator に留まり、
「cursor 移動した差分だけを FHIR server に POST する」用の Bundle 生成をここで行う。
push は user 側 tool (curl / httpx / hapi-fhir-cli) に委ねる。
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

# meta 内 cursor 依存 field。hash 計算前に strip する。
_META_HASH_IGNORE_KEYS = ("lastUpdated", "versionId", "source")


def canonical_hash(resource: dict) -> str:
    """Resource の canonical sha256 hash。

    meta.lastUpdated / meta.versionId / meta.source は cursor 依存で
    変わりうるので hash 前に除外(false-positive UPDATED を防ぐ)。
    meta.profile / meta.security 等は意味論的差分なので保持。

    dict key order は sorted で正規化。
    """
    # 深いコピーして meta を strip(元 resource を破壊しない)
    stripped = copy.deepcopy(resource)
    meta = stripped.get("meta")
    if isinstance(meta, dict):
        for k in _META_HASH_IGNORE_KEYS:
            meta.pop(k, None)
        if not meta:
            stripped.pop("meta", None)
    return hashlib.sha256(
        json.dumps(stripped, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def classify_resources(
    old_by_id: dict[str, dict],
    new_by_id: dict[str, dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Resource id ごとに (new_only, updated, unchanged) に分類。

    DELETED(old にあり new にない)は snapshot が cumulative なので通常発生しない。
    発生した場合は上位 caller で warning ログを出す(この関数は返り値に含めない)。

    Args:
        old_by_id: 前 snapshot の {id: resource}
        new_by_id: 現 snapshot の {id: resource}

    Returns:
        (new_only, updated, unchanged) の 3 list。全て resource dict の list。
    """
    new_only: list[dict] = []
    updated: list[dict] = []
    unchanged: list[dict] = []

    for rid, new_r in new_by_id.items():
        old_r = old_by_id.get(rid)
        if old_r is None:
            new_only.append(new_r)
        elif canonical_hash(old_r) != canonical_hash(new_r):
            updated.append(new_r)
        else:
            unchanged.append(new_r)

    return new_only, updated, unchanged


def load_ndjson_by_id(path: Path) -> dict[str, dict]:
    """単一 NDJSON file を {resource.id: resource} 辞書に読み込む。

    Args:
        path: NDJSON file path。存在しなければ空辞書を返す。

    Returns:
        {resource.id: resource_dict}。id なし resource は除外。
    """
    result: dict[str, dict] = {}
    if not path.exists():
        return result
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rid = r.get("id")
            if rid:
                result[rid] = r
    return result


def _iter_resource_types(directory: Path) -> Iterator[tuple[str, Path]]:
    """directory 内の *.ndjson を (resource_type, path) で yield。

    Args:
        directory: NDJSON file が格納されたディレクトリ。

    Yields:
        (resource_type_from_filename, path) tuples。
    """
    for path in sorted(directory.glob("*.ndjson")):
        rt = path.stem
        yield rt, path


def build_diff_bundle(
    old_dir: Path,
    new_dir: Path,
    bundle_id: str,
    last_updated: str,
) -> dict:
    """2 snapshot output directory から FHIR Bundle transaction を生成する。

    Args:
        old_dir: 前 snapshot の FHIR NDJSON directory。
        new_dir: 現 snapshot の FHIR NDJSON directory。
        bundle_id: Bundle.id。
        last_updated: Bundle.meta.lastUpdated (FHIR instant format)。

    Returns:
        FHIR R4 Bundle resource (transaction type)。
        NEW resource は POST、UPDATED resource は PUT、UNCHANGED resource は除外。
    """
    entries: list[dict] = []

    # 新 dir の全 resource type を対象(旧 dir 側で消滅した type は空)
    resource_types = {rt for rt, _ in _iter_resource_types(new_dir)}

    for rt in sorted(resource_types):
        new_by_id = load_ndjson_by_id(new_dir / f"{rt}.ndjson")
        old_by_id = load_ndjson_by_id(old_dir / f"{rt}.ndjson")

        new_only, updated, _unchanged = classify_resources(old_by_id, new_by_id)

        for r in new_only:
            entries.append({
                "resource": r,
                "request": {"method": "POST", "url": rt},
            })
        for r in updated:
            entries.append({
                "resource": r,
                "request": {"method": "PUT", "url": f"{rt}/{r['id']}"},
            })

    return {
        "resourceType": "Bundle",
        "id": bundle_id,
        "meta": {"lastUpdated": last_updated},
        "type": "transaction",
        "entry": entries,
    }


def format_summary(bundle: dict, old_cursor: str, new_cursor: str) -> str:
    """Bundle transaction の human-readable summary を返す。

    Args:
        bundle: FHIR R4 Bundle resource (transaction type)。
        old_cursor: 前 snapshot の cursor (表示用)。
        new_cursor: 現 snapshot の cursor (表示用)。

    Returns:
        Resource type ごとに new / modified を集計した summary text。
    """
    entries = bundle.get("entry", [])
    new_count: Counter[str] = Counter()
    updated_count: Counter[str] = Counter()
    for e in entries:
        rt = e["resource"].get("resourceType", "?")
        method = e["request"]["method"]
        if method == "POST":
            new_count[rt] += 1
        elif method == "PUT":
            updated_count[rt] += 1

    lines = [f"Diff {old_cursor} → {new_cursor}", ""]

    if new_count:
        lines.append("New resources:")
        for rt in sorted(new_count):
            lines.append(f"  {rt:26} : {new_count[rt]}")
        lines.append("")

    if updated_count:
        lines.append("Modified resources:")
        for rt in sorted(updated_count):
            lines.append(f"  {rt:26} : {updated_count[rt]}")
        lines.append("")

    lines.append(f"Total bundle size: {len(entries)} entries")
    return "\n".join(lines)
