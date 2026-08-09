"""``display_name`` → imaging-metadata inference (case D).

Call sites other than ``place_imaging_orders()`` (ED workflow, legacy
admission, ``treatment_mods``, ``unknown_condition`` path) populate
only ``Order.display_name`` and leave ``imaging_modality`` /
``imaging_body_site_code`` / ``imaging_views`` empty. To prevent those
orders from silent-dropping, this module infers canonical metadata
from ``display_name`` using a whitelist of regex patterns.

**Policy**:

- **Whitelist only — no guessing.** If no pattern matches, return
  ``None``; the enricher then emits a text-only stub, which preserves
  meaning better than a silent drop.
- **JP + EN both accepted** — real-world EHRs mix the two naming
  conventions.
- The ``body_site`` in the return value is a key from
  ``body_sites.yaml``; the ``modality`` is the DCM code from
  ``modalities.yaml`` (``CR`` / ``CT`` / ``MR`` / ``US`` / ``NM`` /
  ``PT`` / ``XA`` and so on).
"""

from __future__ import annotations

import re

from clinosim.modules.imaging.engine import load_body_sites, load_modalities

# Tuple layout: ``(regex, modality DCM code, body_site key, default views)``.
# ``body_site`` key is a key of ``body_sites.yaml`` (``chest`` / ``head``
# / ``abdomen`` / ...). ``views`` overrides
# ``modalities.yaml.default_views_by_body_site``. Separators accept
# space / hyphen / underscore (underscore because the inpatient +
# emergency simulator builds orders in the ``Chest_Xray_PA`` form).
_SEP = r"[\s\-_]*"  # Separator (any)
_PATTERNS: list[tuple[str, str, str, list[str]]] = [
    # ---- CR / plain X-ray ----
    (
        rf"chest{_SEP}x{_SEP}?ray(?:{_SEP}pa{_SEP}lateral)?{_SEP}(?:pa|portable|lateral)?|chest{_SEP}film|chest{_SEP}cr|cxr",
        "CR",
        "chest",
        ["PA"],
    ),
    (
        rf"胸部{_SEP}x[\s\-_]*(?:線|ray|p)|胸部{_SEP}単純{_SEP}(?:x{_SEP}(?:線|ray|p)|レ|レントゲン)|胸写|胸{_SEP}x{_SEP}p",
        "CR",
        "chest",
        ["PA"],
    ),
    (
        rf"abdomen{_SEP}x{_SEP}?ray|abdominal{_SEP}x{_SEP}?ray|kub|abd{_SEP}x{_SEP}?ray|xray{_SEP}abdomen",
        "CR",
        "abdomen",
        ["AP"],
    ),
    (rf"腹部{_SEP}x{_SEP}(?:線|ray|p)|腹部{_SEP}単純{_SEP}(?:x|レ)", "CR", "abdomen", ["AP"]),
    (rf"hand{_SEP}x{_SEP}?ray|hand{_SEP}film", "CR", "hand", ["PA"]),
    (rf"手{_SEP}(?:関節)?{_SEP}x{_SEP}(?:線|p)", "CR", "hand", ["PA"]),
    (rf"wrist{_SEP}x{_SEP}?ray(?:{_SEP}ap)?(?:{_SEP}lateral)?", "CR", "wrist", ["AP"]),
    (rf"手関節{_SEP}x{_SEP}(?:線|p)", "CR", "wrist", ["AP"]),
    (rf"hip{_SEP}x{_SEP}?ray", "CR", "hip", ["AP"]),
    (rf"股関節{_SEP}x{_SEP}(?:線|p)", "CR", "hip", ["AP"]),
    (rf"leg{_SEP}x{_SEP}?ray|lower{_SEP}extremity{_SEP}x{_SEP}?ray", "CR", "leg", ["AP"]),
    (rf"下肢{_SEP}x{_SEP}(?:線|p)", "CR", "leg", ["AP"]),
    # ankle / knee / foot / shoulder are folded into ``leg`` (i.e.
    # 下肢 / 骨・軟部). No dedicated body_site is defined yet — that
    # is out of scope for the current CIF-VS-FHIR-01 fix.
    (rf"ankle{_SEP}x{_SEP}?ray|foot{_SEP}x{_SEP}?ray|knee{_SEP}x{_SEP}?ray", "CR", "leg", ["AP"]),
    (
        rf"shoulder{_SEP}x{_SEP}?ray(?:{_SEP}ap)?(?:{_SEP}lateral)?(?:{_SEP}post{_SEP}reduction)?",
        "CR",
        "hand",
        ["AP"],
    ),  # No upper-limb (上肢) body_site defined yet — folded into ``hand`` provisionally.
    (rf"spine{_SEP}x{_SEP}?ray|(?:lumbar|cervical|thoracic){_SEP}(?:spine{_SEP})?x{_SEP}?ray", "CR", "spine", ["AP"]),
    (rf"脊椎{_SEP}x{_SEP}(?:線|p)|(?:腰椎|頸椎|胸椎){_SEP}x{_SEP}(?:線|p)", "CR", "spine", ["AP"]),
    # Freetext fallback: "Xray Affected Area" and similar map to chest provisionally.
    (rf"xray{_SEP}affected{_SEP}area", "CR", "chest", ["AP"]),
    # ---- CT ----
    (rf"(?:head|brain|cranial){_SEP}ct|ct{_SEP}(?:head|brain)(?:{_SEP}noncontrast|{_SEP}stat)?", "CT", "head", []),
    (rf"頭部{_SEP}ct|脳{_SEP}ct", "CT", "head", []),
    (rf"(?:chest|thoracic){_SEP}ct|ct{_SEP}(?:chest|thorax)", "CT", "chest", []),
    (rf"胸部{_SEP}ct", "CT", "chest", []),
    (
        rf"abdominal?{_SEP}ct|ct{_SEP}(?:abdomen|abd)(?:{_SEP}pelvis)?(?:{_SEP}(?:with|no)n?{_SEP}?contrast)?",
        "CT",
        "abdomen",
        [],
    ),
    (rf"腹部{_SEP}ct", "CT", "abdomen", []),
    (rf"(?:kidney|renal){_SEP}ct", "CT", "kidney", []),
    (rf"腎{_SEP}ct|腎臓{_SEP}ct", "CT", "kidney", []),
    # CT angiography — head/neck に routed
    (rf"ct{_SEP}angiography{_SEP}head{_SEP}neck", "CT", "head", []),
    # ---- MR / MRA ----
    (rf"(?:head|brain|cranial){_SEP}mri|mri{_SEP}(?:head|brain)(?:{_SEP}dwi)?", "MR", "head", []),
    (rf"mra{_SEP}intracranial", "MR", "head", []),
    (rf"頭部{_SEP}mri|脳{_SEP}mri", "MR", "head", []),
    (rf"spine{_SEP}mri|(?:lumbar|cervical){_SEP}mri|mri{_SEP}spine", "MR", "spine", []),
    (rf"脊椎{_SEP}mri|(?:腰椎|頸椎|胸椎){_SEP}mri", "MR", "spine", []),
    (rf"abdominal?{_SEP}mri|mri{_SEP}abdomen", "MR", "abdomen", []),
    (rf"腹部{_SEP}mri", "MR", "abdomen", []),
    # ---- US ----
    (rf"abdominal?{_SEP}(?:ultrasound|us|sono)|abdomen{_SEP}sono", "US", "abdomen", []),
    (rf"腹部{_SEP}(?:超音波|エコー|us)", "US", "abdomen", []),
    (rf"(?:kidney|renal){_SEP}(?:ultrasound|us)", "US", "kidney", []),
    (rf"腎{_SEP}(?:超音波|エコー|us)", "US", "kidney", []),
    # Carotid → cervical vasculature; folded into ``spine`` because no
    # dedicated body_site exists for it (cervical spine is the closest match).
    (rf"carotid{_SEP}(?:ultrasound|us)", "US", "spine", []),
    # Echocardiogram (TTE) is a cardiac US. Folded into ``chest``
    # because no ``heart`` body_site is defined.
    (rf"echocardiog(?:ram|raphy)(?:{_SEP}(?:tte|complete|bedside))?", "US", "chest", []),
    # Lower-extremity venous US (DVT workup); ``US`` + ``leg`` has
    # Doppler views registered.
    (
        rf"lower{_SEP}extremity{_SEP}venous{_SEP}(?:ultrasound|us)|下肢{_SEP}静脈{_SEP}(?:超音波|エコー)",
        "US",
        "leg",
        [],
    ),
    # ---- XA / angiography ----
    # Coronary angiography → XA. Folded into ``chest`` (same precision
    # as the echocardiogram folding) because no ``heart`` body_site is defined.
    (rf"coronary{_SEP}angio(?:graphy|gram)|冠動脈{_SEP}造影", "XA", "chest", []),
    # CT pulmonary angiography (PE workup) → CT + chest.
    (rf"ct{_SEP}pulmonary{_SEP}angio(?:graphy|gram)|ctpa|肺動脈{_SEP}ct", "CT", "chest", []),
    # ---- ECG ----
    # Electrocardiogram orders that the ED / cardiac workup places via
    # ``OrderType.IMAGING``. DICOM waveform modality ``ECG``; the
    # body_site is folded into ``chest`` (same precision as echo). The
    # anchored regex form matches any display_name that starts with
    # ``ecg`` or ``ekg`` (e.g. ``ECG`` / ``ECG_12lead`` /
    # ``ECG_12lead_stat``) because ``\b`` does not treat ``_`` as a
    # boundary.
    (r"^(?:ecg|ekg)(?:[\s\-_].*)?$|心電図", "ECG", "chest", []),
]


def infer_imaging_metadata(display_name: str) -> dict | None:
    """Infer ``(modality, body_site_snomed, views)`` from ``display_name``.

    Returns ``None`` when no whitelist entry matches, in which case the
    caller emits a text-only stub instead.

    Returns:
        A dict of the shape
        ``{"modality": str, "body_site_snomed": str, "views": list[str]}``,
        or ``None``. An empty string / empty list in one of the keys
        indicates a partial match; the caller decides what to do with
        it.
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
                continue  # Key missing from body_sites.yaml — should have failed at load-time validation.
            snomed = bs.get("snomed", "")
            if not snomed:
                continue
            # Fall back to the modality's default views when none supplied.
            if not views:
                default_views = (
                    (modalities.get(modality, {}) or {}).get("default_views_by_body_site", {}).get(body_key, [])
                )
                views = list(default_views)
            return {
                "modality": modality,
                "body_site_snomed": snomed,
                "body_site_key": body_key,
                "views": list(views),
            }
    return None
