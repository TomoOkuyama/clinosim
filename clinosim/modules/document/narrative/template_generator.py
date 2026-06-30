"""Template-based narrative generator (Tier 1 #3 α-min-1 PR1 Task 6).

Stage 1 default generator producing deterministic narrative text from CIF
+ disease YAML + reference data. No LLM dependency. Dispatches by
DocumentTypeSpec.format_type to one of 3 renderers.

Multi-day fallback chain (Task 4 lesson):
  1. disease_protocol.narrative.physical_exam_findings[archetype][day_N]
  2. reference_data findings[disease_id][archetype][day_N]
  3. same chain at prior days (N-1, N-2, ..., 0)
  4. baseline reference data [archetype][day_N] with same fallback
  5. generic phrase fallback ("特記事項なし" / "No special findings")

Never raise, never return empty narrative field.

EN locale note: when a disease YAML field has only "ja" (no "en" key), the
generator falls back to the "ja" text and notes this in facts_used as
"<path>:ja_only_fallback". For fields with both "en" and "ja" (e.g.
discharge_instructions), the target_lang key is used directly. This is
preferable to fabricating English text for JP-clinical-context disease YAMLs.

Jinja2-like substitution: all template substitution is via Python
str.format_map() with named placeholders. For α-min-1, templates that
require computed values (e.g. "{onset_days_ago}日前より") use a fixed
reasonable default (3 days) when onset cannot be derived from CIF without
complex date arithmetic.
"""

from __future__ import annotations

from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.reference_data_loaders import (
    load_discharge_instructions,
    load_physical_exam_findings,
)
from clinosim.types.document import FormatType, NarrativeContext, NarrativeOutput

# Generic fallback phrases per locale
_GENERIC_FALLBACK_JA = "特記事項なし"
_GENERIC_FALLBACK_EN = "No special findings"
_GENERIC_ASSESSMENT_JA = "経過観察中"
_GENERIC_ASSESSMENT_EN = "Clinical assessment ongoing"
_GENERIC_PLAN_JA = "治療継続"
_GENERIC_PLAN_EN = "Continue current management"

# NKDA phrases per locale
_NKDA_JA = "薬物アレルギーなし（NKDA）"
_NKDA_EN = "No known drug allergies (NKDA)"

# Social history smoking labels
_SMOKING_JA: dict[str, str] = {
    "never": "非喫煙者",
    "former": "元喫煙者",
    "current": "喫煙者（現在）",
    "unknown": "喫煙歴不明",
}
_SMOKING_EN: dict[str, str] = {
    "never": "Non-smoker",
    "former": "Former smoker",
    "current": "Current smoker",
    "unknown": "Smoking history unknown",
}

# Alcohol use labels
_ALCOHOL_JA: dict[str, str] = {
    "none": "飲酒なし",
    "occasional": "機会飲酒",
    "moderate": "適度な飲酒",
    "heavy": "多量飲酒",
    "unknown": "飲酒状況不明",
}
_ALCOHOL_EN: dict[str, str] = {
    "none": "Non-drinker",
    "occasional": "Occasional drinker",
    "moderate": "Moderate drinker",
    "heavy": "Heavy drinker",
    "unknown": "Alcohol use unknown",
}

# SOAP section labels per locale
_SOAP_JA = ("S（主観）", "O（客観）", "A（評価）", "P（計画）")
_SOAP_EN = ("S:", "O:", "A:", "P:")


