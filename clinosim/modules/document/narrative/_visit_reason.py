"""Outpatient SOAP content by the reason for the visit (Issues #3249, #3251, #3252).

The simulator records the kind of outpatient visit it ran
(``condition_event.visit_type``) and the condition the visit was for
(``condition_event.visit_condition_id``); :func:`visit_kind` maps them to a
kind of ``reference_data/visit_reason_soap.yaml`` (chemotherapy,
post-discharge, post-operative, acute illness, screening, vaccination,
well-child). :func:`kind_lines` renders the kind's lines of one SOAP section
from the visit's CIF data, :func:`vital_findings` words the visit's abnormal
vital signs as a finding linked to the known diagnosis with a plan line, and
:func:`next_visit_line` states the return the kind calls for.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.age_bands import find_age_band, parse_age_band
from clinosim.codes.drugs import medication_matches
from clinosim.countries import country_code
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.locale.localized import localized
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
    NARRATIVE_FEVER_C,
    NARRATIVE_HYPOXEMIA_SPO2,
    NARRATIVE_SEVERE_HYPOXEMIA_SPO2,
)
from clinosim.modules.document.reference_data_loaders import _EnglishLangMap

_REF_FILE = Path(__file__).resolve().parents[1] / "reference_data" / "visit_reason_soap.yaml"

Kind = Literal[
    "chemotherapy",
    "post_discharge",
    "post_operative",
    "acute_illness",
    "screening",
    "vaccination",
    "well_child",
]

# A language map with English text (the fallback language).
_LangText = _EnglishLangMap


class _Lines(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subjective: list[_LangText] = Field(default_factory=list)
    objective: list[_LangText] = Field(default_factory=list)
    assessment: list[_LangText] = Field(default_factory=list)
    plan: list[_LangText] = Field(default_factory=list)


class _VisitKinds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    by_visit_type: dict[str, Kind]
    by_condition: dict[str, Kind]
    post_operative_conditions: list[str]


class _Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assessment: _LangText
    plan: _LangText


class _VitalFindings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tachycardia: dict[
        Literal["af_no_rate_control", "af_on_rate_control", "af_unchanged", "febrile", "default"], _Finding
    ]
    fever: dict[Literal["infection", "default"], _Finding]
    hypoxemia: dict[Literal["known", "default"], _Finding]
    hypoxemia_severe: dict[Literal["known", "default"], _Finding]


class _VitalLinks(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    infection: list[str] = Field(min_length=1)
    atrial_fibrillation: list[str] = Field(min_length=1)
    chronic_cardiopulmonary: list[str] = Field(min_length=1)


class _WellChild(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    development: dict[str, _LangText] = Field(min_length=1)
    guidance: dict[str, _LangText] = Field(min_length=1)
    # Infant (under 12 months) feeding and examination statements by age band
    # (Issue #3566); generic age-appropriate observations, no findings.
    feeding: dict[str, _LangText] = Field(min_length=1)
    exam: dict[str, _LangText] = Field(min_length=1)

    @model_validator(mode="after")
    def _bands(self) -> _WellChild:
        for table in (self.development, self.guidance, self.feeding, self.exam):
            for key in table:
                parse_age_band(key)
        return self


class VisitReasonSoap(BaseModel):
    """Shape of visit_reason_soap.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: dict[str, Any] = Field(default_factory=dict)
    visit_kinds: _VisitKinds
    next_visit: dict[Kind, Literal["chronic", "cycle", "schedule", "none"]]
    next_visit_by_condition: dict[str, Literal["chronic", "cycle", "schedule", "none"]] = Field(default_factory=dict)
    kinds: dict[Kind, _Lines]
    conditions: dict[str, _Lines] = Field(default_factory=dict)
    retinopathy_codes: list[str] = Field(min_length=1)
    vaccine_detail: dict[Literal["dose", "lot", "route", "site"], _LangText]
    vaccine_routes: dict[str, _LangText]
    vaccine_sites: dict[str, _LangText]
    vaccination_country_lines: dict[str, list[_LangText]]
    therapy_by_drug_class: dict[str, Literal["hormonal", "targeted", "immunotherapy"]]
    therapy: dict[Literal["cytotoxic", "hormonal", "targeted", "immunotherapy"], _LangText]
    vital_findings: _VitalFindings
    vital_links: _VitalLinks
    phrases: dict[str, _LangText]
    well_child: _WellChild

    @model_validator(mode="after")
    def _complete(self) -> VisitReasonSoap:
        kinds = set(Kind.__args__)  # type: ignore[attr-defined]
        if set(self.next_visit) != kinds:
            raise ValueError(f"next_visit must name every kind: {sorted(kinds - set(self.next_visit))}")
        unknown = (
            (set(self.conditions) | set(self.next_visit_by_condition))
            - set(self.visit_kinds.by_condition)
            - set(self.visit_kinds.post_operative_conditions)
        )
        if unknown:
            raise ValueError(f"conditions for no mapped visit condition: {sorted(unknown)}")
        return self


