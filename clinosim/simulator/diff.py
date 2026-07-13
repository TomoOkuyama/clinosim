"""FHIR snapshot diff — 2 snapshot output の差分を FHIR Bundle transaction に変換 (F3, session 49)。

Approach C の operational cover。clinosim 自身は決定的な snapshot generator に留まり、
「cursor 移動した差分だけを FHIR server に POST する」用の Bundle 生成をここで行う。
push は user 側 tool (curl / httpx / hapi-fhir-cli) に委ねる。
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

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
