"""NarrativePass base + TemplateNarrativePass (AD-65 Stage 2 workhorse).

Reads structural CIF, builds per-encounter NarrativeContext, runs the
generator, writes cif/narratives/<version>/documents/<enc>/<doc_type>.json.

Walk order contract: (doc_type, language) group serial — β-JP-1
LLMNarrativePass inherits this base and gains Bedrock prompt cache
friendliness automatically.
"""

from __future__ import annotations

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clinosim.modules.llm_service.engine import LLMService

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp, resolve_lang
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
from clinosim.types.document import NarrativeContext, NarrativeGenerator, NarrativeOutput

logger = logging.getLogger(__name__)


def _parse_dt(value: Any) -> datetime | None:
    """Parse a structural-CIF datetime value (ISO string / datetime / None)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class NarrativePass(ABC):
    """Stage 2 base class: read structural CIF → write narrative-tree CIF.

    Walk order is (spec, language, patient) — β-JP-1 LLMNarrativePass groups
    by (doc_type, language) to maximize Bedrock prompt cache hits.

    N-1 (N-chain): the content generator is constructor-injected as a
    ``NarrativeGenerator`` (Protocol in ``clinosim/types/document.py``); the
    base ``_generate`` delegates to it. Subclasses supply the generator and
    the manifest identity via ``_generator_name``.
    """

    def __init__(
        self,
        cif_dir: str,
        version_id: str,
        country: str,
        tasks: list[str] | None = None,
        rng_seed: int = 42,
        *,
        generator: NarrativeGenerator,
        patient_filter: str | None = None,
    ):
        self.cif_dir = cif_dir
        self.version_id = version_id
        self.country = country
        self.tasks_filter = set(tasks) if tasks else None
        self.rng_seed = rng_seed
        self.generator = generator
        # β-JP-1 chain 1b T3: optional regex over patient filename stem OR
        # patient_id — remote per-patient iteration support. Compiled here so
        # an invalid regex fails loud at construction, not mid-walk.
        self.patient_filter = patient_filter or ""
        self._patient_filter_re: re.Pattern[str] | None = (
            re.compile(patient_filter) if patient_filter else None
        )

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
        if self._patient_filter_re is not None:
            patient_files = self._apply_patient_filter(structural_dir, patient_files)
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
                        # α-min-3: per-stub shift key (daily_3shift stubs carry
                        # "night"/"day"/"evening"; all other stubs ""). ctx is
                        # shared across this patient's stubs, so set per stub
                        # before generating — the renderer resolves the
                        # localized label from this neutral key (AD-30 spirit).
                        ctx.shift = str(stub.get("shift", "") or "")
                        # β-JP-1 chain 1a: per-stub hospital day (mirrors the
                        # ctx.shift pattern) — daily notes previously all
                        # rendered as day 0 because ctx was built once per
                        # patient with day_index=0.
                        ctx.day_index = self._stub_day_index(stub, encounter_dict)
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
            llm_cost_report=self._llm_cost_report(),
            patient_filter=self.patient_filter,
            partial=bool(self.patient_filter),
        )
        manifest_path = os.path.join(self.cif_dir, "narratives", self.version_id, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(asdict(manifest), f, indent=2, ensure_ascii=False)
        return manifest

    def _apply_patient_filter(
        self, structural_dir: str, patient_files: list[str]
    ) -> list[str]:
        """T3: keep files whose stem OR patient_id matches ``patient_filter``.

        One extra JSON read per patient, only when a filter is set (the
        default None path costs nothing). Order is preserved (sorted input →
        sorted output) so the walk stays deterministic and any selected
        patient's output is byte-identical to the unfiltered run (AD-16).
        """
        assert self._patient_filter_re is not None
        selected: list[str] = []
        for pf in patient_files:
            stem = pf[: -len(".json")]
            if self._patient_filter_re.search(stem):
                selected.append(pf)
                continue
            with open(os.path.join(structural_dir, pf)) as f:
                patient_dict = json.load(f)
            patient_id = str(_o(patient_dict.get("patient") or {}, "patient_id", "") or "")
            if patient_id and self._patient_filter_re.search(patient_id):
                selected.append(pf)
        return selected

    def _generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Default: delegate to the injected NarrativeGenerator (N-1)."""
        return self.generator.generate(ctx, spec)

    @abstractmethod
    def _generator_name(self) -> str: ...

    def _generator_config(self) -> dict[str, Any]:
        return {}

    def _llm_cost_report(self) -> dict[str, Any]:
        """Manifest ``llm_cost_report`` hook — overridden by LLMNarrativePass.

        Base returns ``{}`` so the template path manifest stays byte-identical.
        """
        return {}

    def _languages_for_spec(self, spec: DocumentTypeSpec) -> list[str]:
        # US → en, JP → ja. β-JP-1 で bilingual 可能に拡張。
        return [resolve_lang(self.country)]

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
        """Assemble the per-patient NarrativeContext from real structural CIF keys.

        β-JP-1 chain 1a (spec §2b): every field is wired to the actual
        structural JSON schema (``vital_signs`` / ``medication_administrations``
        + ``discharge_prescription`` / ``clinical_diagnosis`` /
        ``patient.allergies`` / ``encounter.severity`` /
        ``encounter.clinical_course_archetype``). Pre-1a JSON without the new
        Stage 1 fields degrades to the old defaults (""/[]/None) — never raise.

        ``day_index`` is a per-stub value: ``run()`` overrides it per stub
        (mirroring ``ctx.shift``) via ``_stub_day_index``; the value set here
        is only the day-0 base.
        """
        from clinosim.modules.document import DocumentType

        condition_event = patient_dict.get("condition_event") or {}
        disease_protocol = self._resolve_disease_protocol(condition_event)
        encounter_protocol = self._resolve_encounter_protocol(condition_event)
        archetype = str(encounter_dict.get("clinical_course_archetype", "") or "")
        clinical_diagnosis = patient_dict.get("clinical_diagnosis") or None

        ctx = NarrativeContext(
            patient=patient_dict.get("patient"),
            encounter=encounter_dict,
            encounter_type=encounter_dict.get("encounter_type"),
            disease_protocol=disease_protocol,
            encounter_protocol=encounter_protocol,
            clinical_course_archetype=archetype,
            severity=str(encounter_dict.get("severity", "") or ""),
            day_index=0,
            los_days=self._compute_los_days(patient_dict, encounter_dict),
            vitals=patient_dict.get("vital_signs", []) or [],
            lab_results=patient_dict.get("lab_results", []) or [],
            medications=self._collect_medications(patient_dict),
            discharge_medications=self._collect_discharge_medications(patient_dict),
            diagnoses=[clinical_diagnosis] if clinical_diagnosis else [],
            procedures=patient_dict.get("procedures", []) or [],
            rehab_sessions=patient_dict.get("rehab_sessions", []) or [],
            allergies=_o(patient_dict.get("patient") or {}, "allergies", []) or [],
            document_type=DocumentType(spec.type_key),
            target_lang=language,
            locale="jp" if is_jp(self.country) else "us",
        )
        ctx.narrative_spine = build_narrative_spine(
            disease_protocol,
            encounter_protocol,
            archetype,
        )
        ctx.materialized_facts = extract_all_facts(patient_dict, encounter_dict, ctx)
        if spec.format_type.value == "composition":
            ctx.section_facts = extract_for_composition(ctx, spec)
        return ctx

    @staticmethod
    def _resolve_disease_protocol(condition_event: Any) -> Any | None:
        """Resolve the DiseaseProtocol for a known_disease condition event.

        Only ``condition_type == "known_disease"`` carries a disease id in
        ``ground_truth_diseases[0]`` (ED stores an encounter condition id;
        outpatient follow-ups store ICD codes). ``load_disease_protocol`` is
        lru_cached (PR #133) so the per-patient call is cheap; the returned
        protocol is a SHARED instance and must not be mutated.
        """
        if str(_o(condition_event, "condition_type", "") or "") != "known_disease":
            return None
        gt = _o(condition_event, "ground_truth_diseases", []) or []
        if not gt:
            return None
        disease_id = str(gt[0])
        from clinosim.modules.disease.protocol import load_disease_protocol

        try:
            return load_disease_protocol(disease_id)
        except FileNotFoundError:
            logger.warning(
                "narrative context: unknown disease id %r in condition_event — "
                "disease_protocol falls back to None", disease_id,
            )
            return None

    @staticmethod
    def _resolve_encounter_protocol(condition_event: Any) -> Any | None:
        """Resolve the encounter condition protocol for an ed_visit event.

        ``simulate_ed_visit`` stores the encounter condition id in
        ``ground_truth_diseases[0]`` with ``condition_type="ed_visit"`` (both
        EMERGENCY and outpatient-typed encounter-YAML visits go through it).
        Outpatient chronic/post-discharge follow-ups store ICD codes instead —
        not recoverable; encounter_protocol stays None there (spec §3 TODO).
        """
        if str(_o(condition_event, "condition_type", "") or "") != "ed_visit":
            return None
        gt = _o(condition_event, "ground_truth_diseases", []) or []
        if not gt:
            return None
        condition_id = str(gt[0])
        from clinosim.modules.encounter.protocol import load_encounter_condition

        try:
            return load_encounter_condition(condition_id)
        except FileNotFoundError:
            logger.warning(
                "narrative context: unknown encounter condition id %r in "
                "condition_event — encounter_protocol falls back to None", condition_id,
            )
            return None

    @staticmethod
    def _collect_medications(patient_dict: dict[str, Any]) -> list[Any]:
        """MAR entries only as ``ctx.medications`` (in-hospital administrations).

        adv-1 I-1: ``discharge_prescription.items`` were previously merged in
        here, which leaked ICU drips (Dobutamine / Norepinephrine) and
        protocol-prefixed in-hospital orders into the discharge_medications
        narrative section. In-hospital consumers
        (``extract_medication_facts`` / ``section_extractor``) read the MAR
        shape ``drug_name`` (+ optional ``dose``); discharge prescriptions are
        collected separately by ``_collect_discharge_medications``.
        """
        return list(patient_dict.get("medication_administrations", []) or [])

    @staticmethod
    def _collect_discharge_medications(patient_dict: dict[str, Any]) -> list[Any]:
        """``discharge_prescription.items`` normalized to the consumer shape.

        Only source for ``ctx.discharge_medications`` (adv-1 I-1). Inpatient
        rx items carry ``drug_name`` (``simulator/inpatient.py``
        ``_build_discharge_prescription``) while outpatient renewal items
        carry ``drug`` (``simulator/outpatient.py``); both shapes are
        normalized to ``{"drug_name", "dose"}`` here (spec §2b decision:
        adapt the source to the consumer contract, not vice versa).
        """
        rx = patient_dict.get("discharge_prescription") or None
        if rx is None:
            return []
        items: list[Any] = []
        for item in _o(rx, "items", []) or []:
            drug = str(_o(item, "drug_name", "") or _o(item, "drug", "") or "")
            if drug:
                items.append(
                    {"drug_name": drug, "dose": str(_o(item, "dose", "") or "")}
                )
        return items

    @staticmethod
    def _compute_los_days(
        patient_dict: dict[str, Any], encounter_dict: dict[str, Any]
    ) -> int:
        """LOS in whole days from admission→discharge dates.

        In-progress encounters (AD-32 snapshot truncation) reuse the document
        engine's physiological_states proxy — single edit point, no duplicated
        proxy rule (``clinosim.modules.document.engine._compute_los_days``).
        """
        from clinosim.modules.document.engine import (
            _compute_los_days as _engine_los,
        )

        admission_dt = _parse_dt(encounter_dict.get("admission_datetime"))
        if admission_dt is None:
            return 1
        discharge_dt = _parse_dt(encounter_dict.get("discharge_datetime"))
        states = patient_dict.get("physiological_states", []) or []
        return _engine_los(admission_dt, discharge_dt, list(states))

    @staticmethod
    def _stub_day_index(stub: dict[str, Any], encounter_dict: dict[str, Any]) -> int:
        """0-based hospital day of one document stub (spec §2b per-stub day).

        Derived from the stub's ``period_start`` (fallback:
        ``authored_datetime``) minus the encounter admission date. Missing /
        unparseable dates → 0 (pre-1a behavior); negative deltas are clamped
        to 0 (defensive — stubs never precede admission in production).
        """
        stub_dt = _parse_dt(stub.get("period_start")) or _parse_dt(
            stub.get("authored_datetime")
        )
        admission_dt = _parse_dt(encounter_dict.get("admission_datetime"))
        if stub_dt is None or admission_dt is None:
            return 0
        return max(0, (stub_dt.date() - admission_dt.date()).days)

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
        generator: NarrativeGenerator | None = None,
        patient_filter: str | None = None,
    ):
        # F-5 adv-1: `self._rng` was allocated here from rng_seed but never
        # consumed — TemplateNarrativeGenerator is deterministic modulo
        # rng_seed via `_deterministic_timestamp` and fact ordering only.
        # Removed to eliminate the aspirational-scaffold no-op wiring
        # (β-JP-1 LLMNarrativePass will re-allocate if it needs one).
        super().__init__(
            cif_dir,
            version_id,
            country,
            tasks,
            rng_seed,
            generator=generator if generator is not None else TemplateNarrativeGenerator(),
            patient_filter=patient_filter,
        )

    def _generator_name(self) -> str:
        return "template"