def _validate_condition_ids(data: VisitReasonSoap) -> None:
    """Every condition id names a pediatric schedule visit or an encounter
    protocol, and every post-operative condition a disease protocol."""
    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.modules.encounter.protocol import load_encounter_condition
    from clinosim.modules.pediatric.calendar import load_pediatric_schedule

    pediatric = {str(e.get("disease_id") or k) for k, e in load_pediatric_schedule().items()}
    for cid in data.visit_kinds.by_condition:
        if cid in pediatric:
            continue
        try:
            load_encounter_condition(cid)
        except FileNotFoundError as exc:
            raise ValueError(f"visit_reason_soap.yaml: unknown visit condition {cid!r}") from exc
    for disease_id in data.visit_kinds.post_operative_conditions:
        load_disease_protocol(disease_id)


@lru_cache(maxsize=1)
def load_visit_reason_soap() -> VisitReasonSoap:
    """Load and validate visit_reason_soap.yaml. Cached singleton."""
    data = VisitReasonSoap.model_validate(load_validated_yaml(_REF_FILE, VisitReasonSoap))
    _validate_condition_ids(data)
    return data


# ─────────────────────────────────────────────────────────────────────
# Visit kind
# ─────────────────────────────────────────────────────────────────────


def visit_kind(ctx: Any) -> str:
    """The kind of the outpatient visit ``ctx`` describes, "" for a visit
    with none (a chronic follow-up, an encounter-protocol visit)."""
    visit_type = str(getattr(ctx, "visit_type", "") or "")
    condition = str(getattr(ctx, "visit_condition_id", "") or "")
    if not visit_type:
        return ""
    kinds = load_visit_reason_soap().visit_kinds
    kind = kinds.by_condition.get(condition) or kinds.by_visit_type.get(visit_type) or ""
    if kind == "post_discharge" and condition in kinds.post_operative_conditions:
        return "post_operative"
    return kind


def visit_dx(ctx: Any) -> str:
    """The visit's diagnosis code (``clinical_diagnosis.admission_diagnosis_code``)."""
    for dx in getattr(ctx, "diagnoses", None) or []:
        code = str(_o(dx, "admission_diagnosis_code", "") or _o(dx, "discharge_diagnosis_code", "") or "")
        if code:
            return code
    return ""


def _code_matches(code: str, prefixes: list[str]) -> bool:
    bare = code.replace(".", "").upper()
    return any(bare.startswith(p) for p in prefixes)


def _condition_name(code: str, ctx: Any) -> str:
    from clinosim.modules.document.narrative.renderers._shared_helpers import chronic_condition_label

    sex = str(_o(ctx.patient, "sex", "") or "") if ctx.patient is not None else ""
    return chronic_condition_label(code, country_code(ctx.locale), ctx.target_lang, sex) or ""


def _index_disease_label(ctx: Any) -> str:
    """Name of the admission a post-discharge visit follows (its disease
    protocol's primary ICD code)."""
    from clinosim.modules.disease.protocol import load_disease_protocol

    disease_id = str(getattr(ctx, "visit_condition_id", "") or "")
    if not disease_id:
        return ""
    try:
        protocol = load_disease_protocol(disease_id)
    except FileNotFoundError:
        return ""
    code = str((protocol.icd_codes or {}).get("primary") or "")
    return _condition_name(code, ctx) if code else ""


# ─────────────────────────────────────────────────────────────────────
# Values of the kind lines
# ─────────────────────────────────────────────────────────────────────


def _phrase(key: str, lang: str, **kwargs: Any) -> str:
    return localized(load_visit_reason_soap().phrases[key], lang).format(**kwargs)


