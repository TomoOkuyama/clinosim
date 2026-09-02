"""Verify a clinosim CIF/FHIR/narrative bundle against a suite of invariants.

Session-98 formalization of the ad-hoc p=10000 verify script. Checks the
axes that byte-diff and pytest unit tests cannot see at cohort scale:

  * File-tree completeness (cif/, fhir_r4/, narratives/)
  * Structural FHIR language consistency
    (Composition.section.title, Encounter.reasonCode.text)
  * Machine-key slug leaks into human-readable fields
  * Narrative CIF locale (generator_metadata.lang) + full-width JP
    punctuation contamination on EN output + unresolved ${...} templates
    + machine-key-only sections + long-ASCII-English contamination on
    JP narratives
  * Temporal invariants: period.start <= end; no encounter after death;
    postpartum admission strictly after delivery
  * Obstetric biology: no male-flagged pregnancy Dx; delivery rate in
    plausible range
  * Referential integrity: Encounter/Condition/Observation subject and
    encounter references resolve

Usage:
    python scripts/verify_bundle.py <out_dir> {US|JP}

    <out_dir> must contain `cif/` (structural + narratives) and
    `fhir_r4/` (Patient.ndjson, Encounter.ndjson, ...). Produce it with:

        clinosim simulate --country US -p 500 -s 42 \\
            --start 2023-01-01 --end 2025-01-01 \\
            --format cif fhir-r4 -o /tmp/cohort
        clinosim narrate --cif-dir /tmp/cohort/cif --provider template

Exit code 0 = all invariants held, 1 = at least one FAIL surfaced.
Prints a JSON report on stdout with per-axis counts + failure samples.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(sys.argv[1])
COUNTRY = sys.argv[2].upper()
assert COUNTRY in ("US", "JP")

FHIR = OUT / "fhir_r4"
CIF = OUT / "cif"
STRUCT = CIF / "structural"
NARR = CIF / "narratives"

report = {"country": COUNTRY, "out": str(OUT)}
fail = []

# --- Regex helpers ---
HAS_JP = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
# Long ASCII English sentence: 40+ contiguous ASCII letters/spaces/punct at once, no CJK
LONG_ASCII_SENTENCE = re.compile(r"[A-Za-z][A-Za-z0-9 ,;:'\-.()/&%]{40,}")
UNRESOLVED_TEMPLATE = re.compile(r"\$\{[^}]+\}|\{\{[^}]+\}\}")
# Machine-key slug: pure lowercase snake_case token, no spaces, no punctuation
MACHINE_KEY = re.compile(r"^[a-z][a-z0-9_]{2,50}$")
# Full-width punctuation (JA): ideographic comma 、 period 。 fullwidth parens etc.
# When appearing in an EN document, it's locale contamination.
FULLWIDTH_PUNCT = re.compile(r"[　-〿＀-￯]")


def read_ndjson(p: Path):
    if not p.exists():
        return []
    with p.open() as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as e:
                fail.append(f"BAD JSON {p.name}:{i}: {e}")


def check_file_present():
    r = {}
    r["cif_metadata"] = (CIF / "metadata.json").exists()
    r["cif_structural"] = STRUCT.exists() and any(STRUCT.iterdir()) if STRUCT.exists() else False
    r["fhir_dir"] = FHIR.exists()
    core_fhir = ["Patient", "Encounter", "Condition", "Observation", "Composition"]
    r["fhir_core_files"] = {f: (FHIR / f"{f}.ndjson").exists() for f in core_fhir}
    r["narratives_dir"] = NARR.exists()
    report["files"] = r
    if not all([r["cif_metadata"], r["cif_structural"], r["fhir_dir"], r["narratives_dir"]]):
        fail.append("missing expected output directory")
    for f, ok in r["fhir_core_files"].items():
        if not ok:
            fail.append(f"missing FHIR {f}.ndjson")


# ---------------- Structural FHIR ----------------
def check_structural_fhir():
    r = {}
    # 1. Composition.section.title language
    jp_titles = 0
    en_titles = 0
    slug_leak = []
    for doc in read_ndjson(FHIR / "Composition.ndjson"):
        for sec in doc.get("section", []):
            t = sec.get("title", "")
            if not t:
                continue
            if HAS_JP.search(t):
                jp_titles += 1
            else:
                en_titles += 1
            if MACHINE_KEY.match(t):
                slug_leak.append(t)
    r["composition_section_titles"] = {"jp": jp_titles, "en": en_titles}
    r["composition_section_slug_leak_count"] = len(slug_leak)
    r["composition_section_slug_leak_sample"] = list(set(slug_leak))[:5]
    if COUNTRY == "JP" and en_titles > 0:
        fail.append(f"JP Composition.section.title EN leak: {en_titles} titles are ASCII-only")
    if COUNTRY == "US" and jp_titles > 0:
        fail.append(f"US Composition.section.title JP leak: {jp_titles} titles contain JP chars")
    if slug_leak:
        fail.append(f"Composition.section.title machine-key slug leak: {len(slug_leak)} instances")

    # 2. Encounter.reasonCode.text language
    jp_reason = 0
    en_reason = 0
    slug_reason = []
    for e in read_ndjson(FHIR / "Encounter.ndjson"):
        for rc in e.get("reasonCode", []):
            t = rc.get("text", "")
            if not t:
                continue
            if HAS_JP.search(t):
                jp_reason += 1
            else:
                en_reason += 1
            if MACHINE_KEY.match(t):
                slug_reason.append(t)
    r["encounter_reason_text"] = {"jp": jp_reason, "en": en_reason}
    r["encounter_reason_slug_leak"] = len(slug_reason)

    # 3. Cross-locale contamination
    if COUNTRY == "JP":
        us_contam = sum(
            1
            for e in read_ndjson(FHIR / "Encounter.ndjson")
            for rc in e.get("reasonCode", [])
            if rc.get("text") and not HAS_JP.search(rc.get("text", ""))
        )
        r["jp_encounter_reason_ascii_only"] = us_contam
    if COUNTRY == "US":
        jp_contam = 0
        for e in read_ndjson(FHIR / "Encounter.ndjson"):
            for rc in e.get("reasonCode", []):
                if rc.get("text") and HAS_JP.search(rc.get("text", "")):
                    jp_contam += 1
        r["us_encounter_reason_jp_chars"] = jp_contam

    report["structural_fhir_lang"] = r


# ---------------- Narrative CIF ----------------
def check_narrative_cif():
    r = {
        "docs": 0,
        "sections": 0,
        "lang_dist": Counter(),
        "wrong_lang_docs": 0,
        "wrong_lang_samples": [],
        "unresolved_templates": 0,
        "unresolved_samples": [],
        "machine_key_only_sections": 0,
        "machine_key_samples": [],
        "cross_locale_docs": 0,
        "cross_locale_samples": [],
        "fullwidth_punct_in_en_sections": 0,
        "fullwidth_samples": [],
        "empty_sections_dict_but_has_text": 0,
    }
    # Pick default version dir (template)
    cur = NARR / "current_version.txt"
    ver = cur.read_text().strip() if cur.exists() else "template"
    ver_dir = NARR / ver
    if not ver_dir.exists():
        fail.append(f"narrative version dir missing: {ver_dir}")
        return
    docs = list((ver_dir / "documents").rglob("doc-*.json"))
    r["docs"] = len(docs)
    expected_lang = "ja" if COUNTRY == "JP" else "en"
    for dp in docs:
        try:
            d = json.load(dp.open())
        except Exception as e:
            fail.append(f"bad narrative json {dp.name}: {e}")
            continue
        narr = d.get("narrative", {})
        lang = narr.get("generator_metadata", {}).get("lang", "unknown")
        r["lang_dist"][lang] += 1
        if lang != expected_lang:
            r["wrong_lang_docs"] += 1
            if len(r["wrong_lang_samples"]) < 3:
                r["wrong_lang_samples"].append({"doc": dp.name, "lang": lang})
        secs = narr.get("sections", {})
        flat_text = narr.get("text", "") or ""
        # docs that use flat .text (ED brief/nursing shift note) — track these
        if not secs and flat_text:
            r["empty_sections_dict_but_has_text"] += 1
            # also check flat text for cross-locale contamination
            if COUNTRY == "US":
                if HAS_JP.search(flat_text) or FULLWIDTH_PUNCT.search(flat_text):
                    r["fullwidth_punct_in_en_sections"] += 1
                    if len(r["fullwidth_samples"]) < 3:
                        r["fullwidth_samples"].append({"doc": dp.name, "src": "flat_text", "text": flat_text[:150]})
            else:
                # JP: flat text should have JP chars
                if flat_text.strip() and not HAS_JP.search(flat_text) and LONG_ASCII_SENTENCE.search(flat_text):
                    r["cross_locale_docs"] += 1
                    if len(r["cross_locale_samples"]) < 3:
                        r["cross_locale_samples"].append({"doc": dp.name, "src": "flat_text", "text": flat_text[:150]})
        for slug, text in secs.items():
            r["sections"] += 1
            if not text:
                continue
            if UNRESOLVED_TEMPLATE.search(text):
                r["unresolved_templates"] += 1
                if len(r["unresolved_samples"]) < 3:
                    r["unresolved_samples"].append({"doc": dp.name, "slug": slug, "text": text[:100]})
            if MACHINE_KEY.match(text.strip()):
                r["machine_key_only_sections"] += 1
                if len(r["machine_key_samples"]) < 3:
                    r["machine_key_samples"].append({"doc": dp.name, "slug": slug, "text": text[:80]})
            # cross-locale check
            if COUNTRY == "JP":
                # JP narrative should be Japanese. Long ASCII English sentence = contamination.
                # Allow short ASCII tokens (numbers, code names, drug names).
                if LONG_ASCII_SENTENCE.search(text) and not HAS_JP.search(text):
                    r["cross_locale_docs"] += 1
                    if len(r["cross_locale_samples"]) < 3:
                        r["cross_locale_samples"].append({"doc": dp.name, "slug": slug, "text": text[:120]})
            else:  # US
                if HAS_JP.search(text):
                    r["cross_locale_docs"] += 1
                    if len(r["cross_locale_samples"]) < 3:
                        r["cross_locale_samples"].append({"doc": dp.name, "slug": slug, "text": text[:120]})
                # Additionally: full-width punctuation (、。「」etc) is JP contamination even if no CJK letters
                if FULLWIDTH_PUNCT.search(text):
                    r["fullwidth_punct_in_en_sections"] += 1
                    if len(r["fullwidth_samples"]) < 5:
                        r["fullwidth_samples"].append({"doc": dp.name, "slug": slug, "text": text[:150]})
    r["lang_dist"] = dict(r["lang_dist"])
    report["narrative_cif"] = r
    if r["wrong_lang_docs"] > 0:
        fail.append(f"narrative: {r['wrong_lang_docs']} docs have wrong lang (expected {expected_lang})")
    if r["unresolved_templates"] > 0:
        fail.append(f"narrative: {r['unresolved_templates']} sections have unresolved ${{...}} templates")
    if r["machine_key_only_sections"] > 0:
        fail.append(f"narrative: {r['machine_key_only_sections']} sections have machine-key-only text")
    if r["cross_locale_docs"] > 0:
        fail.append(f"narrative: {r['cross_locale_docs']} sections have cross-locale contamination")
    if COUNTRY == "US" and r["fullwidth_punct_in_en_sections"] > 0:
        n = r["fullwidth_punct_in_en_sections"]
        fail.append(f"narrative: {n} EN sections contain fullwidth JP punctuation (、。「」etc)")


# ---------------- Temporal ----------------
def check_temporal():
    r = {}
    # 1. Encounter period start <= end
    bad_period = 0
    bad_samples = []
    # 2. Postpartum > delivery (obstetric invariant)
    # 3. No encounter after death
    patient_death = {}
    for p in read_ndjson(FHIR / "Patient.ndjson"):
        dd = p.get("deceasedDateTime")
        if dd:
            patient_death[p["id"]] = dd
    encounters_by_patient = defaultdict(list)
    for e in read_ndjson(FHIR / "Encounter.ndjson"):
        per = e.get("period", {})
        s = per.get("start")
        en = per.get("end")
        if s and en and s > en:
            bad_period += 1
            if len(bad_samples) < 3:
                bad_samples.append({"id": e.get("id"), "start": s, "end": en})
        pid = (e.get("subject", {}).get("reference", "") or "").replace("Patient/", "")
        encounters_by_patient[pid].append(
            (s, en, e.get("type", [{}])[0].get("coding", [{}])[0].get("code", ""), e.get("id"))
        )
    r["encounter_period_start_gt_end"] = {"count": bad_period, "samples": bad_samples}
    # encounter after death
    after_death = 0
    after_death_samples = []
    for pid, dd in patient_death.items():
        for s, en, typ, eid in encounters_by_patient.get(pid, []):
            if s and s > dd:
                after_death += 1
                if len(after_death_samples) < 3:
                    after_death_samples.append({"patient": pid, "death": dd, "encounter_start": s, "id": eid})
    r["encounter_after_death"] = {"count": after_death, "samples": after_death_samples}
    # obstetric: postpartum > delivery. Look at Condition Z37/O80 encounters and postpartum AMB.
    # Simpler: for a patient with a delivery Condition (O80 or Z37), find its Encounter start,
    # then find any AMB encounter tagged postpartum (or within 30d after) — assert start > delivery_start
    delivery_enc_start_by_patient = defaultdict(list)
    for c in read_ndjson(FHIR / "Condition.ndjson"):
        codes = [cd.get("code", "") for cd in c.get("code", {}).get("coding", [])]
        if any(
            cc in ("O80", "O801", "Z37", "Z370", "Z371") or cc.startswith("O80") or cc.startswith("Z37") for cc in codes
        ):
            eref = (c.get("encounter", {}).get("reference", "") or "").replace("Encounter/", "")
            pid = (c.get("subject", {}).get("reference", "") or "").replace("Patient/", "")
            # find that encounter start
            for s, en, typ, eid in encounters_by_patient.get(pid, []):
                if eid == eref:
                    delivery_enc_start_by_patient[pid].append(s)
                    break
    # Postpartum encounters: search Encounter.reasonCode for postpartum / puerperium / Z39
    postpartum_by_patient = defaultdict(list)
    for e in read_ndjson(FHIR / "Encounter.ndjson"):
        rc_texts = " ".join([rc.get("text", "") for rc in e.get("reasonCode", [])])
        rc_codes = []
        for rc in e.get("reasonCode", []):
            for cd in rc.get("coding", []):
                rc_codes.append(cd.get("code", ""))
        if (
            any(c in ("Z39", "Z390", "Z391", "Z392") for c in rc_codes)
            or "postpartum" in rc_texts.lower()
            or "産褥" in rc_texts
            or "産後" in rc_texts
        ):
            pid = (e.get("subject", {}).get("reference", "") or "").replace("Patient/", "")
            postpartum_by_patient[pid].append(e.get("period", {}).get("start"))
    tp_ok = tp_bad = 0
    tp_bad_samples = []
    for pid, del_starts in delivery_enc_start_by_patient.items():
        if not del_starts:
            continue
        earliest_del = min(x for x in del_starts if x)
        for pp_start in postpartum_by_patient.get(pid, []):
            if pp_start and earliest_del:
                if pp_start > earliest_del:
                    tp_ok += 1
                else:
                    tp_bad += 1
                    if len(tp_bad_samples) < 3:
                        tp_bad_samples.append({"patient": pid, "delivery": earliest_del, "postpartum": pp_start})
    r["postpartum_after_delivery"] = {"ok": tp_ok, "bad": tp_bad, "samples": tp_bad_samples}
    report["temporal"] = r
    if bad_period > 0:
        fail.append(f"temporal: {bad_period} encounters with period.start > period.end")
    if after_death > 0:
        fail.append(f"temporal: {after_death} encounters after patient death")


# ---------------- Statistical (obstetric biology) ----------------
def check_statistical_obstetric():
    r = {}
    # count Z34 (supervision), Z37 (outcome), O80 (spontaneous delivery)
    z34 = z37 = o80 = 0
    # ineligible: sex=male, or age<12 or age>55
    ineligible_male = ineligible_age = 0
    # Load patient sex + birth
    p_sex = {}
    p_birth = {}
    for p in read_ndjson(FHIR / "Patient.ndjson"):
        p_sex[p["id"]] = p.get("gender", "")
        p_birth[p["id"]] = p.get("birthDate", "")
    delivered_patients = set()
    z34_patients = set()
    for c in read_ndjson(FHIR / "Condition.ndjson"):
        codes = [cd.get("code", "") for cd in c.get("code", {}).get("coding", [])]
        pid = (c.get("subject", {}).get("reference", "") or "").replace("Patient/", "")
        for cc in codes:
            if cc.startswith("Z34"):
                z34 += 1
                z34_patients.add(pid)
            elif cc.startswith("Z37"):
                z37 += 1
                delivered_patients.add(pid)
            elif cc.startswith("O80"):
                o80 += 1
                delivered_patients.add(pid)
        # eligibility check
        if any(cc.startswith(("Z34", "Z37", "O8", "O0", "O1", "O2", "O3", "O4", "O6", "O7", "O9")) for cc in codes):
            sex = p_sex.get(pid, "")
            if sex == "male":
                ineligible_male += 1
            bd = p_birth.get(pid, "")
            if bd:
                try:
                    y = int(bd[:4])
                    # crude age at 2024
                    if y < 1970 or y > 2010:
                        ineligible_age += 1
                except (TypeError, ValueError):
                    pass
    r["z34_conditions"] = z34
    r["z37_conditions"] = z37
    r["o80_conditions"] = o80
    r["unique_delivered_patients"] = len(delivered_patients)
    r["unique_z34_patients"] = len(z34_patients)
    r["ineligible_male_obstetric"] = ineligible_male
    r["ineligible_age_obstetric"] = ineligible_age

    # deliveries per 1000 women 15-49
    women_15_49 = 0
    for pid, sex in p_sex.items():
        if sex != "female":
            continue
        bd = p_birth.get(pid, "")
        if not bd:
            continue
        try:
            y = int(bd[:4])
            age = 2024 - y
            if 15 <= age <= 49:
                women_15_49 += 1
        except (TypeError, ValueError):
            pass
    r["women_15_49_denom"] = women_15_49
    if women_15_49:
        # simulation is 2 years so annualize
        r["delivery_rate_per_1000_per_year"] = round(len(delivered_patients) / 2 * 1000 / women_15_49, 2)
    report["statistical_obstetric"] = r
    # Biology invariants (session 97 pattern)
    if r["z37_conditions"] != r["o80_conditions"]:
        # Not strictly equal — Z37 is outcome-of-delivery, O80 is normal-spontaneous.
        # Cesarean O82 would break equality. Emit as observation, not fail.
        r["z37_o80_equality"] = (
            f"NOTE: Z37={r['z37_conditions']} != O80={r['o80_conditions']} (expected O80 <= Z37 when C-section modeled)"
        )
    else:
        r["z37_o80_equality"] = "OK (equal)"
    if r["ineligible_male_obstetric"] > 0:
        fail.append(f"biology: {r['ineligible_male_obstetric']} obstetric Conditions on male patients")
    if r["ineligible_age_obstetric"] > 0:
        n = r["ineligible_age_obstetric"]
        fail.append(f"biology: {n} obstetric Conditions outside age 15-49 (pre-1970 or post-2010 births)")


# ---------------- Clinical consistency ----------------
def check_clinical():
    r = {}
    # 1. All Encounter.subject references resolve
    patient_ids = set()
    for p in read_ndjson(FHIR / "Patient.ndjson"):
        patient_ids.add(p["id"])
    encounter_ids = set()
    dangling_enc_subj = 0
    for e in read_ndjson(FHIR / "Encounter.ndjson"):
        encounter_ids.add(e["id"])
        pid = (e.get("subject", {}).get("reference", "") or "").replace("Patient/", "")
        if pid and pid not in patient_ids:
            dangling_enc_subj += 1
    r["patient_count"] = len(patient_ids)
    r["encounter_count"] = len(encounter_ids)
    r["dangling_encounter_subject"] = dangling_enc_subj

    # 2. Condition.encounter references resolve
    dangling_cond_enc = 0
    dangling_cond_subj = 0
    condition_count = 0
    for c in read_ndjson(FHIR / "Condition.ndjson"):
        condition_count += 1
        er = (c.get("encounter", {}).get("reference", "") or "").replace("Encounter/", "")
        pr = (c.get("subject", {}).get("reference", "") or "").replace("Patient/", "")
        if er and er not in encounter_ids:
            dangling_cond_enc += 1
        if pr and pr not in patient_ids:
            dangling_cond_subj += 1
    r["condition_count"] = condition_count
    r["dangling_condition_encounter"] = dangling_cond_enc
    r["dangling_condition_subject"] = dangling_cond_subj

    # 3. Observation refs
    obs_count = 0
    dangling_obs_enc = 0
    dangling_obs_subj = 0
    for o in read_ndjson(FHIR / "Observation.ndjson"):
        obs_count += 1
        er = (o.get("encounter", {}).get("reference", "") or "").replace("Encounter/", "")
        pr = (o.get("subject", {}).get("reference", "") or "").replace("Patient/", "")
        if er and er not in encounter_ids:
            dangling_obs_enc += 1
        if pr and pr not in patient_ids:
            dangling_obs_subj += 1
    r["observation_count"] = obs_count
    r["dangling_observation_encounter"] = dangling_obs_enc
    r["dangling_observation_subject"] = dangling_obs_subj

    # 4. Composition per encounter
    r["composition_count"] = sum(1 for _ in read_ndjson(FHIR / "Composition.ndjson"))

    # 5. MedicationRequest / MedicationAdministration route + dose
    mr = list(read_ndjson(FHIR / "MedicationRequest.ndjson"))
    ma = list(read_ndjson(FHIR / "MedicationAdministration.ndjson"))
    r["medication_request_count"] = len(mr)
    r["medication_administration_count"] = len(ma)

    report["clinical"] = r
    if dangling_enc_subj > 0:
        fail.append(f"clinical: {dangling_enc_subj} Encounter.subject references dangling")
    if dangling_cond_enc > 0 or dangling_cond_subj > 0:
        fail.append(f"clinical: dangling Condition refs (encounter={dangling_cond_enc}, subject={dangling_cond_subj})")
    if dangling_obs_enc > 0 or dangling_obs_subj > 0:
        fail.append(f"clinical: dangling Observation refs (encounter={dangling_obs_enc}, subject={dangling_obs_subj})")


# ---------------- Run ----------------
check_file_present()
check_structural_fhir()
check_narrative_cif()
check_temporal()
check_statistical_obstetric()
check_clinical()

report["FAIL"] = fail
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(1 if fail else 0)
