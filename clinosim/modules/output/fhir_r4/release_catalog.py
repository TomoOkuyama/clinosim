"""Catalog of every code a release can emit, per country (Issue #3763).

The per-dataset used-codes catalog (``lib/used_codes.py``) lists what one
dataset contains. This module lists what the version can emit, in the same
line format (without the usage fields ``count`` and ``patients``), so a
consumer can prepare master tables before generating data and is not surprised
by a new code when the seed or the population changes.

How it is built. The reference data is walked through the functions the
simulator and the FHIR builders resolve codes with: the drug catalog and the
country drug mapping through ``_resolve_medication_concept`` and
``build_route_concept``, the lab names through ``lab_observation_coding``, the
microbiology tests through ``resolve_culture_code`` /
``resolve_susceptibility_code``, concepts through ``dual_slot_concept``. Each
code becomes a minimal FHIR resource of the shape the builder emits, passes
through the export's own ``_finalize_resource`` (country profiles, dual
coding), and is fed to the same ``UsedCodesCatalog`` the export uses, so a line
means the same thing in both catalogs.

The result is an upper bound: it lists what the reference data allows, not
what a given seed draws. A medication is listed with every route text its
route class admits. Observation codes that no resolver table attributes to a
more specific kind (the LOINC codes the builders write as literals) are listed
as kind ``observation``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from clinosim.countries import lang_for
from clinosim.country_profile import country_profile
from clinosim.modules.output.fhir_r4.lib.used_codes import UsedCodesCatalog

Emit = Callable[[dict[str, Any]], None]


def _concept(system_key: str, code: str, lang: str) -> dict[str, Any]:
    from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept

    return dual_slot_concept(system_key, code, lang)


def _diagnoses(emit: Emit, country: str, lang: str) -> None:
    """Every code of the country's diagnosis system, in a Condition built from
    the builders' own skeleton (``build_diagnosis_codeable_concept``)."""
    from clinosim.codes import code_system
    from clinosim.codes.icd10 import icd10_system
    from clinosim.modules.output.fhir_r4.conditions.conditions import (
        _condition_skeleton,
        _ConditionContext,
        _history_of_pregnancy_code,
    )

    ctx = _ConditionContext(patient_id="pt-release", country=country, encounters=[], deceased=False, patient_sex="")
    system = code_system(icd10_system(country))
    assert system is not None

    def condition(code: str) -> dict[str, Any]:
        return _condition_skeleton(
            ctx,
            condition_id="release",
            structural_key=f"release-{code}",
            diagnosis_type=None,
            clinical_status="active",
            category="problem-list-item",
            mapped_code=code,
        )

    for code in system.codes:
        emit(condition(code))
    past_birth = condition("")
    past_birth["code"] = _history_of_pregnancy_code(lang)
    emit(past_birth)


def _procedures(emit: Emit, country: str, lang: str) -> None:
    from clinosim.codes import code_system, system_key_for
    from clinosim.codes.snomed import snomed_phrase_codes

    key = system_key_for("procedure", country)
    system = code_system(key)
    assert system is not None
    for code in system.codes:
        emit({"resourceType": "Procedure", "code": _concept(key, code, lang)})
    from clinosim.codes.snomed import snomed_map
    from clinosim.locale.loader import load_clinician_roles

    snomed = [*snomed_phrase_codes(), *snomed_map("newborn_screen").values()]
    snomed += [str(r["rehab_session_snomed"]) for r in load_clinician_roles().values() if r.get("rehab_session_snomed")]
    for code in dict.fromkeys(snomed):
        emit({"resourceType": "Procedure", "code": _concept("snomed-ct", code, lang)})


def _documents(emit: Emit, country: str, lang: str) -> None:
    from clinosim.modules.document.narrative.registry import specs_for_country

    for spec in specs_for_country(country):
        emit({"resourceType": "DocumentReference", "type": _concept("loinc", spec.loinc_code, lang)})


def _vaccines(emit: Emit, country: str, lang: str) -> None:
    from clinosim.modules.immunization.engine import load_schedule
    from clinosim.modules.immunization.enricher import ed_vaccine_cvx

    cvx: dict[str, None] = dict.fromkeys(ed_vaccine_cvx())
    for vaccine in load_schedule(country).values():
        cvx[str(vaccine["cvx"])] = None
        for product in vaccine.get("products") or []:
            cvx[str(product["cvx"])] = None
    for code in cvx:
        emit({"resourceType": "Immunization", "vaccineCode": _concept("cvx", code, lang)})


