"""display_name → imaging metadata inference (case D, session 48 cycle 8 拡張).

`place_imaging_orders()` 以外の call site(ED workflow / legacy admission /
treatment_mods / unknown_condition path)は Order.display_name のみ populate し
`imaging_modality` / `imaging_body_site_code` / `imaging_views` を空にする。
これらの Order が silent-drop されないよう、display_name から canonical
metadata を whitelist regex で推論する。

**方針**:
- **whitelist only, guess 禁止** — pattern match しない display_name は None を返し
  enricher 側で text-only stub を emit(silent-drop よりは意味を保つ)
- **JP + EN 両対応** — 命名規則が両言語混在の実 EHR に整合
- 返り値の body_site は body_sites.yaml の key、modality は modalities.yaml の
  DCM code(CR/CT/MR/US/NM/PT/XA など)
"""
from __future__ import annotations

import re
from typing import Optional

from clinosim.modules.imaging.engine import load_body_sites, load_modalities

# (regex, modality DCM code, body_site key, default views)
# body_site key は body_sites.yaml のキー(chest/head/abdomen/... 等)
# views は modalities.yaml default_views_by_body_site を上書き可能
_PATTERNS: list[tuple[str, str, str, list[str]]] = [
    # ---- CR / plain X-ray ----
    (r"chest[\s\-]*x[\s\-]*ray|chest[\s\-]*film|chest\s*cr|cxr",  "CR", "chest",  ["PA"]),
    (r"胸部\s*x[\s\-]*(?:線|ray|p)|胸部\s*単純\s*(?:x[\s\-]*(?:線|ray|p)|レ|レントゲン)|胸写|胸\s*x[\s\-]*p",  "CR", "chest",  ["PA"]),
    (r"abdomen\s*x[\s\-]*ray|abdominal\s*x[\s\-]*ray|kub|abd\s*x[\s\-]*ray", "CR", "abdomen", ["AP"]),
    (r"腹部\s*x[\s\-]*(?:線|ray|p)|腹部\s*単純\s*(?:x|レ)",       "CR", "abdomen", ["AP"]),
    (r"hand\s*x[\s\-]*ray|hand\s*film",                           "CR", "hand",    ["PA"]),
    (r"手\s*(?:関節)?\s*x[\s\-]*(?:線|p)",                         "CR", "hand",    ["PA"]),
    (r"wrist\s*x[\s\-]*ray",                                       "CR", "wrist",   ["PA"]),
    (r"手関節\s*x[\s\-]*(?:線|p)",                                "CR", "wrist",   ["PA"]),
    (r"hip\s*x[\s\-]*ray",                                         "CR", "hip",     ["AP"]),
    (r"股関節\s*x[\s\-]*(?:線|p)",                                "CR", "hip",     ["AP"]),
    (r"leg\s*x[\s\-]*ray|lower\s+extremity\s*x[\s\-]*ray",         "CR", "leg",     ["AP"]),
    (r"下肢\s*x[\s\-]*(?:線|p)",                                  "CR", "leg",     ["AP"]),
    (r"spine\s*x[\s\-]*ray|lumbar\s*x[\s\-]*ray|cervical\s*x[\s\-]*ray", "CR", "spine", ["AP"]),
    (r"脊椎\s*x[\s\-]*(?:線|p)|(?:腰椎|頸椎|胸椎)\s*x[\s\-]*(?:線|p)", "CR", "spine", ["AP"]),

    # ---- CT ----
    (r"head\s*ct|brain\s*ct|cranial\s*ct|ct\s*head|ct\s*brain",   "CT", "head",    []),
    (r"頭部\s*ct|脳\s*ct",                                        "CT", "head",    []),
    (r"chest\s*ct|thoracic\s*ct|ct\s*chest|ct\s*thorax",           "CT", "chest",   []),
    (r"胸部\s*ct",                                                "CT", "chest",   []),
    (r"abdominal?\s*ct|ct\s*abdomen|ct\s*abd",                     "CT", "abdomen", []),
    (r"腹部\s*ct",                                                "CT", "abdomen", []),
    (r"kidney\s*ct|renal\s*ct",                                    "CT", "kidney",  []),
    (r"腎\s*ct|腎臓\s*ct",                                       "CT", "kidney",  []),

    # ---- MR ----
    (r"head\s*mri|brain\s*mri|cranial\s*mri|mri\s*head|mri\s*brain", "MR", "head",  []),
    (r"頭部\s*mri|脳\s*mri",                                     "MR", "head",    []),
    (r"spine\s*mri|lumbar\s*mri|cervical\s*mri|mri\s*spine",      "MR", "spine",  []),
    (r"脊椎\s*mri|(?:腰椎|頸椎|胸椎)\s*mri",                    "MR", "spine",  []),
    (r"abdominal?\s*mri|mri\s*abdomen",                             "MR", "abdomen",[]),
    (r"腹部\s*mri",                                              "MR", "abdomen",[]),

    # ---- US ----
    (r"abdominal?\s*ultrasound|abdominal?\s*us|abdomen\s*sono",     "US", "abdomen",[]),
    (r"腹部\s*(?:超音波|エコー|us)",                              "US", "abdomen",[]),
    (r"kidney\s*us|renal\s*us|renal\s*ultrasound",                  "US", "kidney", []),
    (r"腎\s*(?:超音波|エコー|us)",                                "US", "kidney", []),
]


def infer_imaging_metadata(display_name: str) -> Optional[dict]:
    """display_name から (modality, body_site_snomed, views) を推論。

    見つからなければ ``None`` を返す(caller は text-only stub emit を選ぶ)。

    Returns
    -------
    dict | None
        ``{"modality": str, "body_site_snomed": str, "views": list[str]}``
        いずれかの key が空 str/list なら partial match(caller 責任で判断)。
    """
    if not display_name:
        return None
    txt = display_name.strip().lower()
    body_sites = load_body_sites()
    modalities = load_modalities()

    for pattern, modality, body_key, views in _PATTERNS:
        if re.search(pattern, txt, flags=re.IGNORECASE):
            bs = body_sites.get(body_key)
            if not bs:
                continue  # body_sites.yaml に無い key = ロード時に validation 失敗しているはず
            snomed = bs.get("snomed", "")
            if not snomed:
                continue
            # views が空なら modalities の default で補完
            if not views:
                default_views = (modalities.get(modality, {}) or {}).get(
                    "default_views_by_body_site", {}
                ).get(body_key, [])
                views = list(default_views)
            return {
                "modality": modality,
                "body_site_snomed": snomed,
                "body_site_key": body_key,
                "views": list(views),
            }
    return None
