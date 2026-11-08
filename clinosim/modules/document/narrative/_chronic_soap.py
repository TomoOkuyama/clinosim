"""Chronic-disease outpatient SOAP template resolver (v9 density fix).

The 32 disease YAMLs under ``modules/disease/reference_data/`` cover
acute inpatient conditions only. Chronic diseases (hypertension,
diabetes, CKD, etc.) appear in the simulator solely as ICD-10 codes on
``patient.chronic_conditions``. The v10 density audit found ~35 % of
outpatient encounters were chronic-follow-up visits with no matching
encounter or disease template — falling through to a raw fallback.

This module reads
``clinosim/modules/document/reference_data/chronic_soap_templates.yaml``
and returns an OutpatientSoapTemplate-shaped dict when the patient's
primary chronic condition matches a registry entry, so
``_get_soap_template()`` can slot it into its existing resolution chain
(encounter → disease → chronic → engine).
"""

from __future__ import annotations

from typing import Any

from clinosim.modules.document.reference_data_loaders import load_document_data_yaml

_REGISTRY_FILENAME = "chronic_soap_templates.yaml"


def resolve_chronic_soap(chronic_conditions: list[Any] | None) -> dict[str, str] | None:
    """Return the SOAP template for the first-matching chronic condition,
    or None when no chronic condition matches a registry entry.

    Args:
        chronic_conditions: The patient's chronic conditions list
            (``patient.chronic_conditions``). Each item may be a
            PatientChronicCondition-like object with a ``code`` field
            or a plain ICD-10 string. Order is honored — first match wins.

    Returns:
        Dict with ``subjective`` / ``objective`` / ``assessment`` / ``plan``
        language maps, or ``None``.
    """
    if not chronic_conditions:
        return None
    registry = load_document_data_yaml(_REGISTRY_FILENAME)
    for c in chronic_conditions:
        code: str | None
        if isinstance(c, str):
            code = c
        else:
            code = getattr(c, "code", None) or (c.get("code") if isinstance(c, dict) else None)
        if not code:
            continue
        prefix = str(code).split(".")[0].upper()
        entry = registry.get(prefix)
        if entry:
            return dict(entry)
    return None