def _allergens(emit: Emit, country: str, lang: str) -> None:
    from clinosim.modules.allergy.engine import country_allergen_code, load_allergen_config, load_allergens

    codes = [str(e["allergen_code"]) for entries in load_allergens().values() for e in entries]
    codes.append(str(load_allergen_config()["nka"]["allergen_code"]))
    for code in dict.fromkeys(codes):
        own = country_allergen_code(code, country)
        key, value = own if own else ("snomed-ct", code)
        emit({"resourceType": "AllergyIntolerance", "code": _concept(key, value, lang)})


def _imaging(emit: Emit, country: str, lang: str) -> None:
    # A JP Core ImagingStudy omits procedureCode (its binding cannot be met by
    # text), so only the other countries list imaging codes.
    if country_profile(country).uses("jp_core"):
        return
    from clinosim.modules.imaging.engine import load_body_sites

    for body_site in load_body_sites().values():
        for proc in (body_site.get("procedure_codes") or {}).values():
            if proc.get("loinc"):
                emit({"resourceType": "ImagingStudy", "procedureCode": [_concept("loinc", proc["loinc"], lang)]})


def _lab_names() -> list[str]:
    """Every lab name a country mapping lists: a name one country maps is still
    an analyte the other country reports by its local or LOINC code."""
    from clinosim.country_profile import supported_countries
    from clinosim.locale.loader import load_code_mapping

    return sorted({name for cc in supported_countries() for name in load_code_mapping("lab", cc)})


def _labs(emit: Emit, country: str, lang: str) -> None:
    from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation

    for name in _lab_names():
        result = {"lab_name": name, "value": 1.0, "unit": "", "result_datetime": "2026-01-01T00:00:00"}
        obs = _build_lab_observation(
            {"display_name": name}, result, "pt-release", 0, country, encounter_id="enc-release"
        )
        if obs is not None:
            emit(obs)


def _microbiology(emit: Emit, country: str, lang: str) -> None:
    from clinosim.codes.snomed_concepts import NO_GROWTH
    from clinosim.modules.observation.microbiology import (
        antibiotic_loinc_lookup,
        culture_test_loincs,
        organism_snomed_codes,
    )
    from clinosim.modules.output.fhir_r4.labs.microbiology import (
        MB_ORG_KEY_SYSTEM,
        resolve_culture_code,
        resolve_susceptibility_code,
    )

    category = [_concept("hl7-observation-category", "laboratory", lang)]
    tests = [resolve_culture_code(spec, loinc, country) for spec, loinc in culture_test_loincs().items()]
    tests += [resolve_susceptibility_code(loinc, country) for loinc in antibiotic_loinc_lookup().values()]
    for code, key in dict.fromkeys(tests):
        emit({"resourceType": "Observation", "category": category, "code": _concept(key, code, lang)})
    culture_key = resolve_culture_code("blood", culture_test_loincs()["blood"], country)
    isolates = [*organism_snomed_codes(), NO_GROWTH]
    for code in isolates:
        emit(
            {
                "resourceType": "Observation",
                "identifier": [{"system": MB_ORG_KEY_SYSTEM, "value": "release"}],
                "category": category,
                "code": _concept(culture_key[1], culture_key[0], lang),
                "valueCodeableConcept": _concept("snomed-ct", code, lang),
            }
        )