def _lab_entry(lab: Any, lang: str) -> str:
    from clinosim.codes.ucum import ucum_prose
    from clinosim.locale.loader import lab_display
    from clinosim.modules.document.narrative._localization import _localize_lab_flag, lab_value_text

    raw = str(_o(lab, "lab_name", "") or "")
    unit = str(_o(lab, "unit", "") or "")
    unit_disp = ucum_prose(unit) if unit else ""
    name = lab_display(raw, lang)
    if unit_disp and unit_disp.lower() == str(name).lower():
        unit_disp = ""
    text = f"{name} {lab_value_text(raw, _o(lab, 'value', None), unit, lang)}" + (f" {unit_disp}" if unit_disp else "")
    flag = str(_o(lab, "flag", "") or "")
    return f"{text} [{_localize_lab_flag(flag, lang)}]" if _abnormal(lab) else text


def _abnormal(lab: Any) -> bool:
    return str(_o(lab, "flag", "") or "").upper() not in ("", "N", "NORMAL")


def _labs(ctx: Any, *, known_only: bool = True) -> list[Any]:
    """The visit's lab results with a value; by default only those reported by
    the note's authored time (Issue #3396), ``known_only=False`` every drawn
    test (the names of the tests of a screening visit)."""
    from clinosim.modules.document.narrative._outpatient_results import known_labs

    labs = known_labs(ctx) if known_only else (ctx.lab_results or [])
    return [lab for lab in labs if _o(lab, "lab_name", None) and _o(lab, "value", None) is not None]


def _lab_values(ctx: Any, values: dict[str, Any]) -> None:
    lang = ctx.target_lang
    sep = t("list_sep.serial", lang)
    labs = _labs(ctx)
    if not labs:
        # Tests drawn at the visit and not yet reported are pending, not absent.
        values["labs_pending" if _labs(ctx, known_only=False) else "no_labs"] = ""
        return
    values["labs"] = sep.join(_lab_entry(lab, lang) for lab in labs)
    abnormal = [_lab_entry(lab, lang) for lab in labs if _abnormal(lab)]
    if abnormal:
        values["abnormal"] = sep.join(abnormal)
        values["lab_status"] = _phrase("lab_tail_abnormal", lang, list=values["abnormal"])
        values["screening_labs"] = _phrase("screening_labs_abnormal", lang, list=values["abnormal"])
    else:
        values["all_normal"] = ""
        values["lab_status"] = _phrase("lab_tail_normal", lang)
        values["screening_labs"] = _phrase("screening_labs_normal", lang)


def _imaging_values(ctx: Any, values: dict[str, Any]) -> list[str]:
    """Impressions of the encounter's imaging reports (in the note language)."""
    lang = ctx.target_lang
    texts: list[str] = []
    for study in getattr(ctx, "imaging_studies", None) or []:
        report = _o(study, "report", None) or {}
        text = _o(report, f"impression_text_{lang}", None) or _o(report, "impression_text", None) or ""
        if text:
            texts.append(str(text).strip())
    if texts:
        values["imaging"] = join_sentences(texts, lang)
    return texts


def _screening_items(ctx: Any) -> str:
    from clinosim.locale.loader import imaging_exam_display, lab_display
    from clinosim.modules.document.narrative.renderers._shared_helpers import procedure_prose_name

    lang = ctx.target_lang
    names: list[str] = []
    for lab in _labs(ctx, known_only=False):
        name = lab_display(str(_o(lab, "lab_name", "")), lang)
        if name not in names:
            names.append(name)
    for order in getattr(ctx, "orders", None) or []:
        if str(_o(order, "order_type", "") or "") != "imaging":
            continue
        name = imaging_exam_display(str(_o(order, "display_name", "") or ""), lang)
        if name and name not in names:
            names.append(name)
    for proc in ctx.procedures or []:
        name = procedure_prose_name(proc, lang)
        if name and name not in names:
            names.append(name)
    return t("list_sep.serial", lang).join(names)


def _chemo_values(ctx: Any, values: dict[str, Any]) -> None:
    from clinosim.locale.free_text import localize_drug_name

    lang = ctx.target_lang
    drugs: list[str] = []
    for mar in ctx.medications or []:
        if str(_o(mar, "status", "given") or "given") != "given":
            continue
        name = localize_drug_name(str(_o(mar, "drug_name", "") or ""), lang)
        dose = str(_o(mar, "dose", "") or "")
        if name:
            drugs.append(f"{name} {dose}".strip())
    if drugs:
        values["drugs"] = t("list_sep.serial", lang).join(drugs)