class LLMNarrativePass(NarrativePass):
    """Stage 2 LLM-backed narrative pass (N-1b, N-chain 2026-07-02).

    Wraps ``LLMNarrativeGenerator`` (template base + per-section LLM
    replacement per ``DocumentTypeSpec.stage2_strategy``) around the base
    walk order — (doc_type, language) group serial is inherited unchanged,
    which keeps Bedrock prompt cache hit rates maximal (AD-65).

    All LLM traffic goes through the injected ``LLMService`` (AD-11):
    retry, disk PromptCache and token accounting live in the service; the
    in-memory ``NarrativeCache`` (layer 1, clinical-context key) is owned
    per pass instance for cross-patient reuse within one run. The manifest
    ``llm_cost_report`` is wired from ``LLMService.cost_report()``.
    """

    def __init__(
        self,
        cif_dir: str,
        llm: LLMService,
        version_id: str = "llm",
        country: str = "US",
        tasks: list[str] | None = None,
        rng_seed: int = 42,
        patient_filter: str | None = None,
    ):
        from clinosim.modules.document.narrative.cache import NarrativeCache
        from clinosim.modules.document.narrative.llm_generator import LLMNarrativeGenerator

        self.llm = llm
        self._llm_generator = LLMNarrativeGenerator(
            template_generator=TemplateNarrativeGenerator(),
            llm=llm,
            cache=NarrativeCache(),
        )
        super().__init__(
            cif_dir, version_id, country, tasks, rng_seed,
            generator=self._llm_generator, patient_filter=patient_filter,
        )

    def run(self) -> NarrativeVersionManifest:
        """Base walk + loud all-fallback detection (I-2, N-chain adv-1).

        A dead provider (e.g. Ollama server down) must not pass silently:
        when at least one processed doc was template_seed-eligible and ZERO
        docs got LLM content, every call failed — print a stderr WARNING.
        Not an exception: ``narrate`` must remain usable offline (the
        template fallback output itself is valid).
        """
        import sys

        manifest = super().run()
        gen = self._llm_generator
        if gen.eligible_docs > 0 and gen.llm_docs == 0:
            print(
                f"WARNING: narrate produced 0 LLM documents out of "
                f"{gen.eligible_docs} template_seed-eligible docs — every LLM "
                f"call fell back to template output. Check provider "
                f"connectivity/config. Sampled reasons: {gen.fallback_reasons}",
                file=sys.stderr,
            )
        return manifest

    def _generator_name(self) -> str:
        return f"llm-{self.llm.provider_name_narrative or 'none'}"

    def _generator_config(self) -> dict[str, Any]:
        return {
            "provider": self.llm.provider_name_narrative,
            "mode": self.llm.mode,
            "narrative_model_map": dict(self.llm.narrative_model_map),
        }

    def _llm_cost_report(self) -> dict[str, Any]:
        """Service-level cost report + generator-level fallback counters (I-2).

        The service counters (total_calls / fallback_count) only see calls
        that REACHED the service; the generator counters expose docs whose
        LLM path never fired or fell back to template.
        """
        report = dict(self.llm.cost_report())
        gen = self._llm_generator
        report["generator_llm_docs"] = gen.llm_docs
        report["generator_fallback_docs"] = gen.fallback_docs
        report["generator_fallback_reasons"] = list(gen.fallback_reasons)
        return report
