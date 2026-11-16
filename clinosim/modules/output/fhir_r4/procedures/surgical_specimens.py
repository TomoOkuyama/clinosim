"""FHIR R4 Specimen for the tissue a procedure sends to pathology (Issue #3284).

A resection records its specimens in ``ProcedureRecord.specimens_sent``
(``specimen_type`` keys: ``appendix``, ``gallbladder``, ``colon_segment``).
Each entry becomes one Specimen:

- ``type``: the SNOMED CT specimen concept (English display in the coding, the
  clinical label in ``text``, dual slot);
- ``collection.collectedDateTime``: the end of the procedure (the organ leaves
  the field when the resection is complete), else its start;
- ``collection.bodySite``: the procedure's body site;
- ``collection.collector``: the operating surgeon;
- ``collection.extension``: a reference to the Procedure that collected it.
  FHIR R4 Specimen has no element for that; R5 added
  ``Specimen.collection.procedure``, and the R4 representation of an R5
  element is its cross-version extension.

Ids follow the shared Specimen resolver (``spec-<12hex>``) with the structural
key ``<procedure structural key>-specimen-<n>``.
"""

from __future__ import annotations

import copy
from typing import Any

from clinosim.codes.procedures import specimen_code, specimen_label
from clinosim.countries import lang_for
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.fhir_time import to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import wrap_as_identifier
from clinosim.modules.output.fhir_r4.post_process.specimen import SPECIMEN_KEY_SYSTEM, _resolve_specimen_id
from clinosim.modules.output.fhir_r4.procedures.procedures import _resolve_procedure_id, procedure_structural_key

# R5 ``Specimen.collection.procedure`` (Reference(Procedure)) carried in R4 as
# its cross-version extension.
PROCEDURE_REFERENCE_EXTENSION = "http://hl7.org/fhir/5.0/StructureDefinition/extension-Specimen.collection.procedure"


def _bb_procedure_specimens(ctx: BundleContext) -> list[dict]:
    """One Specimen per ``specimens_sent`` entry of every CIF procedure."""
    lang = lang_for(ctx.country)
    out: list[dict] = []
    for index, proc in enumerate(ctx.record.get("procedures", []) or []):
        slugs = [str(s) for s in (proc.get("specimens_sent") or []) if s]
        if not slugs:
            continue
        proc_key = procedure_structural_key(proc, ctx.patient_id, index)
        collection: dict[str, Any] = {
            "extension": [
                {
                    "url": PROCEDURE_REFERENCE_EXTENSION,
                    "valueReference": {"reference": f"Procedure/{_resolve_procedure_id(proc_key)}"},
                }
            ]
        }
        surgeon_id = proc.get("primary_surgeon_id", "")
        if surgeon_id:
            collection["collector"] = {"reference": f"Practitioner/{surgeon_id}"}
        collected = to_fhir_datetime(proc.get("end_datetime", "")) or to_fhir_datetime(proc.get("start_datetime", ""))
        if collected:
            collection["collectedDateTime"] = collected
        body_site_code = proc.get("body_site_code", "")
        if body_site_code:
            collection["bodySite"] = dual_slot_concept("snomed-ct", body_site_code, lang)
        for n, slug in enumerate(slugs):
            code = specimen_code(slug)
            if not code:
                continue
            key = f"{proc_key}-specimen-{n}"
            out.append(
                {
                    "resourceType": "Specimen",
                    "id": _resolve_specimen_id(key),
                    "identifier": [wrap_as_identifier(key, SPECIMEN_KEY_SYSTEM)],
                    "status": "available",
                    "type": dual_slot_concept("snomed-ct", code, lang, text=specimen_label(slug, lang)),
                    "subject": patient_ref(ctx.patient_id),
                    "collection": copy.deepcopy(collection),
                }
            )
    return out