def _visit_regimen(ctx: Any) -> dict[str, Any] | None:
    """The regimen (``chemo_regimens.yaml``) whose drugs were all given at
    the visit, compared by catalog id (``codes.drugs.drug_ref``)."""
    from clinosim.codes.drugs import drug_ref
    from clinosim.locale.loader import load_chemo_regimens

    given = {
        str(_o(m, "drug_id", "") or "") or drug_ref(str(_o(m, "drug_name", "") or "")) for m in ctx.medications or []
    }
    given.discard("")
    if not given:
        return None
    for regimen in (load_chemo_regimens().get("regimens") or {}).values():
        ids = {
            str(o.get("drug_id") or "") or drug_ref(str(o.get("drug") or "")) for o in regimen.get("cycle_orders") or []
        }
        if ids and "" not in ids and ids <= given:
            return dict(regimen)
    return None


def chemo_cycle_days(ctx: Any) -> int | None:
    """Cycle interval (days) of the visit's regimen, None when no regimen matches."""
    regimen = _visit_regimen(ctx)
    return int(regimen.get("cycle_interval_days") or 0) or None if regimen else None


def _therapy_values(ctx: Any, values: dict[str, Any]) -> None:
    data = load_visit_reason_soap()
    regimen = _visit_regimen(ctx) or {}
    therapy = next(
        (
            data.therapy_by_drug_class[c]
            for c in regimen.get("contains_drug_classes") or []
            if c in data.therapy_by_drug_class
        ),
        "cytotoxic",
    )
    text = localized(data.therapy[therapy], ctx.target_lang)  # type: ignore[index]
    values["therapy"] = text
    values["therapy_title"] = text[:1].upper() + text[1:]
    if therapy == "cytotoxic":
        values["cytotoxic"] = ""


def _vaccine_values(ctx: Any, values: dict[str, Any]) -> None:
    from clinosim.codes import display as registry_display
    from clinosim.modules.immunization.engine import vaccine_administration
    from clinosim.modules.observation.pediatric_ranges import age_in_completed_months

    lang = ctx.target_lang
    data = load_visit_reason_soap()
    names: list[str] = []
    details: list[str] = []
    birth = _o(ctx.patient, "date_of_birth", None) if ctx.patient is not None else None
    for imm in getattr(ctx, "immunizations", None) or []:
        if str(_o(imm, "status", "completed") or "completed") != "completed":
            continue
        cvx = str(_o(imm, "vaccine_cvx", "") or "")
        name = registry_display("cvx", cvx, lang) or ""
        if not name:
            continue
        names.append(name)
        parts = [name]
        dose = _o(imm, "dose_number", None)
        if isinstance(dose, int) and dose > 0:
            parts.append(localized(data.vaccine_detail["dose"], lang).format(dose=dose))
        lot = str(_o(imm, "lot_number", "") or "")
        if lot:
            parts.append(localized(data.vaccine_detail["lot"], lang).format(lot=lot))
        given = vaccine_administration(
            country_code(ctx.locale), cvx, age_in_completed_months(birth, _o(imm, "occurrence_date", None))
        )
        if given is not None:
            route = localized(data.vaccine_routes.get(given.route), lang)
            if route:
                parts.append(localized(data.vaccine_detail["route"], lang).format(route=route))
            site = localized(data.vaccine_sites.get(given.site or ""), lang)
            if site:
                parts.append(localized(data.vaccine_detail["site"], lang).format(site=site))
        details.append("".join(parts))
    if names:
        sep = t("list_sep.serial", lang)
        values["vaccine_names"] = sep.join(names)
        values["vaccine_details"] = t("list_sep.period_space", lang).join(details)


def _well_child_values(ctx: Any, values: dict[str, Any]) -> None:
    from clinosim.modules.observation.pediatric_ranges import age_in_completed_months

    lang = ctx.target_lang
    data = load_visit_reason_soap().well_child
    patient = ctx.patient
    enc = ctx.encounter
    if patient is None or enc is None:
        return
    when = _o(enc, "admission_datetime", None)
    months = age_in_completed_months(_o(patient, "date_of_birth", None), when)
    if months is None:
        return
    band = find_age_band(data.development, months)
    if band is not None:
        values["development"] = localized(data.development[band], lang)
    band = find_age_band(data.guidance, months)
    if band is not None:
        values["guidance"] = localized(data.guidance[band], lang)
    _growth_values(ctx, values)
    _infant_values(ctx, values, months)