def _observations(emit: Emit, country: str, lang: str) -> None:
    """Observation codes the builders write from tables and constants rather
    than from the lab mapping: vital signs, nursing scores and the rest."""
    from clinosim.codes import code_system
    from clinosim.codes.loinc import loinc_map
    from clinosim.codes.snomed_concepts import NEWS2_SCALE
    from clinosim.modules.document.narrative.registry import load_document_type_specs, load_section_catalog
    from clinosim.modules.imaging.engine import load_body_sites
    from clinosim.modules.output.fhir_r4.labs import _reference_ranges as rr

    vitals = [v.loinc for v in vars(rr).values() if isinstance(v, rr.VitalSignReferenceRange)]
    vitals += [rr.BP_SYSTOLIC.loinc, rr.BP_DIASTOLIC.loinc, "85354-9"]
    vitals += list(loinc_map("anthropometric").values())
    vital_cat = [_concept("hl7-observation-category", "vital-signs", lang)]
    for code in dict.fromkeys(vitals):
        emit({"resourceType": "Observation", "category": vital_cat, "code": _concept("loinc", code, lang)})
    survey_cat = [_concept("hl7-observation-category", "survey", lang)]
    emit(
        {
            "resourceType": "Observation",
            "category": survey_cat,
            "valueInteger": 0,
            "code": {
                "coding": [
                    _concept("clinosim-nursing-scores", "NEWS2", lang)["coding"][0],
                    _concept("snomed-ct", NEWS2_SCALE, lang)["coding"][0],
                ]
            },
        }
    )
    from clinosim.modules.code_status.engine import load_reference
    from clinosim.modules.output.fhir_r4.labs.stage_scale_observations import _SCALE_SPECS

    emit(
        {"resourceType": "Observation", "code": _concept("snomed-ct", str(load_reference()["observable_snomed"]), lang)}
    )
    for scale in _SCALE_SPECS.values():
        if scale.snomed:
            emit({"resourceType": "Observation", "code": _concept("snomed-ct", scale.snomed, lang)})
    elsewhere = {spec.loinc_code for spec in load_document_type_specs().values()}
    elsewhere |= {e.loinc for e in load_section_catalog().values() if e.loinc}
    for body_site in load_body_sites().values():
        elsewhere |= {p["loinc"] for p in (body_site.get("procedure_codes") or {}).values() if p.get("loinc")}
    loinc = code_system("loinc")
    assert loinc is not None
    for code in loinc.codes:
        if code not in elsewhere:
            emit({"resourceType": "Observation", "code": _concept("loinc", code, lang)})


def _medication_names() -> list[str]:
    """Drug names orders carry: the catalog's English names and the US code mapping's."""
    from clinosim.codes.drugs import all_drug_ids, get_drug
    from clinosim.country_profile import supported_countries
    from clinosim.locale.loader import load_code_mapping

    names = {rec.names["en"] for rec in map(get_drug, all_drug_ids()) if rec is not None}
    mapped = {name for cc in supported_countries() for name in load_code_mapping("drug", cc)}
    return sorted({*names, *mapped})


def _route_tokens() -> list[str]:
    """The order routes of the drug resolvers: the route vocabulary, the routes
    the route translation table names, and the route abbreviations the route
    classes list; of these, the ones that name a route class."""
    from clinosim.codes.drugs import class_routes, route_class
    from clinosim.modules.output.fhir_r4.lib.localization import ROUTE_TEXT
    from clinosim.modules.output.fhir_r4.lib.reference_data import KNOWN_ROUTE_VOCABULARY

    abbreviations = {r for routes in class_routes().values() for r in routes if r.isascii() and r == r.upper()}
    tokens = {*KNOWN_ROUTE_VOCABULARY, *ROUTE_TEXT.entries(), *abbreviations}
    return sorted(t for t in tokens if route_class(t))


def _medications(emit: Emit, country: str, lang: str) -> None:
    """Every drug name with every order route, resolved as an order is, plus
    each RxNorm product (SCD) of the drug for a dose of it."""
    from clinosim.codes.drugs import find_drug, route_class, rxnorm_scd_products
    from clinosim.modules.output.fhir_r4.lib.dosage import build_route_concept
    from clinosim.modules.output.fhir_r4.medications.medications import (
        _apply_rxnorm_scd,
        _resolve_medication_concept,
    )

    def medication_request(concept: dict[str, Any], token: str, dose: dict[str, Any] | None = None) -> dict[str, Any]:
        dosage: dict[str, Any] = {}
        route = build_route_concept(token, country)
        if route:
            dosage["route"] = route
        if dose:
            dosage["doseAndRate"] = [{"doseQuantity": dose}]
        return {
            "resourceType": "MedicationRequest",
            "medicationCodeableConcept": concept,
            "dosageInstruction": [dosage],
        }

    tokens = _route_tokens()
    for name in _medication_names():
        record = find_drug(name)
        products = rxnorm_scd_products(record.drug_id) if record else {}
        for token in tokens:
            concept, _note = _resolve_medication_concept(name, "", country, route=token)
            emit(medication_request(concept, token))
            for _rxcui, strength, unit in products.get(route_class(token), ()):
                scd_request = medication_request(concept, token, {"value": strength, "unit": unit, "code": unit})
                scd_request["medicationCodeableConcept"] = {**concept, "coding": [dict(c) for c in concept["coding"]]}
                _apply_rxnorm_scd(scd_request, country)
                emit(scd_request)