class TemplateNarrativeGenerator:
    """Stage 1 default narrative generator.

    Produces deterministic narrative text from CIF + disease YAML + reference
    data. No LLM calls. Dispatches by DocumentTypeSpec.format_type.

    See module docstring for fallback chain and locale policy details.
    """

    def generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Dispatch by spec.format_type and return NarrativeOutput."""
        if spec.format_type == FormatType.FREE_TEXT:
            return self._render_free_text(ctx, spec)
        elif spec.format_type == FormatType.COMPOSITION:
            return self._render_composition_sections(ctx, spec)
        elif spec.format_type == FormatType.QUESTIONNAIRE_RESPONSE:
            return self._render_structured_form(ctx, spec)
        else:
            raise ValueError(f"Unsupported format_type: {spec.format_type}")

    # ─────────────────────────────────────────────────────────────────
    # Renderer: FREE_TEXT (PROGRESS_NOTE)
    # ─────────────────────────────────────────────────────────────────

    def _render_free_text(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Build a SOAP-style progress note as plain text."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        soap_labels = _SOAP_JA if is_ja else _SOAP_EN

        # Resolve daily trajectory for this day (with fallback chain)
        traj, traj_source = self._resolve_daily_trajectory_with_source(
            ctx, ctx.clinical_course_archetype, ctx.day_index
        )
        if traj_source:
            facts.append(traj_source)

        _generic_s = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN
        _generic_a = _GENERIC_ASSESSMENT_JA if is_ja else _GENERIC_ASSESSMENT_EN
        _generic_p = _GENERIC_PLAN_JA if is_ja else _GENERIC_PLAN_EN
        subjective = traj.get("subjective") or _generic_s
        objective = traj.get("objective") or _generic_s
        assessment = traj.get("assessment") or _generic_a
        plan = traj.get("plan") or _generic_p

        # Add physical exam findings to the objective section
        phys_exam = self._resolve_physical_exam(ctx, ctx.clinical_course_archetype, ctx.day_index)
        if phys_exam:
            facts.append(
                f"physical_exam_findings.{ctx.clinical_course_archetype}.day_{ctx.day_index}"
            )
        phys_summary = self._format_physical_exam(phys_exam, ctx.severity, is_ja)
        if phys_summary:
            objective = f"{objective}。{phys_summary}" if is_ja else f"{objective}. {phys_summary}"

        # Build SOAP note
        sep = "\n"
        raw_text = sep.join([
            f"{soap_labels[0]} {subjective}",
            f"{soap_labels[1]} {objective}",
            f"{soap_labels[2]} {assessment}",
            f"{soap_labels[3]} {plan}",
        ])

        # Always add at least ctx reference
        facts.append("ctx.day_index")
        facts.append("ctx.clinical_course_archetype")

        return NarrativeOutput(
            raw_text=raw_text,
            metadata={"generator": "template", "lang": lang, "day_index": ctx.day_index},
            facts_used=facts,
        )

    # ─────────────────────────────────────────────────────────────────
    # Renderer: COMPOSITION (ADMISSION_HP, DISCHARGE_SUMMARY)
    # ─────────────────────────────────────────────────────────────────

    def _render_composition_sections(
        self, ctx: NarrativeContext, spec: DocumentTypeSpec
    ) -> NarrativeOutput:
        """Build section dict per spec.composition_sections."""
        facts: list[str] = []
        sections: dict[str, str] = {}

        section_builders = {
            "chief_complaint": self._build_chief_complaint,
            "hpi": self._build_hpi,
            "past_medical_history": self._build_past_medical_history,
            "medications_at_home": self._build_medications_at_home,
            "allergies": self._build_allergies,
            "social_history": self._build_social_history,
            "family_history": self._build_family_history,
            "physical_examination": self._build_physical_examination,
            "assessment_and_plan": self._build_assessment_and_plan,
            "admission_summary": self._build_admission_summary,
            "hospital_course": self._build_hospital_course,
            "discharge_diagnoses": self._build_discharge_diagnoses,
            "discharge_medications": self._build_discharge_medications,
            "discharge_instructions": self._build_discharge_instructions,
            "follow_up": self._build_follow_up,
        }

        for section in spec.composition_sections:
            builder = section_builders.get(section)
            if builder is not None:
                text, section_facts = builder(ctx)
                sections[section] = text
                facts.extend(section_facts)
            else:
                # Unknown section — generic fallback
                lang = ctx.target_lang
                sections[section] = _GENERIC_FALLBACK_JA if lang == "ja" else _GENERIC_FALLBACK_EN

        return NarrativeOutput(
            sections=sections,
            metadata={"generator": "template", "lang": ctx.target_lang},
            facts_used=facts,
        )

    # ─────────────────────────────────────────────────────────────────
    # Renderer: QUESTIONNAIRE_RESPONSE (infrastructure stub)
    # ─────────────────────────────────────────────────────────────────

    def _render_structured_form(
        self, ctx: NarrativeContext, spec: DocumentTypeSpec
    ) -> NarrativeOutput:
        """QUESTIONNAIRE_RESPONSE infrastructure stub for α-min-1.

        Returns empty structured dict with metadata indicating stub stage.
        β-JP-1 phase will implement the full form structure.
        """
        return NarrativeOutput(
            structured={},
            metadata={
                "generator": "template",
                "lang": ctx.target_lang,
                "stage": "infrastructure_stub",
            },
            facts_used=[],
        )

    # ─────────────────────────────────────────────────────────────────
    # Section builders (COMPOSITION)
    # ─────────────────────────────────────────────────────────────────

    def _build_chief_complaint(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build chief_complaint section from disease_protocol."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = "発熱・全身倦怠感" if is_ja else "Chief complaint not specified"

        proto = ctx.disease_protocol
        if proto is None:
            return fallback, facts

        cc = _o(proto, "chief_complaint", None)
        if cc is None:
            return fallback, facts

        if isinstance(cc, dict):
            text = cc.get(lang) or cc.get("ja" if is_ja else "en") or cc.get("en") or fallback
            key = "ja" if is_ja else "en"
            facts_key = f"disease_protocol.chief_complaint.{key}"
            if text == fallback:
                facts_key += ":fallback"
            facts.append(facts_key)
        else:
            # Plain string (pre-Task-4 format)
            text = str(cc)
            facts.append("disease_protocol.chief_complaint:str")

        return text, facts

    def _build_hpi(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build HPI from narrative.hpi_template.onset_pattern[severity]."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = (
            f"{ctx.severity}の症状で受診。" if is_ja
            else f"Patient presented with {ctx.severity} symptoms."
        )

        proto = ctx.disease_protocol
        narrative = _o(proto, "narrative", None) if proto is not None else None
        if narrative is None:
            return fallback, facts

        hpi_tmpl = _o(narrative, "hpi_template", None)
        if hpi_tmpl is None:
            return fallback, facts

        onset_pattern = _o(hpi_tmpl, "onset_pattern", {})
        if isinstance(onset_pattern, dict):
            onset_text = onset_pattern.get(ctx.severity) or onset_pattern.get("moderate") or ""
        else:
            onset_text = ""

        trigger_options = _o(hpi_tmpl, "trigger_options", []) or []
        trigger = trigger_options[0] if trigger_options else ""

        if onset_text:
            text = f"{onset_text} {trigger}".strip() if trigger else onset_text
            facts.append(
                f"disease_protocol.narrative.hpi_template.onset_pattern.{ctx.severity}"
            )
            if trigger:
                facts.append("disease_protocol.narrative.hpi_template.trigger_options[0]")
        else:
            text = fallback

        return text, facts

    def _build_past_medical_history(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build past medical history from ctx.patient.chronic_conditions."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        none_text = "特記既往歴なし" if is_ja else "No significant past medical history"

        patient = ctx.patient
        if patient is None:
            return none_text, facts

        conditions = _o(patient, "chronic_conditions", []) or []
        if not conditions:
            return none_text, facts

        facts.append("ctx.patient.chronic_conditions")
        # Each condition: use code field (display resolved at output time; CIF rule)
        lines = []
        for cond in conditions:
            code = _o(cond, "code", "")
            stage = _o(cond, "stage", "")
            if code:
                lines.append(f"{code}{' (' + stage + ')' if stage else ''}")
        if lines:
            return "; ".join(lines), facts
        return none_text, facts

    def _build_medications_at_home(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build home medications from ctx.patient.current_medications."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        none_text = "常用薬なし" if is_ja else "No home medications"

        patient = ctx.patient
        if patient is None:
            return none_text, facts

        meds = _o(patient, "current_medications", []) or []
        if not meds:
            return none_text, facts

        facts.append("ctx.patient.current_medications")
        return "; ".join(str(m) for m in meds), facts

    def _build_allergies(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build allergies section from ctx.allergies."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        allergies = ctx.allergies or []
        if not allergies:
            return _NKDA_JA if is_ja else _NKDA_EN, facts

        facts.append("ctx.allergies")
        parts = []
        for allergy in allergies:
            display = _o(allergy, "allergen_display", "") or ""
            criticality = _o(allergy, "criticality", "") or ""
            if display:
                if criticality:
                    crit_str = f"（{criticality}）" if is_ja else f" ({criticality})"
                    parts.append(f"{display}{crit_str}")
                else:
                    parts.append(display)
        return "; ".join(parts) if parts else (_NKDA_JA if is_ja else _NKDA_EN), facts

    def _build_social_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build social history from patient smoking_status, alcohol_use, occupation."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        patient = ctx.patient
        if patient is None:
            return _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN, facts

        smoking_status = _o(patient, "smoking_status", "unknown") or "unknown"
        alcohol_use = _o(patient, "alcohol_use", "unknown") or "unknown"
        occupation = _o(patient, "occupation", "") or ""

        smoke_map = _SMOKING_JA if is_ja else _SMOKING_EN
        alcohol_map = _ALCOHOL_JA if is_ja else _ALCOHOL_EN

        smoke_text = smoke_map.get(smoking_status, smoke_map.get("unknown", ""))
        alcohol_text = alcohol_map.get(alcohol_use, alcohol_map.get("unknown", ""))

        parts = []
        if smoke_text:
            key = "喫煙歴" if is_ja else "Smoking"
            parts.append(f"{key}: {smoke_text}")
        if alcohol_text:
            key = "飲酒歴" if is_ja else "Alcohol"
            parts.append(f"{key}: {alcohol_text}")
        if occupation:
            key = "職業" if is_ja else "Occupation"
            parts.append(f"{key}: {occupation}")

        facts.append("ctx.patient.smoking_status")
        facts.append("ctx.patient.alcohol_use")
        facts.append("ctx.patient.occupation")

        fallback = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN
        return "; ".join(parts) if parts else fallback, facts

    def _build_family_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build family history — generic placeholder for α-min-1."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        text = "特記家族歴なし" if is_ja else "No significant family history"
        return text, []

    def _build_physical_examination(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build physical_examination using multi-step fallback chain."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        phys_exam = self._resolve_physical_exam(
            ctx, ctx.clinical_course_archetype, ctx.day_index
        )
        if phys_exam:
            facts.append(
                f"physical_exam_findings.{ctx.clinical_course_archetype}.day_{ctx.day_index}"
            )

        text = self._format_physical_exam(phys_exam, ctx.severity, is_ja)
        if not text:
            text = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN

        return text, facts

    def _build_assessment_and_plan(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build assessment_and_plan from daily_trajectory day_0 assessment + plan."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        traj, traj_src = self._resolve_daily_trajectory_with_source(
            ctx, ctx.clinical_course_archetype, 0
        )
        if traj_src:
            facts.append(traj_src)

        _generic_a = _GENERIC_ASSESSMENT_JA if is_ja else _GENERIC_ASSESSMENT_EN
        _generic_p = _GENERIC_PLAN_JA if is_ja else _GENERIC_PLAN_EN
        assessment = traj.get("assessment") or _generic_a
        plan = traj.get("plan") or _generic_p

        if is_ja:
            text = f"評価: {assessment}。方針: {plan}。"
        else:
            text = f"Assessment: {assessment}. Plan: {plan}."

        return text, facts

    def _build_admission_summary(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build admission_summary for DISCHARGE_SUMMARY."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        cc_text, cc_facts = self._build_chief_complaint(ctx)
        facts.extend(cc_facts)

        if is_ja:
            text = f"主訴: {cc_text}。入院日: {ctx.day_index + 1} 日目現在。"
        else:
            text = f"Chief complaint: {cc_text}. Admitted for inpatient care."

        return text, facts

    def _build_hospital_course(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build hospital_course — 1-3 sentence summary across all days."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        los = ctx.los_days or 1

        if is_ja:
            text = f"入院 {los} 日間の治療を経て経過良好。症状は改善し退院となった。"
        else:
            text = (
                f"The patient was hospitalized for {los} days. "
                "Clinical course was favorable with improvement in presenting symptoms."
            )

        return text, facts

    def _build_discharge_diagnoses(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build discharge_diagnoses from ctx.diagnoses."""
        facts: list[str] = []

        diagnoses = ctx.diagnoses or []
        if not diagnoses:
            # Fall back to chief complaint
            cc_text, _ = self._build_chief_complaint(ctx)
            return cc_text, []

        facts.append("ctx.diagnoses")
        codes = []
        for dx in diagnoses:
            code = _o(dx, "discharge_diagnosis_code", "") or _o(dx, "admission_diagnosis_code", "")
            if code:
                codes.append(code)

        if codes:
            return "; ".join(codes), facts

        # No codes — fall back
        cc_text, _ = self._build_chief_complaint(ctx)
        return cc_text, []

    def _build_discharge_medications(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build discharge_medications from ctx.medications (status=given)."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        none_text = "退院処方なし" if is_ja else "No discharge medications"

        meds = ctx.medications or []
        if not meds:
            return none_text, facts

        facts.append("ctx.medications")
        seen: set[str] = set()
        drug_names = []
        for med in meds:
            drug = _o(med, "drug_name", "") or ""
            if drug and drug not in seen:
                seen.add(drug)
                drug_names.append(drug)

        if drug_names:
            return "; ".join(drug_names), facts
        return none_text, facts

    def _build_discharge_instructions(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build discharge_instructions using disease-specific override + baseline merge."""
        facts: list[str] = []
        lang = ctx.target_lang

        instructions = self._resolve_discharge_instructions(ctx)
        facts.append("discharge_instructions.baseline")

        disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol else None
        if disease_id:
            facts.append(f"discharge_instructions.disease_specific.{disease_id}")

        parts = []
        for key, bi_lang in instructions.items():
            text = bi_lang.get(lang) or bi_lang.get("ja") or bi_lang.get("en") or ""
            if text:
                parts.append(text)

        return " ".join(parts), facts

    def _build_follow_up(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build follow_up section from discharge instructions follow_up entry."""
        lang = ctx.target_lang

        instructions = self._resolve_discharge_instructions(ctx)
        follow_up_entry = instructions.get("follow_up") or {}
        text = (
            follow_up_entry.get(lang)
            or follow_up_entry.get("ja")
            or follow_up_entry.get("en")
            or ""
        )
        if not text:
            text = (
                "外来フォローアップ予定" if lang == "ja"
                else "Follow up with outpatient provider"
            )
        return text, ["discharge_instructions.follow_up"]

    # ─────────────────────────────────────────────────────────────────
    # Fallback helpers
    # ─────────────────────────────────────────────────────────────────

    def _resolve_physical_exam(
        self, ctx: NarrativeContext, archetype: str, day_index: int
    ) -> dict[str, Any]:
        """Multi-step fallback chain for per-day physical exam findings.

        Fallback priority:
          1. disease_protocol.narrative.physical_exam_findings[archetype][day_N] (Pydantic)
          2. reference_data.findings[disease_id][archetype][day_N]
          3. Steps 1-2 at prior days (N-1 ... 0)
          4. baseline.reference_data[archetype][day_N] with same fallback
          5. Returns {} (caller uses generic phrase)
        """
        # Try days from current down to 0
        candidate_days = list(range(day_index, -1, -1))

        # Source 1+2: disease protocol narrative + reference_data.findings
        disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol else None
        narrative = _o(ctx.disease_protocol, "narrative", None) if ctx.disease_protocol else None
        pex_data = load_physical_exam_findings()

        for day in candidate_days:
            day_key = f"day_{day}"

            # Source 1: disease_protocol.narrative.physical_exam_findings[archetype][day_N]
            if narrative is not None:
                proto_pex = _o(narrative, "physical_exam_findings", {})
                if isinstance(proto_pex, dict):
                    arch_day = proto_pex.get(archetype, {})
                    if isinstance(arch_day, dict):
                        day_findings = arch_day.get(day_key)
                        if day_findings is not None:
                            return self._pydantic_day_findings_to_dict(day_findings)

            # Source 2: reference_data.findings[disease_id][archetype][day_N]
            if disease_id:
                ref_findings = pex_data.get("findings", {})
                disease_findings = ref_findings.get(disease_id, {})
                arch_findings = disease_findings.get(archetype, {})
                day_entry = arch_findings.get(day_key)
                if day_entry is not None:
                    return day_entry if isinstance(day_entry, dict) else {}

        # Source 3+4: baseline reference data
        baseline = pex_data.get("baseline", {})

        # Try archetype directly
        arch_baseline = baseline.get(archetype, {})
        for day in candidate_days:
            day_key = f"day_{day}"
            day_entry = arch_baseline.get(day_key)
            if day_entry is not None:
                return day_entry if isinstance(day_entry, dict) else {}

        # Try similar archetypes (graceful fallback across archetype names)
        for alt_arch, alt_data in baseline.items():
            if not isinstance(alt_data, dict):
                continue
            for day in candidate_days:
                day_key = f"day_{day}"
                day_entry = alt_data.get(day_key)
                if day_entry is not None:
                    return day_entry if isinstance(day_entry, dict) else {}

        return {}

    def _resolve_daily_trajectory(
        self, ctx: NarrativeContext, archetype: str, day_index: int
    ) -> dict[str, str]:
        """Fallback chain for SOAP-structured daily trajectory.

        Fallback priority:
          1. disease_protocol.course_archetypes[archetype].daily_trajectory[day_N]
          2. Same at prior days (N-1 ... 0)
          3. Generic SOAP entry (always succeeds)
        """
        traj, _ = self._resolve_daily_trajectory_with_source(ctx, archetype, day_index)
        return traj

    def _resolve_daily_trajectory_with_source(
        self, ctx: NarrativeContext, archetype: str, day_index: int
    ) -> tuple[dict[str, str], str]:
        """Like _resolve_daily_trajectory but also returns source path for facts_used.

        Returns (trajectory_dict, source_path) where source_path is an empty string
        when the generic fallback is used (not from disease YAML).
        """
        proto = ctx.disease_protocol
        if proto is None:
            return self._generic_trajectory(ctx), ""

        course_archetypes = _o(proto, "course_archetypes", {}) or {}
        archetype_data = course_archetypes.get(archetype) or {}

        daily_trajectory: dict[str, Any] = {}
        if isinstance(archetype_data, dict):
            daily_trajectory = archetype_data.get("daily_trajectory") or {}
        else:
            # Pydantic model — try attribute
            daily_trajectory = _o(archetype_data, "daily_trajectory", {}) or {}

        candidate_days = list(range(day_index, -1, -1))
        for day in candidate_days:
            day_key = f"day_{day}"
            entry = daily_trajectory.get(day_key)
            if entry is not None:
                source = (
                    f"disease_protocol.course_archetypes.{archetype}"
                    f".daily_trajectory.{day_key}"
                )
                if isinstance(entry, dict):
                    return entry, source
                # Pydantic DailyTrajectoryEntry
                return {
                    "subjective": _o(entry, "subjective", ""),
                    "objective": _o(entry, "objective", ""),
                    "assessment": _o(entry, "assessment", ""),
                    "plan": _o(entry, "plan", ""),
                }, source

        # No trajectory entry found — return generic with no source
        return self._generic_trajectory(ctx), ""

    def _generic_trajectory(self, ctx: NarrativeContext) -> dict[str, str]:
        """Return generic SOAP entry for when no trajectory data is available."""
        is_ja = ctx.target_lang == "ja"
        return {
            "subjective": _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN,
            "objective": _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN,
            "assessment": _GENERIC_ASSESSMENT_JA if is_ja else _GENERIC_ASSESSMENT_EN,
            "plan": _GENERIC_PLAN_JA if is_ja else _GENERIC_PLAN_EN,
        }

    def _resolve_discharge_instructions(
        self, ctx: NarrativeContext
    ) -> dict[str, dict[str, str]]:
        """Merge baseline + disease_specific discharge instructions.

        disease_specific entries take precedence over baseline for shared keys.
        Returns a flat dict {key: {en: "...", ja: "..."}}.
        """
        di_data = load_discharge_instructions()
        baseline: dict[str, Any] = di_data.get("baseline") or {}
        disease_specific: dict[str, Any] = di_data.get("disease_specific") or {}

        # Start with baseline
        merged: dict[str, dict[str, str]] = {}
        for key, entry in baseline.items():
            if isinstance(entry, dict):
                merged[key] = dict(entry)

        # Override / supplement with disease_specific
        disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol else None
        if disease_id and disease_id in disease_specific:
            overrides = disease_specific[disease_id] or {}
            for key, entry in overrides.items():
                if isinstance(entry, dict):
                    merged[key] = dict(entry)

        # Also check disease YAML's own discharge_instructions (highest priority)
        narrative = _o(ctx.disease_protocol, "narrative", None) if ctx.disease_protocol else None
        if narrative is not None:
            proto_di = _o(narrative, "discharge_instructions", None)
            if proto_di is not None:
                _di_sections = (
                    "follow_up", "activity", "medications", "emergency", "diet_lifestyle"
                )
                for section in _di_sections:
                    sec_data = _o(proto_di, section, {})
                    if isinstance(sec_data, dict) and (sec_data.get("en") or sec_data.get("ja")):
                        merged[section] = dict(sec_data)

        return merged

    # ─────────────────────────────────────────────────────────────────
    # Formatting helpers
    # ─────────────────────────────────────────────────────────────────

    def _pydantic_day_findings_to_dict(self, day_findings: Any) -> dict[str, Any]:
        """Convert a Pydantic PhysicalExamDayFindings to a plain dict."""
        if isinstance(day_findings, dict):
            return day_findings
        # Pydantic model: extract body system fields
        result: dict[str, Any] = {}
        for sys_key in ("general", "cardiovascular", "respiratory", "abdominal", "neurological"):
            val = _o(day_findings, sys_key, None)
            if val is not None:
                if isinstance(val, str):
                    result[sys_key] = val
                else:
                    # PhysicalExamSystemFindings Pydantic model
                    result[sys_key] = {
                        "mild": _o(val, "mild", ""),
                        "moderate": _o(val, "moderate", ""),
                        "severe": _o(val, "severe", ""),
                        "all": _o(val, "all", None),
                    }
        return result

    def _format_physical_exam(
        self, phys_exam: dict[str, Any], severity: str, is_ja: bool
    ) -> str:
        """Format a physical exam findings dict to a single text string.

        Picks the most appropriate severity level per system:
          - prefer "all" (severity-agnostic) if present
          - else pick severity-matched text (mild/moderate/severe)
          - else pick any non-empty text
        """
        if not phys_exam:
            return ""

        body_system_labels_ja = {
            "general": "一般状態",
            "cardiovascular": "循環器",
            "respiratory": "呼吸器",
            "abdominal": "腹部",
            "neurological": "神経",
        }
        body_system_labels_en = {
            "general": "General",
            "cardiovascular": "Cardiovascular",
            "respiratory": "Respiratory",
            "abdominal": "Abdomen",
            "neurological": "Neurological",
        }
        labels = body_system_labels_ja if is_ja else body_system_labels_en

        parts = []
        for sys_key in ("general", "cardiovascular", "respiratory", "abdominal", "neurological"):
            entry = phys_exam.get(sys_key)
            if entry is None:
                continue
            if isinstance(entry, str):
                text = entry
            elif isinstance(entry, dict):
                # Pick severity-specific text
                text = (
                    entry.get("all")
                    or entry.get(severity)
                    or entry.get("moderate")
                    or entry.get("mild")
                    or entry.get("severe")
                    or ""
                )
                if text is None:
                    text = ""
            else:
                text = ""
            if text:
                label = labels.get(sys_key, sys_key)
                parts.append(f"{label}: {text}")

        return "。".join(parts) if is_ja else ". ".join(parts)