def _infant_values(ctx: Any, values: dict[str, Any], months: int) -> None:
    """``feeding``, ``exam`` and, for a visit that is not a well-child check,
    ``infant_development`` of an infant visit (Issue #3566): age-banded
    statements from ``well_child.feeding`` / ``exam`` / ``development``; the
    feeding and examination tables cover infants only, so an older child gets
    none of them."""
    lang = ctx.target_lang
    data = load_visit_reason_soap().well_child
    if find_age_band(data.feeding, months) is None:
        return
    for key, table in (("feeding", data.feeding), ("exam", data.exam), ("infant_development", data.development)):
        band = find_age_band(table, months)
        if band is not None:
            values[key] = localized(table[band], lang)


def _growth_values(ctx: Any, values: dict[str, Any]) -> None:
    """``values["growth"]``: the visit's measured weight, height and head
    circumference with their percentiles, from the same derivation the FHIR
    anthropometric Observations use."""
    from clinosim.modules.population.encounter_anthropometry import encounter_anthropometrics, growth_percentiles

    lang = ctx.target_lang
    patient = ctx.patient
    enc = ctx.encounter
    if patient is None or enc is None:
        return
    when = _o(enc, "admission_datetime", None)
    enc_id = str(_o(enc, "encounter_id", "") or "")
    country = country_code(ctx.locale)
    measured = encounter_anthropometrics(patient, enc_id, when, country)
    pct = growth_percentiles(patient, enc_id, when, country)
    parts: list[str] = []
    for key, label, unit in (
        ("weight_kg", "fhir_obs_text.body_weight", "kg"),
        ("height_cm", "fhir_obs_text.body_height", "cm"),
        ("head_circumference_cm", "fhir_obs_text.head_circumference", "cm"),
    ):
        if key not in measured:
            continue
        text = f"{t(label, lang)} {measured[key]:g} {unit}"
        if key in pct:
            text += " " + _phrase("percentile", lang, pct=pct[key])
        parts.append(text)
    if parts:
        values["growth"] = t("list_sep.serial", lang).join(parts)


def _is_child_visit(ctx: Any) -> bool:
    from clinosim.modules.observation.pediatric_ranges import PEDIATRIC_UPPER_AGE_MONTHS, age_in_completed_months

    if ctx.patient is None or ctx.encounter is None:
        return False
    months = age_in_completed_months(
        _o(ctx.patient, "date_of_birth", None), _o(ctx.encounter, "admission_datetime", None)
    )
    return months is not None and months < PEDIATRIC_UPPER_AGE_MONTHS


def _visit_age_months(ctx: Any) -> int | None:
    from clinosim.modules.observation.pediatric_ranges import age_in_completed_months

    if ctx.patient is None or ctx.encounter is None:
        return None
    return age_in_completed_months(
        _o(ctx.patient, "date_of_birth", None), _o(ctx.encounter, "admission_datetime", None)
    )


def kind_values(ctx: Any, kind: str) -> dict[str, Any]:
    """The placeholder values of ``kind``'s lines for the visit."""
    values: dict[str, Any] = {}
    dx = visit_dx(ctx)
    if kind == "chemotherapy":
        cancer = _condition_name(dx, ctx) if dx else ""
        if cancer:
            values["cancer"] = cancer
        _chemo_values(ctx, values)
        _therapy_values(ctx, values)
        _lab_values(ctx, values)
    elif kind in ("post_discharge", "post_operative"):
        index = _index_disease_label(ctx)
        if index:
            values["index"] = index
        _lab_values(ctx, values)
        _imaging_values(ctx, values)
    elif kind == "acute_illness":
        label = _condition_name(dx, ctx) if dx else ""
        if label:
            values["dx"] = label
        if not (getattr(ctx, "discharge_medications", None) or []):
            values["no_rx"] = ""
    elif kind == "screening":
        items = _screening_items(ctx)
        if items:
            values["items"] = items
        _lab_values(ctx, values)
        _imaging_values(ctx, values)
    elif kind == "well_child":
        _well_child_values(ctx, values)
    _vaccine_values(ctx, values)
    if kind != "well_child" and "vaccine_names" in values and _is_child_visit(ctx):
        # Issue #3464: a child's vaccination visit records growth (the visit
        # may be an appended encounter with no visit kind).
        _growth_values(ctx, values)
        # Issue #3566: an infant's vaccination visit also states feeding,
        # development and an examination, as a well-child check does.
        months = _visit_age_months(ctx)
        if months is not None:
            _infant_values(ctx, values, months)
    _retinopathy_values(ctx, values)
    return values


