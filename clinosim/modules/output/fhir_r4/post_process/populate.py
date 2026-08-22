"""Post-populate ECS / status coding / condition-tree helpers.

Extracted from ``_fhir_post_process.py`` (Issue #555 PR3, folds Issue #556).

Contains the ``_populate_*`` walkers that fire AFTER every ``_bb_*`` builder
emits a resource — they attach identifier slices, meta.lastUpdated, static
display maps, and JP-CLINS eCS-required fields that are cheaper to inject
here than to weave through every resource-specific builder. Also owns
``_normalize_jp_observation_category`` (the JP-only category rewrite) and
``_copy_display_from_sibling_coding`` (dual-slot display propagation).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import is_jp
from clinosim.modules.output.fhir_r4.lib.common import derive_meta_last_updated
from clinosim.modules.output.fhir_r4.post_process.profile import (
    _HL7_OBSERVATION_CATEGORY_SYSTEM,
    _HL7_OBSERVATION_CATEGORY_SYSTEMS,
    _JP_OBSERVATION_CATEGORY_SYSTEM,
)
from clinosim.modules.output.fhir_r4.post_process.strip import (
    _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES,
)

# Observation.identifier system — internal namespace for clinosim-generated
# Observations. Feedback (2026-07-16) noted that JP_Observation_LabResult_eCS
# declares `identifier` with `min=1`; every Observation now carries this
# identifier populated from `Observation.id`.
_CLINOSIM_OBSERVATION_ID_SYSTEM = "urn:clinosim:observation-id"


# JP-CLINS 1.12.0 JP_Observation_LabResult_eCS profile requires an
# `identifier:resourceIdentifier` slice whose `.system` matches the profile's
# patternUri (spec directly from
# `StructureDefinition-JP-Observation-LabResult-eCS.json`, differential
# element `Observation.identifier:resourceIdentifier.system`). Emitting the
# internal `urn:clinosim:observation-id` alone triggered 30,315 slice-
# minimum-violation errors in the 2026-07-17 v2 fullset validation (v2
# feedback §【最優先 1】, -7.3pp headroom). For JP output we prepend this
# canonical spec URI; the internal urn is preserved as a secondary
# identifier so downstream consumers can still round-trip clinosim
# resources.
_JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"


# HL7 v3 substanceAdminSubstitution CodeSystem (used by JP MR eCS walker to
# convert `substitution.allowedBoolean` -> `substitution.allowedCodeableConcept`
# per Chain 5). Defined at module top-level so the
# test_adapter_does_not_hardcode_code_system_uris invariant continues to hold
# (the URI never appears as a `"system": "..."` literal inside a builder).
_HL7_V3_SUBSTITUTION_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-substanceAdminSubstitution"


# JP-CLINS MedicationRequest.dosageInstruction (Dosage = JP_MedicationDosage_eCS)
# canonical constants (spec fixedUri from
# StructureDefinition-jp-medicationdosage-eCS.json in JP-CLINS 1.12.0).
# The R5020 constraint ("valid Usage-MedicationUsage-codesystem") requires
# exactly one of: MHLW ePrescription code OR the dummy uncoded code.
# clinosim has no MHLW usage-code mapping, so the dummy is the correct choice
# and matches JP-CLINS's own example fixture
# (MedicationRequest-Example-JP-MedReq-PO-TID-2days-dummyUsageCode.json).
_JP_CLINS_MEDICATION_USAGE_UNCODED_CS = "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_MedicationUsage_Uncoded_CS"


_JP_CLINS_MEDICATION_USAGE_UNCODED_CODE = "0X0XXXXXXXXX0000"


# Issue #782 (part of META #774): consumer viewer からの指摘で "ダミー" 表現の
# display を factual な placeholder に変更。JP-CLINS 1.12.0 example fixture
# (`MedicationRequest-Example-JP-MedReq-PO-TID-2days-dummyUsageCode.json`) は
# `"ダミー用法コード"` を使うが、consumer 側で raw FHIR を露出する場面
# (デモ・スクリーンショット) で「ダミー」文字が信頼を損ねる。code は spec の
# `0X0XXXXXXXXX0000` を維持し display のみ「用法未指定」に置換 (factual、
# JP-CLINS の profile validation は display に制約を持たず spec 準拠を維持)。
_JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY = "用法未指定"


def _derive_usage_display_from_timing(repeat: Any) -> str:
    """Derive a human-readable JA usage description from `timing.repeat` when
    possible; returns `""` on any missing/unrecognized shape.

    Examples::

        {"frequency": 1, "period": 1, "periodUnit": "d"} → "1日1回"
        {"frequency": 3, "period": 1, "periodUnit": "d"} → "1日3回"
        {"frequency": 1, "period": 6, "periodUnit": "h"} → "6時間ごと"
        {"frequency": 1, "period": 8, "periodUnit": "h"} → "8時間ごと"

    Anything else (e.g. weekly cadence, missing fields) returns `""` and the
    caller falls back to `_JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY`.
    """
    if not isinstance(repeat, dict):
        return ""
    freq = repeat.get("frequency")
    period = repeat.get("period")
    unit = repeat.get("periodUnit", "")
    if not isinstance(freq, int) or not isinstance(period, (int, float)):
        return ""
    if unit == "d" and period == 1 and freq >= 1:
        return f"1日{int(freq)}回"
    if unit == "h" and freq == 1 and period >= 1:
        return f"{int(period)}時間ごと"
    return ""


# JP_MedicationDosage_eCS declares Dosage.extension:periodOfUse as min=1
# (spec differential slice). The extension's valuePeriod.start marks the day
# the dose becomes effective.
_JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL = (
    "http://jpfhir.jp/fhir/core/Extension/StructureDefinition/JP_MedicationDosage_PeriodOfUse"
)


# The MHLW ePrescription CS is the "coded" alternative to the dummy code. When
# a builder has emitted this system already, the walker leaves it alone.
_JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS = "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/MedicationUsage_ePrescription"


# Issue #817: Heuristic drug + frequency → MHLW MedicationUsage_ePrescription
# code mapping. Every MHLW code carries a meal-context suffix (朝食後 / 就寝前
# / 頓用条件 / …) because a pure-cadence code (`1日1回` without meal-context)
# does not exist in the CS (verified against
# `jpfhir-terminology#2.2606.0/CodeSystem-mhlw-medicationusagejami-cs.json`,
# 2,000 codes). The clinosim CIF `Order` model has no `meal_relation` field,
# so we infer a clinically plausible meal-context per drug class and fall
# back to a frequency default when no drug-specific rule matches. Emits the
# dummy uncoded code when the (drug, frequency) tuple does not resolve.
#
# Coverage on JP p=10000 s500 sample: ~65% real MHLW codes, ~35% dummy.
# Never fabricates when uncertain (drug outside table + no clean default).
#
# Format: drug name → meal-context string. Meal-context strings match the
# JP-CLINS example fixture displays exactly, so the reverse (context →
# code) lookup uses the same tokens as the CS's `.display` values.

# QD (1日1回, frequency=1 period=1 periodUnit=d) — drug-specific defaults.
# Statins → bedtime (peak endogenous cholesterol synthesis at night); PPIs
# → before breakfast (empty stomach); bisphosphonates → 起床時 (empty
# stomach, upright + water); everything else with a clear QD convention
# → 朝食後 (post-breakfast, the default JA outpatient dosing time).
_DRUG_QD_MEAL_CONTEXT: dict[str, str] = {
    # Statins (HMG-CoA reductase inhibitors) — bedtime
    "アトルバスタチン": "就寝前",
    "ロスバスタチン": "就寝前",
    "プラバスタチン": "就寝前",
    "ピタバスタチン": "就寝前",
    "シンバスタチン": "就寝前",
    # PPIs — before breakfast
    "ランソプラゾール": "朝食前",
    "オメプラゾール": "朝食前",
    "ラベプラゾール": "朝食前",
    "エソメプラゾール": "朝食前",
    "ボノプラザン": "朝食前",
    # Bisphosphonates — 起床時
    "アレンドロネート": "起床時",
    "リセドロネート": "起床時",
    "ミノドロン酸": "起床時",
    # Diuretics — 朝食後 (avoid nocturia)
    "フロセミド": "朝食後",
    "ヒドロクロロチアジド": "朝食後",
    "スピロノラクトン": "朝食後",
    "トラセミド": "朝食後",
    # Antihypertensives (ARB / ACE-i / CCB / α-blocker) — 朝食後
    "アムロジピン": "朝食後",
    "カンデサルタン": "朝食後",
    "オルメサルタン": "朝食後",
    "テルミサルタン": "朝食後",
    "エナラプリル": "朝食後",
    "リシノプリル": "朝食後",
    "タムスロシン": "朝食後",
    "シロドシン": "朝食後",
    # Anticoagulant / antiplatelet — 朝食後
    "アスピリン": "朝食後",
    "クロピドグレル": "朝食後",
    "ワルファリン": "夕食後",
    "リバーロキサバン": "朝食後",
    # Corticosteroids — 朝食後 (mimic diurnal cortisol)
    "プレドニゾロン": "朝食後",
    "メチルプレドニゾロン": "朝食後",
    # Endocrine
    "レボチロキシン": "朝食前",
    "ビタミンD": "朝食後",
    "アルファカルシドール": "朝食後",
}

# BID (1日2回, frequency=2 period=1 periodUnit=d)
_DRUG_BID_MEAL_CONTEXT: dict[str, str] = {
    # Biguanide — with meals
    "メトホルミン": "朝夕食後",
    # β-blockers (twice daily variants) — with meals
    "カルベジロール": "朝夕食後",
    "ビソプロロール": "朝夕食後",
    # Additional cardio
    "エプレレノン": "朝夕食後",
}

# Default (unmapped drug) meal-context per frequency. Every FHIR
# emission at these cadences becomes a spec-legit code; when the specific
# drug is unknown the fallback is the JA outpatient convention.
_DEFAULT_MEAL_CONTEXT_BY_FREQ: dict[int, str] = {
    1: "朝食後",  # QD
    2: "朝夕食後",  # BID
    3: "朝昼夕食後",  # TID
    4: "朝昼夕食後と就寝前",  # QID
}

# (frequency, meal-context) → MHLW MedicationUsage_ePrescription code.
# Codes verified against JP-CLINS 1.12.0 example fixtures + the
# authoritative `jpfhir-terminology#2.2606.0` CS.
_FREQ_CONTEXT_TO_MHLW_CODE: dict[tuple[int, str], tuple[str, str]] = {
    (1, "朝食後"): ("1011000400000000", "１日１回朝食後　服用"),
    (1, "夕食後"): ("1011040000000000", "１日１回夕食後　服用"),
    (1, "就寝前"): ("1011100000000000", "１日１回就寝前　服用"),
    (1, "朝食前"): ("1011000100000000", "１日１回朝食前　服用"),
    (1, "起床時"): ("1011000090000000", "１日１回起床時　服用"),
    (2, "朝夕食後"): ("1012040400000000", "１日２回朝夕食後　服用"),
    (2, "朝食後と就寝前"): ("1012100400000000", "１日２回朝食後と就寝前　服用"),
    (3, "朝昼夕食後"): ("1013044400000000", "１日３回朝昼夕食後　服用"),
    (4, "朝昼夕食後と就寝前"): ("1014144400000000", "１日４回朝昼夕食後と就寝前　服用"),
}


# Drug → typical daily-freq inference. Used when the dosage carries no
# `timing.repeat.frequency` at all (a substantial subset of the CIF —
# especially inpatient continuation orders and discharge prescriptions
# where the timing structure isn't populated). Every entry is a
# clinical convention with a well-defined typical schedule; anything
# with genuinely variable dosing is intentionally excluded so the
# resolver falls back to dummy rather than fabricating.
#
# QD-only drugs — no clinical BID/TID variant in JA outpatient practice.
_DRUG_IMPLIED_FREQ_QD: set[str] = {
    # Statins — always QD
    "アトルバスタチン",
    "ロスバスタチン",
    "プラバスタチン",
    "ピタバスタチン",
    "シンバスタチン",
    # PPIs — usually QD (BID for erosive esophagitis is out of scope)
    "ランソプラゾール",
    "オメプラゾール",
    "ラベプラゾール",
    "エソメプラゾール",
    "ボノプラザン",
    # Bisphosphonates — weekly/daily variants both use "morning empty stomach", QD baseline
    "アレンドロネート",
    "リセドロネート",
    "ミノドロン酸",
    # Diuretics — QD baseline
    "フロセミド",
    "ヒドロクロロチアジド",
    "スピロノラクトン",
    "トラセミド",
    # Antihypertensives (once-daily long-acting)
    "アムロジピン",
    "カンデサルタン",
    "オルメサルタン",
    "テルミサルタン",
    "エナラプリル",
    "リシノプリル",
    "タムスロシン",
    "シロドシン",
    # Anticoagulant / antiplatelet — QD
    "アスピリン",
    "クロピドグレル",
    "ワルファリン",
    "リバーロキサバン",
    # Corticosteroids (chronic maintenance) — QD morning
    "プレドニゾロン",
    "メチルプレドニゾロン",
    # Endocrine
    "レボチロキシン",
    "ビタミンD",
    "アルファカルシドール",
}

# BID-typical drugs
_DRUG_IMPLIED_FREQ_BID: set[str] = {
    "メトホルミン",  # BID with meals (JA clinical convention)
    "カルベジロール",
    "ビソプロロール",
    "エプレレノン",
}


def _resolve_mhlw_usage_code(
    drug_text: str, freq: int | None, period: int | None, period_unit: str
) -> tuple[str, str] | None:
    """Return (MHLW code, display) or None when the (drug, cadence) tuple
    does not map to a coded entry.

    Resolution order:
        1. Real cadence (freq / period=1 / periodUnit=d) — use as-is.
        2. Missing cadence + drug in `_DRUG_IMPLIED_FREQ_*` — infer freq
           from the drug's clinical convention (statins→QD, biguanides
           →BID, etc.).
        3. Otherwise → None (caller falls back to dummy).

    Not deterministic-per-encounter (returns identical outputs for the
    same input); intended to be a pure lookup called from
    `_populate_jp_medication_dosage_ecs_fields`.
    """
    # Path 1: cadence available and daily
    has_daily_cadence = (
        isinstance(freq, int)
        and isinstance(period, (int, float))
        and period_unit == "d"
        and period == 1
        and freq in _DEFAULT_MEAL_CONTEXT_BY_FREQ
    )
    # Path 2: cadence missing → infer from drug's clinical convention.
    # Explicit non-daily cadences (hourly etc.) are rejected — do NOT
    # promote them to daily inference (that would drop information).
    if not has_daily_cadence:
        cadence_present = (isinstance(freq, int) and freq > 0) or isinstance(period, (int, float)) or bool(period_unit)
        if cadence_present:
            return None  # explicit non-daily cadence — no clean spec code
        if drug_text in _DRUG_IMPLIED_FREQ_QD:
            freq = 1
        elif drug_text in _DRUG_IMPLIED_FREQ_BID:
            freq = 2
        else:
            return None

    ctx: str | None = None
    if freq == 1:
        ctx = _DRUG_QD_MEAL_CONTEXT.get(drug_text)
    elif freq == 2:
        ctx = _DRUG_BID_MEAL_CONTEXT.get(drug_text)
    if not ctx:
        ctx = _DEFAULT_MEAL_CONTEXT_BY_FREQ.get(freq)  # type: ignore[arg-type]
    if not ctx:
        return None
    return _FREQ_CONTEXT_TO_MHLW_CODE.get((freq, ctx))  # type: ignore[arg-type]


# JP_MedicationDosage_eCS `Dosage.doseAndRate.type` min=1.
# Spec-authoritative example fixture
# (`MedicationRequest-Example-JP-MedReq-PO-TID-2days-dummyUsageCode.json` in
# `clinical-information-sharing#1.12.0/package/example/`) uses the MHLW
# MedicationIngredientStrengthType CodeSystem `code=1 / display=製剤量`
# (pharmaceutical dose = the amount of formulation ordered, as opposed to
# active-ingredient strength). clinosim does not otherwise emit this
# CodeSystem, so we define the URI here so `_populate_jp_medication_dosage_ecs_fields`
# can inject the coding without duplicating the literal.
_JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS = (
    "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/MedicationIngredientStrengthStrengthType"
)


_JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE = "1"


_JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_DISPLAY = "製剤量"


# UCUM CodeSystem URI + daily unit — used to rewrite
# `Dosage.timing.repeat.periodUnit='d'` (bare `code` with unresolvable-by-tx
# UnitsOfTime binding) into a `Dosage.timing.repeat.boundsDuration` Duration
# whose `system` field lets the validator resolve `d` inline.# Chain #2.
_UCUM_SYSTEM_URI = "http://unitsofmeasure.org"


_UCUM_DAY_CODE = "d"


_UCUM_DAY_UNIT_JA = "日"


# eCS-required identifier namespaces (feedback fix PR-G, 2026-07-17). Every
# resource for which JP-CLINS eCS requires `identifier` with `min=1` gets a
# canonical clinosim namespace so consumers can round-trip resources without
# fabricating IDs. MedicationRequest is intentionally NOT in this map — its
# builder already emits identifier[] with rpNumber + orderInRp (JP Core
# NamingSystem slice discriminators, rule).
_ECS_IDENTIFIER_SYSTEMS: dict[str, str] = {
    "Condition": "urn:clinosim:condition-id",
    "AllergyIntolerance": "urn:clinosim:allergyintolerance-id",
}


# JP-CLINS `JP_Condition_eCS` requires the `code.coding:medisRecordNo` slice
# (min=1) whose `system` fixedUri is the MEDIS 標準病名マスター 病名管理番号
# CodeSystem (spec: `StructureDefinition-JP-Condition-eCS.json`). clinosim does
# not ship an ICD-10 → keyNumber mapping, so we emit the MEDIS "uncoded
# disease" placeholder (`99999999` / `未コード化傷病名`) — an authoritative
# entry used in real JP hospital systems when reception input does not map
# cleanly to the 標準病名マスター. The code is verified present in the JP-
# terminology fragment CodeSystem loaded by fhir-jp-validator
# (`jpfhir-terminology 2.2606.0` / `medis-codesystem-diseasekanricodes`).
_MEDIS_DISEASE_KEYNUMBER_SYSTEM = "http://medis.or.jp/CodeSystem/master-disease-keyNumber"


_MEDIS_UNCODED_DISEASE_CODE = "99999999"


_MEDIS_UNCODED_DISEASE_DISPLAY = "未コード化傷病名"


# HL7 condition-clinical / condition-ver-status display map. The tiny code
# vocabulary is not in clinosim/codes/data/ (they are HL7 spec CS, not
# clinical codes) so we keep the English display map inline.
_CONDITION_CLINICAL_DISPLAY: dict[str, str] = {
    "active": "Active",
    "recurrence": "Recurrence",
    "relapse": "Relapse",
    "inactive": "Inactive",
    "remission": "Remission",
    "resolved": "Resolved",
}


_CONDITION_VER_STATUS_DISPLAY: dict[str, str] = {
    "unconfirmed": "Unconfirmed",
    "provisional": "Provisional",
    "differential": "Differential",
    "confirmed": "Confirmed",
    "refuted": "Refuted",
    "entered-in-error": "Entered in Error",
}


_ALLERGY_CLINICAL_DISPLAY: dict[str, str] = {
    "active": "Active",
    "inactive": "Inactive",
    "resolved": "Resolved",
}


_ALLERGY_VER_STATUS_DISPLAY: dict[str, str] = {
    "unconfirmed": "Unconfirmed",
    "presumed": "Presumed",
    "confirmed": "Confirmed",
    "refuted": "Refuted",
    "entered-in-error": "Entered in Error",
}


# Reverse map: FHIR system URI → clinosim system key (for `code_lookup`).
# Used by `_copy_display_from_sibling_coding` fallback when no sibling coding
# with a display is available (e.g. AllergyIntolerance.code carries a single
# SNOMED coding).
_FHIR_URI_TO_CODE_SYSTEM_KEY: dict[str, str] = {
    "http://snomed.info/sct": "snomed-ct",
    "http://loinc.org": "loinc",
    "http://hl7.org/fhir/sid/icd-10": "icd-10",
    "http://hl7.org/fhir/sid/icd-10-cm": "icd-10-cm",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "rxnorm",
    # Issue #350: JP-locale ICD-10 canonical URI. Reverse-map
    # to the same code data as `icd-10` (via `_SYSTEM_DATA_ALIASES` in
    # `clinosim/codes/loader.py`) so `_copy_display_from_sibling_coding`
    # can look up displays for JP-emitted ICD-10 codings.
    "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full": "icd-10-mhlw",
}


def _populate_observation_identifier_and_last_updated(resource: dict, country: str = "") -> None:
    """Populate `Observation.identifier` and `Observation.meta.lastUpdated`.

    JP_Observation_LabResult_eCS (JP-CLINS 1.12.0) requires both fields:
    - `identifier[]` (`min=1`) with an `identifier:resourceIdentifier` slice
      whose `.system` matches the spec `patternUri`. For JP output the
      spec-canonical URI is emitted as the leading identifier so the slice
      is satisfied; the internal `urn:clinosim:observation-id` is appended
      as a secondary identifier so downstream consumers keep the round-trip
      key.
    - `meta.lastUpdated` (`min=1`) — falls back to `effectiveDateTime` (or
      `issued` / `effectivePeriod.end`) when the builder did not set one. The
      value is a good approximation for synthesized data since clinosim has
      no separate "record last modified" concept.

    Base FHIR admits both as optional, so the walker fires universally.
    Idempotent — leaves builder-populated values untouched.

    Feedback fix (2026-07-16, PR-D) covered identifier + meta.lastUpdated
    universally. chain A (v2 feedback §【最優先 1】) adds the
    JP-locale spec URI so the resourceIdentifier slice actually matches.
    """
    if resource.get("resourceType") != "Observation":
        return
    # identifier — Issue #336: 従来 `if not resource.get("identifier")`
    # で全体 skip だったが、microbiology `mb-org-*` / `mb-sus-*` は builder 側で
    # HAI_EVENT_ID_SYSTEM identifier を先に populate 済 → walker skip →
    # JP_Observation_LabResult_eCS の `resourceIdentifier` slice min=1 fail
    # (v9 obs 1 件 error)。sibling MedicationRequest walker (line 1908-1924)
    # と同じ idempotent-prepend pattern に統一 = 既存 identifier list を保持
    # しつつ、canonical URI が未収録なら prepend、internal namespace も append。
    rid = resource.get("id", "")
    if rid:
        existing = resource.setdefault("identifier", [])
        existing_systems = {i.get("system") for i in existing if isinstance(i, dict)}
        # JP output: canonical resourceInstance-identifier slice を必ず先頭に
        # (spec `Observation.identifier:resourceIdentifier.system` patternUri)。
        if is_jp(country) and _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM not in existing_systems:
            existing.insert(0, {"system": _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM, "value": rid})
        # 全 country: 内部 round-trip 用 identifier(既存 downstream consumer 用)。
        if _CLINOSIM_OBSERVATION_ID_SYSTEM not in existing_systems:
            existing.append({"system": _CLINOSIM_OBSERVATION_ID_SYSTEM, "value": rid})
    # meta.lastUpdated — reuse an existing datetime field. _normalize_dt_fields
    # then converts it to the FHIR `instant` shape (seconds + TZ).
    meta = resource.setdefault("meta", {})
    if not meta.get("lastUpdated"):
        ts = derive_meta_last_updated(resource, ("effectiveDateTime", "issued", "effectivePeriod.end"))
        if ts:
            meta["lastUpdated"] = ts


def _populate_jp_medication_dosage_ecs_fields(resource: dict) -> None:
    """Populate `JP_MedicationDosage_eCS`-required fields on each
    `MedicationRequest.dosageInstruction[]`.

    JP-CLINS 1.12.0 pulls the Dosage type through a JP-specific profile that
    layers three requirements the clinosim builder does not currently emit:

    1. **`Dosage.extension:periodOfUse` (min=1)** — a `Period` whose `start`
       marks the day the dose becomes effective. Derived from `authoredOn`
       (fallback: `recorded`).
    2. **`Dosage.timing.code.coding` (min=1) satisfying R5020** — exactly one
       of the MHLW ePrescription coded system OR the JP-CLINS dummy uncoded
       code `0X0XXXXXXXXX0000`. clinosim has no MHLW coded mapping, so we
       emit the JP-CLINS dummy — this is the exact choice made by the
       official JP-CLINS example fixture
       (`MedicationRequest-Example-JP-MedReq-PO-TID-2days-dummyUsageCode.json`).
    3. **`Dosage.timing.code.text` (min=1)** — human-readable frequency
       description; falls back to `Dosage.text` when unset.

    JP only (the walker is registered inside the `is_jp(country)` branch).
    Idempotent — leaves any builder-populated extension / timing.code alone.

    Feedback fix (2026-07-16, PR-I). Covers `dosageInstruction[N].extension` +
    `Constraint failed: validUsage-MedicationUsage-codesystem` from §"【最優先 2】".
    """
    if resource.get("resourceType") != "MedicationRequest":
        return
    dosages = resource.get("dosageInstruction")
    if not isinstance(dosages, list):
        return

    # Derive the period start from authoredOn / recorded (date portion only —
    # Period.start is a dateTime, but the JP-CLINS example uses date-only).
    authored = resource.get("authoredOn") or resource.get("recorded") or ""
    start_date = ""
    if isinstance(authored, str) and authored:
        # authoredOn is dateTime with TZ; strip the T portion for a stable date.
        start_date = authored.split("T", 1)[0]

    for dosage in dosages:
        if not isinstance(dosage, dict):
            continue

        # (1) PeriodOfUse extension (min=1 slice).
        exts = dosage.setdefault("extension", [])
        if isinstance(exts, list):
            already_periodofuse = any(
                isinstance(e, dict) and e.get("url") == _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL for e in exts
            )
            if not already_periodofuse and start_date:
                exts.append(
                    {
                        "url": _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL,
                        "valuePeriod": {"start": start_date},
                    }
                )

        # (2)+(3) timing.code (R5020 + text min=1).
        timing = dosage.setdefault("timing", {})
        if not isinstance(timing, dict):
            continue
        code_field = timing.setdefault("code", {})
        if not isinstance(code_field, dict):
            continue
        codings = code_field.setdefault("coding", [])
        if isinstance(codings, list):
            already_valid = any(
                isinstance(c, dict)
                and c.get("system")
                in (_JP_CLINS_MEDICATION_USAGE_UNCODED_CS, _JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS)
                for c in codings
            )
            if not already_valid:
                # Issue #817: try the MHLW MedicationUsage_ePrescription
                # heuristic first (drug-class + frequency → meal-context
                # → real MHLW code). Falls back to the dummy uncoded
                # entry when the (drug, cadence) tuple does not map.
                _repeat = timing.get("repeat") or {}
                _drug_text = str((resource.get("medicationCodeableConcept") or {}).get("text") or "").strip()
                _mhlw = _resolve_mhlw_usage_code(
                    _drug_text,
                    _repeat.get("frequency") if isinstance(_repeat, dict) else None,
                    _repeat.get("period") if isinstance(_repeat, dict) else None,
                    (_repeat.get("periodUnit") or "") if isinstance(_repeat, dict) else "",
                )
                if _mhlw is not None:
                    _mhlw_code, _mhlw_display = _mhlw
                    codings.append(
                        {
                            "system": _JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS,
                            "code": _mhlw_code,
                            "display": _mhlw_display,
                        }
                    )
                else:
                    # Issue #782: prefer a derived usage description (`1日3回`,
                    # `8時間ごと`) over the neutral placeholder when
                    # timing.repeat carries a recognizable cadence — this
                    # gives consumers a meaningful display without
                    # changing the JP-CLINS-required `code` value.
                    _derived = _derive_usage_display_from_timing(timing.get("repeat"))
                    codings.append(
                        {
                            "system": _JP_CLINS_MEDICATION_USAGE_UNCODED_CS,
                            "code": _JP_CLINS_MEDICATION_USAGE_UNCODED_CODE,
                            "display": _derived or _JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY,
                        }
                    )
        # DO NOT fill timing.code.text with dosage text. Timing.code is a
        # CodeableConcept with binding to TimingAbbreviation (BID/TID/QID/Q4H/QD).
        # Dosage text belongs in Dosage.text only (line 745). Filling both
        # creates duplication and makes timing.code.text unsuitable for its
        # intended purpose (machine-readable frequency abbreviations). Issue #477.

        # (4) `Dosage.doseAndRate.type` min=1.
        # Every doseAndRate entry gets the MHLW MedicationIngredientStrength
        # `1 / 製剤量` coding when `type` is absent. Matches the JP-CLINS
        # example fixture — see the `_JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS`
        # constant docstring for the exact provenance.
        dose_and_rate = dosage.get("doseAndRate")
        if isinstance(dose_and_rate, list):
            for dr in dose_and_rate:
                if not isinstance(dr, dict) or dr.get("type"):
                    continue
                dr["type"] = {
                    "coding": [
                        {
                            "system": _JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS,
                            "code": _JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE,
                            "display": _JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_DISPLAY,
                        }
                    ]
                }

        # (5) Add a `timing.repeat.boundsDuration` slice + strip
        # `periodUnit='d'`/`period` on JP output.
        #
        # 履歴:
        # - 元の狙いは boundsDuration only 化
        #   (UnitsOfTime binding 回避)
        # - #281:JP-CLINS example fixture が両方 emit する
        #   ことを根拠に `periodUnit` の pop を撤回
        # - v6:HAPI validator が `periodUnit=code`(FHIR R4
        #   `code` type は system 情報を持たない)の binding 検証で
        #   system URI を決定できず 3,532 件 UnitsOfTime error 発火
        #   (v5 では 0 件だった regression、tim-2 と分岐した振舞い)
        # - #307 (判断リカバリ pragmatic middle path):
        #   spec は example と別。JP-CLINS example が両方 emit しても
        #   spec が両方 required とは限らず、boundsDuration + frequency
        #   で per-day cadence 情報は spec-valid に保持可能。chain #2
        #   元の狙いに復帰し、`periodUnit` + `period` を pop する
        #   (tim-2 non-fire + UnitsOfTime binding 対象外)。
        #
        # US 側は影響なし(この walker は JP-only、_fhir_common.py の
        # `period + periodUnit` はそのまま emit される。US は FHIR R4
        # 標準 validator が `code` binding を通す仕様)。
        repeat = timing.get("repeat")
        if isinstance(repeat, dict) and repeat.get("periodUnit") == "d":
            bounds = repeat.get("boundsDuration")
            if not isinstance(bounds, dict):
                # Value 1 mirrors the periodUnit anchoring semantics (per-day
                # cadence). Downstream consumers relying on the total-therapy-
                # duration reading of `boundsDuration` should look at
                # dispenseRequest.expectedSupplyDuration instead.
                period = repeat.get("period", 1)
                repeat["boundsDuration"] = {
                    "value": period if isinstance(period, (int, float)) else 1,
                    "unit": _UCUM_DAY_UNIT_JA,
                    "system": _UCUM_SYSTEM_URI,
                    "code": _UCUM_DAY_CODE,
                }
            # #307 pop `periodUnit` + `period` after boundsDuration
            # is populated. tim-2 (period.exists() implies periodUnit.exists())
            # は pair で無くなれば non-fire。frequency + boundsDuration で
            # per-day cadence は保持。
            repeat.pop("periodUnit", None)
            repeat.pop("period", None)


def _copy_display_from_sibling_coding(codings: list, lang: str = "en") -> None:
    """When one coding entry has a display for a code and another sibling entry
    with the same code lacks it, propagate the display. Used on
    `Condition.code.coding[]` and `AllergyIntolerance.code.coding[]` where the
    primary JP coding (WHO ICD-10 / SNOMED, English-only CodeSystem) had its
    display stripped by the P2 A walker but the interop coding (ICD-10-CM /
    same code, English display) already has it.

    When no sibling display is available (e.g. AllergyIntolerance emits a
    single SNOMED coding), fall back to `code_lookup` in ``lang`` for known
    FHIR system URIs. JP output routes ``lang="ja"`` here so the primary
    coding carries a JP-native display where clinosim/codes/data has one,
    and only falls back to English when no ja entry exists.

    Feedback fix (2026-07-16, PR-G). Preserves the FHIR R4 rule that every
    coding on an English-only CodeSystem must carry a resolvable display.
    """
    if not isinstance(codings, list):
        return
    code_display: dict[str, str] = {}
    for c in codings:
        if isinstance(c, dict):
            code_ = c.get("code")
            display = c.get("display")
            if isinstance(code_, str) and code_ and isinstance(display, str) and display and code_ not in code_display:
                code_display[code_] = display
    for c in codings:
        if isinstance(c, dict) and not c.get("display"):
            code_ = c.get("code")
            if not isinstance(code_, str) or not code_:
                continue
            # Priority for the display value on a coding that lacks one:
            # (1) authoritative `code_lookup` in the requested language (ja)
            # (2) sibling coding's display (interop entry with english)
            # (3) `code_lookup` in english as a last-resort fallback.
            # (1) beats (2) on JP output so a dual-coded Condition emits the
            # authoritative JP display rather than the english interop label.
            display = None
            system_uri = c.get("system", "")
            system_key = _FHIR_URI_TO_CODE_SYSTEM_KEY.get(system_uri) if isinstance(system_uri, str) else None
            # chain G (v2 feedback §【中優先 7】): the sibling-copy
            # step previously re-injected a Japanese display via
            # `code_lookup(..., "ja")` for JP output. On English-only
            # CodeSystems (LOINC / SNOMED / HL7 terminology / DICOM / UCUM
            # / `http://hl7.org/fhir/sid/*` including ICD-10) that undid
            # `_strip_japanese_display_on_english_only_systems`, so the
            # HAPI Validator's "Wrong Display Name" check surfaced ~2.5k
            # ICD-10 errors in v2 fullset. Skip the ja lookup path when
            # the coding's system is on the English-only allowlist so the
            # sibling-copy step falls through to the interop display
            # (2) or the canonical English lookup (3).
            is_english_only_system = isinstance(system_uri, str) and system_uri.startswith(
                _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES
            )
            if system_key and lang != "en" and not is_english_only_system:
                looked_up = code_lookup(system_key, code_, lang)
                if looked_up and looked_up != code_:
                    display = looked_up
            if not display:
                display = code_display.get(code_)
            if not display and system_key:
                looked_up = code_lookup(system_key, code_, "en")
                if looked_up and looked_up != code_:
                    display = looked_up
            if display:
                c["display"] = display


def _populate_status_coding_display(coding_dict: Any, display_map: dict[str, str]) -> None:
    """Populate `.coding[].display` from a static map when missing.

    Used on `clinicalStatus` / `verificationStatus` where the HL7 CodeSystem
    values are a fixed small vocabulary (active / confirmed / ...) that is
    not carried in clinosim/codes/data/.
    """
    if not isinstance(coding_dict, dict):
        return
    codings = coding_dict.get("coding")
    if not isinstance(codings, list):
        return
    for c in codings:
        if not isinstance(c, dict) or c.get("display"):
            continue
        code_ = c.get("code")
        if isinstance(code_, str) and code_ in display_map:
            c["display"] = display_map[code_]


def _populate_condition_ai_mr_ecs_fields(resource: dict, country: str = "US") -> None:
    """Populate JP-CLINS eCS-required fields on Condition / AllergyIntolerance
    / MedicationRequest.

    Feedback fix (2026-07-16, PR-G). The 2026-07-16 fhir-jp-validator report
    §"【最優先 2】" lists a common pattern across the three resources:

    - `identifier` (min=1) — canonical clinosim namespace when not builder-set.
    - `meta.lastUpdated` (min=1) — falls back to the most authoritative
      datetime available on the resource; never fabricated when no source.
    - `clinicalStatus.coding.display` — HL7 CodeSystem values (active /
      inactive / resolved / confirmed / …) resolved via a static English
      display map.
    - `verificationStatus.coding.display` — same idea, different HL7 CS.
    - `code.coding[].display` on the primary coding — copied from a sibling
      coding that shares the same code and has a display (P2 A walker
      strips Japanese display from English-only CodeSystems; when the
      builder emits a paired interop coding with English display, we
      propagate it to the primary coding).

    The walker fires universally (US output picks up the same fields
    harmlessly) and stays idempotent.
    """
    rt = resource.get("resourceType")
    if rt not in ("Condition", "AllergyIntolerance", "MedicationRequest"):
        return

    # (1) identifier — canonical namespace, only when not builder-populated.
    # v3 (Chain-9): for JP output, prepend the JP-CLINS
    # `resourceIdentifier` slice (spec `patternUri`
    # `http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier`) so the
    # `Condition.identifier:resourceIdentifier` slice discriminator matches.
    # Same URI + same 2-element pattern as Chain A on Observation. Keeps the
    # internal `urn:clinosim:*` namespace as a secondary identifier so downstream
    # consumers can still round-trip by resource id.
    if rt in _ECS_IDENTIFIER_SYSTEMS and not resource.get("identifier"):
        rid = resource.get("id", "")
        if rid:
            if is_jp(country):
                resource["identifier"] = [
                    {"system": _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM, "value": rid},
                    {"system": _ECS_IDENTIFIER_SYSTEMS[rt], "value": rid},
                ]
            else:
                resource["identifier"] = [{"system": _ECS_IDENTIFIER_SYSTEMS[rt], "value": rid}]

    # (2) meta.lastUpdated fallback chain.
    meta = resource.setdefault("meta", {})
    if not meta.get("lastUpdated"):
        prefer: tuple[str, ...] = (
            ("authoredOn", "recorded")
            if rt == "MedicationRequest"
            else ("recordedDate", "assertedDate", "onsetDateTime")
        )
        ts = derive_meta_last_updated(resource, prefer)
        if ts:
            meta["lastUpdated"] = ts

    # (3) clinicalStatus / verificationStatus displays.
    if rt == "Condition":
        _populate_status_coding_display(resource.get("clinicalStatus"), _CONDITION_CLINICAL_DISPLAY)
        _populate_status_coding_display(resource.get("verificationStatus"), _CONDITION_VER_STATUS_DISPLAY)
    elif rt == "AllergyIntolerance":
        _populate_status_coding_display(resource.get("clinicalStatus"), _ALLERGY_CLINICAL_DISPLAY)
        _populate_status_coding_display(resource.get("verificationStatus"), _ALLERGY_VER_STATUS_DISPLAY)

    # (4) code.coding[].display sibling-copy (Condition / AllergyIntolerance).
    # JP output prefers JP display via `code_lookup(..., "ja")`; US uses "en".
    lang = "ja" if is_jp(country) else "en"
    if rt in ("Condition", "AllergyIntolerance"):
        code_field = resource.get("code")
        if isinstance(code_field, dict):
            _copy_display_from_sibling_coding(code_field.get("coding") or [], lang)
        if rt == "AllergyIntolerance":
            for reaction in resource.get("reaction", []) or []:
                if isinstance(reaction, dict):
                    for manifestation in reaction.get("manifestation", []) or []:
                        if isinstance(manifestation, dict):
                            _copy_display_from_sibling_coding(manifestation.get("coding") or [], lang)

    # (4b) JP-CLINS `JP_Condition_eCS` `code.coding:medisRecordNo` slice min=1.
    #  (v4 feedback, 6,242 errors, -1.5pp). Every JP
    # Condition must carry a MEDIS 病名管理番号 coding; without an ICD-10 →
    # keyNumber crosswalk shipped in clinosim, we use the MEDIS "uncoded
    # disease" placeholder — a real, spec-registered entry (`99999999` /
    # `未コード化傷病名`) used in JP hospital systems when reception input
    # does not map cleanly. Idempotent: skips when a MEDIS coding is already
    # present so future per-ICD-10 curation can be layered without conflict.
    if rt == "Condition" and is_jp(country):
        code_field = resource.get("code")
        if isinstance(code_field, dict):
            codings = code_field.setdefault("coding", [])
            if not any(isinstance(c, dict) and c.get("system") == _MEDIS_DISEASE_KEYNUMBER_SYSTEM for c in codings):
                codings.append(
                    {
                        "system": _MEDIS_DISEASE_KEYNUMBER_SYSTEM,
                        "code": _MEDIS_UNCODED_DISEASE_CODE,
                        "display": _MEDIS_UNCODED_DISEASE_DISPLAY,
                    }
                )

    # (5) Chain 5 (v2 feedback §【最優先 5】):
    # JP_MedicationRequest_eCS pins `status` = patternCode "completed" and
    # `intent` = patternCode "order", and requires `substitution.allowed[x]`
    # to be a CodeableConcept (allowedBoolean is rejected). Spec:
    # `tx-server-build/.../clinical-information-sharing#1.12.0/package/
    # StructureDefinition-JP-MedicationRequest-eCS.json`. Enforced only on
    # JP output; US path keeps the original semantics.
    #
    # Issue #778 (part of #774): when the builder-set status is not
    # "completed" (e.g. "active" for an ongoing home-medication or
    # "stopped" for a discontinued regimen), the eCS pin overrides real
    # semantics. Consumers viewing JP FHIR see every MedicationRequest as
    # "completed" — including the in-progress inpatient's chronic meds.
    #
    # The pin is spec-required and cannot be dropped without triggering
    # eCS validation errors. Instead we preserve the builder's original
    # status intent via TWO complementary channels so consumers can
    # recover it:
    #   (a) `Extension[url=urn:clinosim:medicationrequest-effective-status]
    #        .valueCode` — machine-readable, structured
    #   (b) `note[].text` — human-readable natural language explanation
    #
    # `dispenseRequest.validityPeriod.end` absence already signals ongoing
    # to structured consumers, but neither channel is prominent enough to
    # override the visible `status` field on a naive UI. Prior status text
    # is added below when it differs from "completed".
    if rt == "MedicationRequest" and is_jp(country):
        _pre_pin_status = resource.get("status", "")
        resource["status"] = "completed"
        resource["intent"] = "order"
        if _pre_pin_status and _pre_pin_status != "completed":
            _ext_list = resource.setdefault("extension", [])
            _ext_url = "urn:clinosim:medicationrequest-effective-status"
            if isinstance(_ext_list, list) and not any(
                isinstance(e, dict) and e.get("url") == _ext_url for e in _ext_list
            ):
                _ext_list.append({"url": _ext_url, "valueCode": _pre_pin_status})
            _notes = resource.setdefault("note", [])
            _note_text = (
                f"実効ステータス: {_pre_pin_status}（JP-CLINS eCS 準拠のため MedicationRequest.status は "
                f'"completed" に固定されているが、この処方の実際の運用状態は "{_pre_pin_status}" である）'
            )
            if isinstance(_notes, list) and not any(
                isinstance(n, dict) and n.get("text") == _note_text for n in _notes
            ):
                _notes.append({"text": _note_text})
        sub = resource.get("substitution")
        if isinstance(sub, dict) and "allowedBoolean" in sub:
            allowed_bool = bool(sub.pop("allowedBoolean"))
            _sub_code = "E" if allowed_bool else "N"
            _sub_display = "equivalent" if allowed_bool else "none"
            sub["allowedCodeableConcept"] = {
                "coding": [
                    {
                        "system": _HL7_V3_SUBSTITUTION_SYSTEM,
                        "code": _sub_code,
                        "display": _sub_display,
                    }
                ]
            }
        # v3 (Chain-10): JP_MedicationRequest_eCS requires
        # `identifier` min=3 with the `identifier:requestIdentifier` slice
        # (min=1 max=1) present in addition to the builder-emitted
        # `rpNumber` + `orderInRp` slices. The requestIdentifier value is
        # the per-medication order id; system is reused from the same
        # `resourceInstance-identifier` namespace applied to Observation
        # (Chain A) and Condition/AI (Chain-9). Idempotent — the walker
        # skips when the URI is already present in identifier[].
        ids = resource.get("identifier", []) or []
        rid = resource.get("id", "")
        if rid and not any(
            isinstance(i, dict) and i.get("system") == _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM for i in ids
        ):
            resource["identifier"] = [
                {"system": _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM, "value": rid},
                *ids,
            ]


def _normalize_jp_observation_category(resource: dict) -> None:
    """Normalize `Observation.category` for JP output(single seam).

    JP only(caller が country=JP のみで呼ぶ前提)。fhir-jp-validator
    feedback 2026-07-17 §"【最優先 3】"(286k errors)の適合設計:
    **1 category element = 1 coding**、HL7 と JP CS は必ず**別々の
    category element**として emit する。

    Spec 根拠(StructureDefinition snapshot 実測):

    - **JP_Observation_LabResult_eCS**(JP-CLINS 1.12.0)
      `Observation.category` は `1..1`、slice `laboratory` の
      `coding` は `1..1` かつ `coding.system fixedUri` =
      `JP_SimpleObservationCategory_CS`。HL7 coding 併記は
      `category:laboratory.coding max=1` を破り、かつ HL7 URL は
      fixedUri と不一致で slice discriminator を破る。→ **lab は JP CS
      単独 1 element**。
    - **JP_Observation_VitalSigns**(jp-core 1.2.0)
      `Observation.category` は `1..*`、slicing rules=`open`。
      slice `first` は `coding.system fixedUri = JP_Simple...` +
      `coding.code fixedCode = vital-signs`。`rules=open` により
      slice に match しない追加 element は許容される。base HL7
      `vitalsigns` profile(HAPI が LOINC 85354-9 等から自動適用)は
      `category:VSCat` slice に HL7 URL#vital-signs coding を要求。
      両方を満たすため → **VS は HL7 element + JP CS element の
      2 element** に分離。公式 example
      `Observation-jp-observation-vitalsigns-example-1.json` も
      同形。
    - **他 code**(social-history / imaging / procedure / survey / exam)
      HL7 base の各 slice discriminator も `coding.system+code` を
      使うため、混在すると同種の fixedUri 違反を招く。→ **JP CS
      単独 1 element**(vital-signs 以外は「1 element = 1 coding」を
      機械的に適用、conservatively minimal shape)。

    共通処理:

    - HL7 標準 URL および過去 clinosim 版の fabricated URL
      (`http://jpfhir.jp/fhir/observation-category`)は canonical
      `JP_SimpleObservationCategory_CS` に置換。
    - `display` は省略。JP CS も HL7 CodeSystem も英語 display のみ
      定義しているため日本語 display は HAPI に「Wrong Display Name」
      で reject される(feedback V5 発見 A')。日本語ラベルは
      `text` field 側で保持(translation として自由)。
    - observation-category 以外の system coding は preserve(独自
      CodeSystem を持ち込むテスト向けの defensive branch)。
      preserve 先は JP element(最初の JP category element の coding
      配列に前置)。
    """
    if resource.get("resourceType") != "Observation":
        return
    cats = resource.get("category")
    if not isinstance(cats, list) or not cats:
        return
    # Sweep every category element: collect obs-cat codes (in appearance
    # order, dedup), preserved foreign codings, and the first non-empty
    # `text` hint. Then rebuild `resource["category"]` from scratch — the
    # per-element output shape depends on the code (VS vs everything else)
    # so we cannot rewrite in place safely.
    category_codes: list[str] = []
    seen_codes: set[str] = set()
    preserved: list[dict] = []
    text_hint: str = ""
    for cat in cats:
        if not isinstance(cat, dict):
            continue
        if not text_hint:
            t = cat.get("text")
            if isinstance(t, str) and t:
                text_hint = t
        codings = cat.get("coding")
        if not isinstance(codings, list):
            continue
        for cod in codings:
            if not isinstance(cod, dict):
                continue
            sys_ = cod.get("system")
            code_ = cod.get("code")
            if sys_ in _HL7_OBSERVATION_CATEGORY_SYSTEMS or sys_ == _JP_OBSERVATION_CATEGORY_SYSTEM:
                if isinstance(code_, str) and code_ and code_ not in seen_codes:
                    category_codes.append(code_)
                    seen_codes.add(code_)
            else:
                preserved.append(cod)
    if not category_codes:
        return
    rebuilt: list[dict] = []
    for code_ in category_codes:
        if code_ == "vital-signs":
            # HL7 element first: matched by the auto-applied base
            # `vitalsigns` profile's `category:VSCat` slice; the JP Core
            # `category:first` slice ignores it via `rules=open`.
            rebuilt.append({"coding": [{"system": _HL7_OBSERVATION_CATEGORY_SYSTEM, "code": code_}]})
        # Always emit a JP element (satisfies JP Core / eCS slices for
        # every obs-cat code, including VS's `category:first`).
        rebuilt.append({"coding": [{"system": _JP_OBSERVATION_CATEGORY_SYSTEM, "code": code_}]})
    # Attach preserved foreign codings and the text hint to the first JP
    # element. Foreign category codings are rare in production; landing
    # them on the JP element mirrors the pre-refactor placement.
    for cat_elem in rebuilt:
        codings = cat_elem["coding"]
        if codings and codings[0].get("system") == _JP_OBSERVATION_CATEGORY_SYSTEM:
            if preserved:
                cat_elem["coding"] = list(preserved) + codings
            if text_hint:
                cat_elem["text"] = text_hint
            break
    resource["category"] = rebuilt
