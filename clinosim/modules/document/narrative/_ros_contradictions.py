"""Record rules that contradict a ROS pertinent negative (Issue #3391).

``hpi_pertinent_negatives.yaml`` lists, per negative, the rules it is
``contradicted_by``; a negative one of whose rules holds for the encounter is
left out of the ROS ("no head strike" next to a head CT that shows a
contusion). The rules are evaluated here; which negative uses which rule is
data. History is a fact of the encounter, so every imaging study of the
encounter counts, not only the reads signed before the note.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o

__all__ = ["RULES", "contradicted"]

#: Modalities of a head study that reads brain injury (DICOM codes).
#: A GCS total below this is impaired consciousness (a fully alert patient scores the scale's maximum).
_GCS_ALERT = 15

_HEAD_MODALITIES = ("CT", "MR")


def _disease_id(ctx: Any) -> str:
    protocol = getattr(ctx, "disease_protocol", None)
    return str(_o(protocol, "disease_id", "") or "") or str(getattr(ctx, "principal_disease_id", "") or "")


def head_imaging_abnormal(ctx: Any) -> bool:
    """A head CT/MRI of the encounter whose impression is an abnormal read
    (a study of an unknown read does not count)."""
    from clinosim.modules.imaging.engine import imaging_report_is_abnormal, load_body_sites

    disease_id = _disease_id(ctx)
    head_snomed = (load_body_sites().get("head") or {}).get("snomed")
    if not disease_id or not head_snomed:
        return False
    for study in getattr(ctx, "imaging_studies", None) or []:
        modality = str(_o(study, "modality_code", "") or "")
        if modality not in _HEAD_MODALITIES or str(_o(study, "body_site_snomed", "") or "") != head_snomed:
            continue
        report = _o(study, "report", None) or {}
        impressions = tuple(str(_o(report, k, "") or "") for k in ("impression_text", "impression_text_ja"))
        if imaging_report_is_abnormal(disease_id, modality, head_snomed, impressions):
            return True
    return False


def consciousness_impaired(ctx: Any) -> bool:
    """The arrival reading (``ctx.vitals[0]``) is below Alert on AVPU or has a
    GCS below 15."""
    vitals = getattr(ctx, "vitals", None) or []
    if not vitals:
        return False
    arrival = vitals[0]
    avpu = str(_o(arrival, "consciousness_level", "") or "")
    gcs = _o(arrival, "gcs_score", None)
    return (avpu not in ("", "A")) or (isinstance(gcs, int) and gcs < _GCS_ALERT)


RULES: dict[str, Callable[[Any], bool]] = {
    "head_imaging_abnormal": head_imaging_abnormal,
    "consciousness_impaired": consciousness_impaired,
}


def contradicted(rules: tuple[str, ...], ctx: Any) -> bool:
    """Whether any of ``rules`` holds for the encounter of ``ctx``."""
    return any(RULES[r](ctx) for r in rules)