def _retinopathy_values(ctx: Any, values: dict[str, Any]) -> None:
    """The problem-list status of diabetic retinopathy at a retinopathy
    screening visit: ``retinopathy_known`` or ``retinopathy_none`` (empty
    values, which select the line of that case)."""
    if str(getattr(ctx, "visit_condition_id", "") or "") != "diabetic_retinopathy_screening":
        return
    codes = [
        str(_o(c, "code", "") or (c if isinstance(c, str) else ""))
        for c in (_o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient is not None else [])
    ]
    known = any(_code_matches(c, load_visit_reason_soap().retinopathy_codes) for c in codes)
    values["retinopathy_known" if known else "retinopathy_none"] = ""


def _render(entries: list[_LangText], lang: str, values: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for entry in entries:
        try:
            text = localized(entry, lang).format_map(values)
        except KeyError:
            continue
        if text.strip():
            out.append(text.strip())
    return out


def kind_lines(ctx: Any, kind: str, section: str, values: dict[str, Any] | None = None) -> list[str]:
    """The lines of ``section`` for a visit of ``kind``: the kind's own lines,
    then those of the visit condition; a vaccination section for any visit
    at which vaccines were given."""
    data = load_visit_reason_soap()
    values = kind_values(ctx, kind) if values is None else values
    lang = ctx.target_lang
    entries: list[_LangText] = []
    if kind:
        entries.extend(getattr(data.kinds[kind], section))  # type: ignore[index]
        condition = data.conditions.get(str(getattr(ctx, "visit_condition_id", "") or ""))
        if condition is not None:
            entries.extend(getattr(condition, section))
    if kind != "vaccination" and "vaccine_names" in values:
        entries.extend(getattr(data.kinds["vaccination"], section))
    # A line shared by two kinds of one visit (the growth line of a vaccination
    # and a well-child check) is written once (Issue #3566).
    lines = list(dict.fromkeys(_render(entries, lang, values)))
    if section == "plan" and "vaccine_names" in values:
        country_lines = data.vaccination_country_lines.get(country_code(ctx.locale).upper(), [])
        lines.extend(_render(country_lines, lang, values))
    return lines


def join_sentences(sentences: list[str], lang: str) -> str:
    """Sentences as one paragraph: "A. B." / 「A。B。」."""
    period = t("list_sep.period", lang)
    bare = [s.strip().removesuffix(period) for s in sentences if s.strip()]
    return t("list_sep.period_space", lang).join(bare) + period if bare else ""


def known_conditions_tail(labels: list[str], lang: str) -> str:
    """ " Known conditions: a, b." — the chronic problems of a visit made for
    another reason."""
    return _phrase("known_conditions", lang, list=t("list_sep.serial", lang).join(labels))


# ─────────────────────────────────────────────────────────────────────
# Vital-sign findings (Issue #3251)
# ─────────────────────────────────────────────────────────────────────


def _rate_control_classes() -> tuple[str, ...]:
    """Drug classes that control the ventricular rate in atrial fibrillation
    (``ventricular_rate.rate_control_classes`` of the AF protocol, Issue #3546)."""
    from clinosim.modules.disease.protocol import load_disease_protocol

    spec = load_disease_protocol("atrial_fibrillation_rvr").ventricular_rate
    return tuple(spec.rate_control_classes) if spec is not None else ()


def vital_findings(
    ctx: Any,
    hr: float | None,
    temp: float | None,
    spo2: float | None,
    tachycardic: bool,
    medications: Sequence[Any] = (),
    rx_unchanged: bool = True,
) -> list[tuple[str, str]]:
    """``(assessment item, plan line)`` of each abnormal vital sign of the
    visit, linked to the diagnosis already known: tachycardia in atrial
    fibrillation or with fever, a fever explained by an infection the visit
    diagnosed, hypoxemia in a known chronic lung or heart condition."""
    data = load_visit_reason_soap()
    lang = ctx.target_lang
    links = data.vital_links
    codes = [
        str(_o(c, "code", "") or (c if isinstance(c, str) else ""))
        for c in (_o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient is not None else [])
    ]
    febrile = temp is not None and temp >= NARRATIVE_FEVER_C
    out: list[tuple[str, str]] = []

    def _add(finding: Any, **kwargs: Any) -> None:
        out.append(
            (localized(finding.assessment, lang).format(**kwargs), localized(finding.plan, lang).format(**kwargs))
        )

    if hr is not None and tachycardic:
        if any(_code_matches(c, links.atrial_fibrillation) for c in codes):
            # Issue #3546: the plan line states an action only when the
            # medication list holds it: no rate-control drug -> starting one is
            # to be considered; one on the list and the prescription changed ->
            # a step-up is to be considered; one on the list and the
            # prescription unchanged -> the regimen continues.
            classes = _rate_control_classes()
            if not any(medication_matches(m, classes=classes) for m in medications):
                variant = "af_no_rate_control"
            elif rx_unchanged:
                variant = "af_unchanged"
            else:
                variant = "af_on_rate_control"
        elif febrile:
            variant = "febrile"
        else:
            variant = "default"
        _add(data.vital_findings.tachycardia[variant], hr=int(round(hr)))  # type: ignore[index]
    if spo2 is not None and spo2 < NARRATIVE_HYPOXEMIA_SPO2:
        table = (
            data.vital_findings.hypoxemia_severe
            if spo2 < NARRATIVE_SEVERE_HYPOXEMIA_SPO2
            else data.vital_findings.hypoxemia
        )
        known = next((c for c in codes if _code_matches(c, links.chronic_cardiopulmonary)), "")
        condition = _condition_name(known, ctx) if known else ""
        if condition:
            _add(table["known"], spo2=spo2, condition=condition)
        else:
            _add(table["default"], spo2=spo2)
    if febrile and temp is not None:
        dx = _infection_dx(ctx, links.infection)
        if dx:
            _add(data.vital_findings.fever["infection"], temp=temp, dx=dx)
        else:
            _add(data.vital_findings.fever["default"], temp=temp)
    return out


def _infection_dx(ctx: Any, prefixes: list[str]) -> str:
    """Name of the infection the visit diagnosed (the visit diagnosis, or the
    index admission of a post-discharge visit), "" when it is not one."""
    code = visit_dx(ctx)
    if code and _code_matches(code, prefixes):
        return _condition_name(code, ctx)
    if visit_kind(ctx) in ("post_discharge", "post_operative"):
        from clinosim.modules.disease.protocol import load_disease_protocol

        try:
            primary = str((load_disease_protocol(str(ctx.visit_condition_id)).icd_codes or {}).get("primary") or "")
        except FileNotFoundError:
            return ""
        if primary and _code_matches(primary, prefixes):
            return _condition_name(primary, ctx)
    return ""


# ─────────────────────────────────────────────────────────────────────
# Next visit
# ─────────────────────────────────────────────────────────────────────


def next_visit_line(ctx: Any, kind: str) -> str | None:
    """The plan's next-visit line of a visit of ``kind``: ``None`` to keep the
    chronic follow-up line, "" for no scheduled return."""
    if not kind:
        return None
    data = load_visit_reason_soap()
    condition = str(getattr(ctx, "visit_condition_id", "") or "")
    mode = data.next_visit_by_condition.get(condition) or data.next_visit[kind]  # type: ignore[index]
    lang = ctx.target_lang
    if mode == "none":
        return ""
    if mode == "cycle":
        days = chemo_cycle_days(ctx)
        return _phrase("next_cycle", lang, days=days) if days else None
    if mode == "schedule":
        months = _schedule_months(condition)
        return _phrase("next_schedule", lang, months=months) if months else None
    return None


def _schedule_months(condition: str) -> int | None:
    """Months between visits of a pediatric schedule visit: 12 over its mean
    yearly visit count (``pediatric_schedule.yaml`` ``visits_per_year``)."""
    from clinosim.modules.pediatric.calendar import load_pediatric_schedule

    for key, entry in load_pediatric_schedule().items():
        if str(entry.get("disease_id") or key) != condition:
            continue
        counts = [int(n) for n in entry.get("visits_per_year") or [] if int(n) > 0]
        if counts:
            return max(1, round(12 / (sum(counts) / len(counts))))
    return None
