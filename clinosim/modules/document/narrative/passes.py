"""NarrativePass base + TemplateNarrativePass (AD-65 Stage 2 workhorse).

Reads structural CIF, builds per-encounter NarrativeContext, runs the
generator, writes cif/narratives/<version>/documents/<enc>/<doc_type>.json.

Walk order contract: (doc_type, language) group serial — β-JP-1
LLMNarrativePass inherits this base and gains Bedrock prompt cache
friendliness automatically.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from clinosim.modules.document import specs_for_country
from clinosim.modules.document.narrative.fact_extractor import extract_all_facts
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.scenario_spine import build_narrative_spine
from clinosim.modules.document.narrative.section_extractor import extract_for_composition
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.clinical import (
    ClinicalDocumentNarrative,
    NarrativeVersionManifest,
)
from clinosim.types.document import NarrativeContext, NarrativeOutput


class NarrativePass(ABC):
    """Stage 2 base class: read structural CIF → write narrative-tree CIF.

    Walk order is (spec, language, patient) — β-JP-1 LLMNarrativePass groups
    by (doc_type, language) to maximize Bedrock prompt cache hits.
    """

    def __init__(
        self,
        cif_dir: str,
        version_id: str,
        country: str,
        tasks: list[str] | None = None,
        rng_seed: int = 42,
    ):
        self.cif_dir = cif_dir
        self.version_id = version_id
        self.country = country
        self.tasks_filter = set(tasks) if tasks else None
        self.rng_seed = rng_seed

    def run(self) -> NarrativeVersionManifest:
        specs = specs_for_country(self.country)
        if self.tasks_filter:
            specs = [s for s in specs if s.type_key in self.tasks_filter]

        structural_dir = os.path.join(self.cif_dir, "structural", "patients")
        narrative_dir = os.path.join(self.cif_dir, "narratives", self.version_id, "documents")
        os.makedirs(narrative_dir, exist_ok=True)

        doc_counts: dict[str, int] = {}
        languages_used: set[str] = set()
        encounters_touched: set[str] = set()

        # ★ Bedrock cache walk order: (doc_type, language) group serial
        patient_files = sorted(f for f in os.listdir(structural_dir) if f.endswith(".json"))
        for spec in specs:
            for language in self._languages_for_spec(spec):
                for pf in patient_files:
                    with open(os.path.join(structural_dir, pf)) as f:
                        patient_dict = json.load(f)
                    if not self._spec_applies(spec, patient_dict):
                        continue
                    encounter_dict = (patient_dict.get("encounters") or [{}])[0]
                    stubs = self._find_matching_stubs(patient_dict, spec)
                    if not stubs:
                        continue
                    ctx = self._build_context(patient_dict, encounter_dict, spec, language)
                    encounter_id = encounter_dict.get("encounter_id", "")
                    for stub in stubs:
                        output = self._generate(ctx, spec)
                        wrapper = self._output_to_wrapper(
                            output, generator=self._generator_name()
                        )
                        self._write(narrative_dir, encounter_id, stub, wrapper, spec)
                        doc_counts[spec.type_key] = doc_counts.get(spec.type_key, 0) + 1
                        languages_used.add(language)
                        encounters_touched.add(encounter_id)

        manifest = NarrativeVersionManifest(
            version_id=self.version_id,
            generator=self._generator_name(),
            generator_config=self._generator_config(),
            generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            encounter_count=len(encounters_touched),
            document_count=sum(doc_counts.values()),
            document_counts_by_type=doc_counts,
            doc_types_enabled=sorted(doc_counts.keys()),
            languages_used=sorted(languages_used),
            llm_cost_report={},
        )
        manifest_path = os.path.join(self.cif_dir, "narratives", self.version_id, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(asdict(manifest), f, indent=2, ensure_ascii=False)
        return manifest

    @abstractmethod
    def _generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput: ...

    @abstractmethod
    def _generator_name(self) -> str: ...

    def _generator_config(self) -> dict[str, Any]:
        return {}

    def _languages_for_spec(self, spec: DocumentTypeSpec) -> list[str]:
        # US → en, JP → ja. β-JP-1 で bilingual 可能に拡張。
        return ["ja"] if self.country == "JP" else ["en"]

    def _spec_applies(self, spec: DocumentTypeSpec, patient_dict: dict[str, Any]) -> bool:
        allowed = getattr(spec, "encounter_types_supported", ()) or ()
        if not allowed:
            return True
        raw = (patient_dict.get("encounters") or [{}])[0].get("encounter_type", "") or ""
        # write_cif serializes EncounterType as a plain string ("inpatient");
        # some test fixtures use the pre-serialization enum shape {"value": "inpatient"}.
        enc_type = raw.get("value", "") if isinstance(raw, dict) else raw
        return enc_type in allowed

    def _build_context(
        self,
        patient_dict: dict[str, Any],
        encounter_dict: dict[str, Any],
        spec: DocumentTypeSpec,
        language: str,
    ) -> NarrativeContext:
        from clinosim.modules.document import DocumentType

        ctx = NarrativeContext(
            patient=patient_dict.get("patient"),
            encounter=encounter_dict,
            encounter_type=None,
            disease_protocol=None,
            encounter_protocol=None,
            clinical_course_archetype=patient_dict.get("clinical_course_archetype", ""),
            severity=patient_dict.get("severity", ""),
            day_index=0,
            los_days=0,
            vitals=patient_dict.get("vitals", []),
            lab_results=patient_dict.get("lab_results", []),
            medications=patient_dict.get("medications", []),
            diagnoses=patient_dict.get("diagnoses", []),
            procedures=patient_dict.get("procedures", []),
            allergies=patient_dict.get("allergies", []),
            document_type=DocumentType(spec.type_key),
            target_lang=language,
            locale="jp" if self.country == "JP" else "us",
        )
        ctx.narrative_spine = build_narrative_spine(
            None,
            None,
            ctx.clinical_course_archetype,
        )
        ctx.materialized_facts = extract_all_facts(patient_dict, encounter_dict, ctx)
        if spec.format_type.value == "composition":
            ctx.section_facts = extract_for_composition(ctx, spec)
        return ctx

    def _find_matching_stubs(
        self, patient_dict: dict[str, Any], spec: DocumentTypeSpec
    ) -> list[dict[str, Any]]:
        """Return ALL stubs matching ``spec.type_key``, in document-list order.

        A single encounter can carry multiple stubs with the same
        ``task_type`` (e.g. ``progress_note`` × ``los_days`` for a
        multi-day inpatient stay — see ``document_enricher``'s ``daily``
        branch in ``engine.py``). Returning only the first match silently
        drops every subsequent day's narrative (PR-90 class silent-no-op).
        """
        docs: list[dict[str, Any]] = patient_dict.get("documents", []) or []
        return [doc for doc in docs if doc.get("task_type") == spec.type_key]

    def _deterministic_timestamp(self) -> str:
        """Deterministic per-document ``generated_at`` (AD-16).

        Real narrative generation runs happen at varying wall-clock times, but
        the byte-diff / regression contract (``test_template_pass_deterministic``)
        requires identical output for identical (structural CIF, version_id,
        rng_seed) inputs. Per-document timestamps are therefore derived from
        ``rng_seed`` rather than ``datetime.utcnow()``. This mirrors the existing
        codebase convention where wall-clock provenance is reserved for
        manifest-level fields only (e.g. ``fhir_r4_adapter.py``'s
        ``transactionTime`` — see manifest.json's ``generated_at`` below, which
        intentionally keeps wall-clock semantics since it is not byte-diffed).
        """
        base = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(seconds=self.rng_seed)
        return base.isoformat().replace("+00:00", "Z")

    def _output_to_wrapper(
        self, output: NarrativeOutput, generator: str
    ) -> ClinicalDocumentNarrative:
        return ClinicalDocumentNarrative(
            text=output.raw_text,
            sections=output.sections,
            structured=output.structured,
            generator=generator,
            generator_metadata=output.metadata,
            generated_at=self._deterministic_timestamp(),
            facts_used=output.facts_used,
        )

    def _write(
        self,
        narrative_dir: str,
        encounter_id: str,
        stub: dict[str, Any],
        wrapper: ClinicalDocumentNarrative,
        spec: DocumentTypeSpec,
    ) -> None:
        enc_dir = os.path.join(narrative_dir, encounter_id)
        os.makedirs(enc_dir, exist_ok=True)
        filename = self._filename_for(stub, spec)
        payload = {
            "document_id": stub["document_id"],
            "encounter_id": encounter_id,
            "narrative": asdict(wrapper),
        }
        with open(os.path.join(enc_dir, filename), "w") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def _filename_for(self, stub: dict[str, Any], spec: DocumentTypeSpec) -> str:
        """Filename keyed by ``document_id`` (unique per stub).

        Keying by ``task_type`` alone silently overwrites every stub past the
        first when an encounter carries N stubs of the same task_type (e.g.
        ``progress_note`` on a multi-day inpatient stay). ``document_id`` is
        unique per stub (e.g. ``doc-ENC-1-progress_note-day-1``) and is
        already filesystem-safe (letters/digits/hyphens/underscores only).
        """
        return f"{stub.get('document_id', 'unknown')}.json"


class TemplateNarrativePass(NarrativePass):
    """Stage 2 default: template-based narrative pass (no LLM dependency)."""

    def __init__(
        self,
        cif_dir: str,
        version_id: str = "template",
        country: str = "US",
        tasks: list[str] | None = None,
        rng_seed: int = 42,
    ):
        super().__init__(cif_dir, version_id, country, tasks, rng_seed)
        self._rng = np.random.default_rng(rng_seed)
        self.generator = TemplateNarrativeGenerator()

    def _generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        return self.generator.generate(ctx, spec)

    def _generator_name(self) -> str:
        return "template"