def build_release_catalog(country: str) -> UsedCodesCatalog:
    """The catalog of every code the version can emit for ``country``."""
    from clinosim.modules.output.fhir_r4.builder import _finalize_resource

    catalog = UsedCodesCatalog(release=True)
    lang = lang_for(country)
    counter = 0

    def emit(resource: dict[str, Any]) -> None:
        nonlocal counter
        counter += 1
        resource["id"] = f"release-{counter}"
        specimen = _finalize_resource(resource, country, {})
        if specimen is not None:
            catalog.observe(specimen)
        catalog.observe(resource)
        catalog.end_bundle()

    providers: Iterable[Callable[[Emit, str, str], None]] = (
        _diagnoses,
        _procedures,
        _documents,
        _vaccines,
        _allergens,
        _imaging,
        _labs,
        _microbiology,
        _observations,
        _medications,
    )
    for provider in providers:
        provider(emit, country, lang)
    return catalog


def _line_key(line: dict[str, Any]) -> tuple[Any, ...]:
    return (line["kind"], line["resource"], line["element"], line["system"], line["code"], line.get("route"))


# Attributes whose change between two releases matters to a consumer's master
# tables: the display and the units.
_DIFF_ATTRIBUTES = ("display", "units", "dose_units")


def diff_catalogs(old: Iterable[dict[str, Any]], new: Iterable[dict[str, Any]]) -> dict[str, list[Any]]:
    """The difference between two release catalogs: ``added`` and ``removed``
    lines, and ``changed`` ``(old line, new line)`` pairs whose display or unit
    differs. Lines are matched on ``(kind, resource, element, system, code, route)``."""
    old_by_key = {_line_key(line): line for line in old}
    new_by_key = {_line_key(line): line for line in new}
    changed = [
        (old_by_key[k], new_by_key[k])
        for k in sorted(old_by_key.keys() & new_by_key.keys(), key=str)
        if any(old_by_key[k].get(a) != new_by_key[k].get(a) for a in _DIFF_ATTRIBUTES)
    ]
    return {
        "added": [new_by_key[k] for k in sorted(new_by_key.keys() - old_by_key.keys(), key=str)],
        "removed": [old_by_key[k] for k in sorted(old_by_key.keys() - new_by_key.keys(), key=str)],
        "changed": changed,
    }


def format_diff(country: str, previous: str, diff: dict[str, list[Any]], limit: int = 50) -> str:
    """Markdown for release notes: counts, then up to ``limit`` lines of each kind of difference."""

    def label(line: dict[str, Any]) -> str:
        route = f" via {line['route']}" if line.get("route") else ""
        return f"`{line['kind']}` {line['system']} `{line['code']}`{route} {line.get('display') or ''}".rstrip()

    out = [
        f"## {country} code catalog changes since {previous}",
        "",
        f"{len(diff['added'])} added, {len(diff['removed'])} removed, "
        f"{len(diff['changed'])} with a changed display or unit.",
    ]
    for title, rows in (("Added", diff["added"]), ("Removed", diff["removed"])):
        if rows:
            out += ["", f"{title}:", ""]
            out += [f"- {label(line)}" for line in rows[:limit]]
            if len(rows) > limit:
                out.append(f"- ... and {len(rows) - limit} more")
    if diff["changed"]:
        out += ["", "Changed:", ""]
        for old_line, new_line in diff["changed"][:limit]:
            changes = [
                f"{a}: {old_line.get(a)} -> {new_line.get(a)}"
                for a in _DIFF_ATTRIBUTES
                if old_line.get(a) != new_line.get(a)
            ]
            out.append(f"- {label(new_line)} ({'; '.join(changes)})")
        if len(diff["changed"]) > limit:
            out.append(f"- ... and {len(diff['changed']) - limit} more")
    return "\n".join(out) + "\n"
