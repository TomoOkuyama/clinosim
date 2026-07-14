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

from clinosim.modules.imaging.engine import load_body_sites, load_modalities

# (regex, modality DCM code, body_site key, default views)
# body_site key は body_sites.yaml のキー(chest/head/abdomen/... 等)
# views は modalities.yaml default_views_by_body_site を上書き可能
# 区切りは space / hyphen / underscore すべて許容(_ は inpatient/emergency
# simulator が Chest_Xray_PA 形式で order を作るため)。
_SEP = r"[\s\-_]*"  # 区切り任意
_PATTERNS: list[tuple[str, str, str, list[str]]] = [
    # ---- CR / plain X-ray ----
    (rf"chest{_SEP}x{_SEP}?ray(?:{_SEP}pa{_SEP}lateral)?{_SEP}(?:pa|portable|lateral)?|chest{_SEP}film|chest{_SEP}cr|cxr",
     "CR", "chest",  ["PA"]),
    (rf"胸部{_SEP}x[\s\-_]*(?:線|ray|p)|胸部{_SEP}単純{_SEP}(?:x{_SEP}(?:線|ray|p)|レ|レントゲン)|胸写|胸{_SEP}x{_SEP}p",
     "CR", "chest",  ["PA"]),
    (rf"abdomen{_SEP}x{_SEP}?ray|abdominal{_SEP}x{_SEP}?ray|kub|abd{_SEP}x{_SEP}?ray|xray{_SEP}abdomen",
     "CR", "abdomen", ["AP"]),
    (rf"腹部{_SEP}x{_SEP}(?:線|ray|p)|腹部{_SEP}単純{_SEP}(?:x|レ)",
     "CR", "abdomen", ["AP"]),
    (rf"hand{_SEP}x{_SEP}?ray|hand{_SEP}film",                     "CR", "hand",    ["PA"]),
    (rf"手{_SEP}(?:関節)?{_SEP}x{_SEP}(?:線|p)",                   "CR", "hand",    ["PA"]),
    (rf"wrist{_SEP}x{_SEP}?ray(?:{_SEP}ap)?(?:{_SEP}lateral)?",   "CR", "wrist",   ["AP"]),
    (rf"手関節{_SEP}x{_SEP}(?:線|p)",                             "CR", "wrist",   ["AP"]),
    (rf"hip{_SEP}x{_SEP}?ray",                                     "CR", "hip",     ["AP"]),
    (rf"股関節{_SEP}x{_SEP}(?:線|p)",                             "CR", "hip",     ["AP"]),
    (rf"leg{_SEP}x{_SEP}?ray|lower{_SEP}extremity{_SEP}x{_SEP}?ray",
     "CR", "leg",     ["AP"]),
    (rf"下肢{_SEP}x{_SEP}(?:線|p)",                               "CR", "leg",     ["AP"]),
    # ankle / knee / foot / shoulder は leg 相当(下肢 or 骨・軟部)に集約
    # (専用 body_site 未定義、CIF-VS-FHIR-01 fix scope 外)
    (rf"ankle{_SEP}x{_SEP}?ray|foot{_SEP}x{_SEP}?ray|knee{_SEP}x{_SEP}?ray",
     "CR", "leg",     ["AP"]),
    (rf"shoulder{_SEP}x{_SEP}?ray(?:{_SEP}ap)?(?:{_SEP}lateral)?(?:{_SEP}post{_SEP}reduction)?",
     "CR", "hand",    ["AP"]),  # 上肢 body_site 未定義、hand を暫定用
    (rf"spine{_SEP}x{_SEP}?ray|(?:lumbar|cervical|thoracic){_SEP}(?:spine{_SEP})?x{_SEP}?ray",
     "CR", "spine",   ["AP"]),
    (rf"脊椎{_SEP}x{_SEP}(?:線|p)|(?:腰椎|頸椎|胸椎){_SEP}x{_SEP}(?:線|p)",
     "CR", "spine",   ["AP"]),
    # freetext fallback: "Xray Affected Area" 等 → chest 暫定
    (rf"xray{_SEP}affected{_SEP}area",                             "CR", "chest",   ["AP"]),

    # ---- CT ----
    (rf"(?:head|brain|cranial){_SEP}ct|ct{_SEP}(?:head|brain)(?:{_SEP}noncontrast|{_SEP}stat)?",
     "CT", "head",    []),
    (rf"頭部{_SEP}ct|脳{_SEP}ct",                                "CT", "head",    []),
    (rf"(?:chest|thoracic){_SEP}ct|ct{_SEP}(?:chest|thorax)",     "CT", "chest",   []),
    (rf"胸部{_SEP}ct",                                            "CT", "chest",   []),
    (rf"abdominal?{_SEP}ct|ct{_SEP}(?:abdomen|abd)(?:{_SEP}pelvis)?(?:{_SEP}(?:with|no)n?{_SEP}?contrast)?",
     "CT", "abdomen", []),
    (rf"腹部{_SEP}ct",                                            "CT", "abdomen", []),
    (rf"(?:kidney|renal){_SEP}ct",                                 "CT", "kidney",  []),
    (rf"腎{_SEP}ct|腎臓{_SEP}ct",                                "CT", "kidney",  []),
    # CT angiography — head/neck に routed
    (rf"ct{_SEP}angiography{_SEP}head{_SEP}neck",                  "CT", "head",    []),

    # ---- MR / MRA ----
    (rf"(?:head|brain|cranial){_SEP}mri|mri{_SEP}(?:head|brain)(?:{_SEP}dwi)?",
     "MR", "head",    []),
    (rf"mra{_SEP}intracranial",                                    "MR", "head",    []),
    (rf"頭部{_SEP}mri|脳{_SEP}mri",                              "MR", "head",    []),
    (rf"spine{_SEP}mri|(?:lumbar|cervical){_SEP}mri|mri{_SEP}spine",
     "MR", "spine",   []),
    (rf"脊椎{_SEP}mri|(?:腰椎|頸椎|胸椎){_SEP}mri",              "MR", "spine",   []),
    (rf"abdominal?{_SEP}mri|mri{_SEP}abdomen",                     "MR", "abdomen", []),
    (rf"腹部{_SEP}mri",                                          "MR", "abdomen", []),

    # ---- US ----
    (rf"abdominal?{_SEP}(?:ultrasound|us|sono)|abdomen{_SEP}sono", "US", "abdomen", []),
    (rf"腹部{_SEP}(?:超音波|エコー|us)",                          "US", "abdomen", []),
    (rf"(?:kidney|renal){_SEP}(?:ultrasound|us)",                  "US", "kidney",  []),
    (rf"腎{_SEP}(?:超音波|エコー|us)",                            "US", "kidney",  []),
    # Carotid → 頸部血管、body_site 未定義のため spine に集約(頸部 spine 相当)
    (rf"carotid{_SEP}(?:ultrasound|us)",                           "US", "spine",   []),
    # Echocardiogram(TTE)は心臓 US → heart body_site 未定義のため chest に集約
    (rf"echocardiog(?:ram|raphy)(?:{_SEP}(?:tte|complete|bedside))?", "US", "chest", []),
    # 下肢静脈エコー(DVT workup)— US leg は doppler views 登録済
    (rf"lower{_SEP}extremity{_SEP}venous{_SEP}(?:ultrasound|us)|下肢{_SEP}静脈{_SEP}(?:超音波|エコー)",
     "US", "leg",     []),

    # ---- XA / angiography(session 52 fix 4)----
    # 冠動脈造影 → XA。heart body_site 未定義のため chest に集約(echo と同精度)
    (rf"coronary{_SEP}angio(?:graphy|gram)|冠動脈{_SEP}造影",     "XA", "chest",   []),
    # CT pulmonary angiography(PE workup)は CT + chest
    (rf"ct{_SEP}pulmonary{_SEP}angio(?:graphy|gram)|ctpa|肺動脈{_SEP}ct",
     "CT", "chest",   []),

    # ---- ECG(session 52 fix 4)----
    # ED / cardiac workup が OrderType.IMAGING で発行する心電図 order。
    # DICOM waveform modality "ECG"、body_site は chest 集約(echo と同精度)。
    # \b は "_" を境界と見なさないため anchored 形("ECG" / "ECG_12lead" /
    # "ECG_12lead_stat" 等、ecg/ekg で始まる display name 全般)
    (r"^(?:ecg|ekg)(?:[\s\-_].*)?$|心電図",
     "ECG", "chest",  []),
]


def infer_imaging_metadata(display_name: str) -> dict | None:
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
