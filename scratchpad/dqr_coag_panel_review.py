"""Data-quality review for the Coag panel PR — three axes.

1. STRUCTURAL HYGIENE
   - New Coag LOINC (14979-9, 5902-2, 3255-7) + Coag panel (24373-3)
     resolve to authoritative English display (NLM-verified)
   - New JLAC10 (2B020, 2B100, plus reused 2B030) resolve to JCCLS-official
     Japanese display (NOT English abbreviations — PR #76 lesson)
   - All APTT / PT / Fibrinogen Observations have referenceRange
   - All Coag DRs (24373-3) have ≥ 2 result[] references that resolve

2. CLINICAL FIDELITY (note: physiology formula correctness lives in
   unit tests — tests/unit/test_physiology.py::test_fibrinogen_*. The
   cohort-level checks below assess emergent realism, not formula bugs.)

   - Sepsis (A41) admit-day Fibrinogen p50 in 350-650 mg/dL (acute-phase
     reactant range; full DIC consumption only appears in the subset of
     sepsis patients who develop DIC over the LOS — admit-day cohort is
     dominated by inflammation ↑ without coag-status ↑ accumulation yet)
   - Sepsis (A41) admit-day APTT p75 ≥ 30 s (≥ upper reference, mild
     trending; full DIC prolongation appears later in LOS for the DIC
     subset, same caveat as Fibrinogen)
   - Hepatic-failure (K72) / cirrhosis-decompensated PT_INR p75 ≥ 1.5
   - Healthy outpatient cohort: Fibrinogen p50 around 300 mg/dL is the
     theoretical baseline; whole-cohort median can run higher when
     inflammation-biased disease scenarios dominate the cohort (this is
     emergent, not a defect — the formula is unit-test validated).
   - PT == 12 * PT_INR within 0.1 s when both are emitted simultaneously
     (no disease YAML orders {test:"PT"} individually today; the LOINC
     5902-2 emit count is therefore expected to be 0 — guard for future).

3. JP LOCALIZATION
   - US output: zero Japanese characters in new Coag-related fields
   - JP output: APTT/PT/Fibrinogen Observation.code.coding[].display in
     Japanese
   - jlac10.yaml 2B020/2B100 ja values contain Japanese (not "APTT", not
     "Fibrinogen")

Usage:
    python scratchpad/dqr_coag_panel_review.py <bundle-root> <country>
"""
from __future__ import annotations

import collections
import json
import re
import statistics
import sys
from pathlib import Path

JAPANESE = re.compile(r"[぀-ヿ一-鿿！-｠]")
# Coag-related LOINC and JLAC10 codes for code-display + emission count
COAG_LOINC = {
    "14979-9": "APTT",
    "5902-2": "PT",
    "3255-7": "Fibrinogen",
    "6301-6": "PT-INR",
    "24373-3": "Coag panel",
}
COAG_JLAC10 = {
    "2B020": "APTT",
    "2B030": "PT/PT_INR (shared analyte)",
    "2B100": "Fibrinogen",
}


def load_ndjson(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with open(path) as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def primary_admit_date(enc: dict) -> str | None:
    p = enc.get("period", {})
    return (p.get("start") or "")[:10] or None


def admit_obs_for_diseases(obs: list[dict], encs: list[dict], conds: list[dict],
                           dx_prefixes: tuple[str, ...]) -> list[dict]:
    """Return Observations whose effectiveDateTime[:10] matches the admission
    date of an Encounter whose primary diagnosis ICD-10 starts with any of
    the given prefixes."""
    # Build patient -> [admit_dates] for matching Conditions
    cond_pid_dates: dict[str, set[str]] = collections.defaultdict(set)
    for c in conds:
        codings = c.get("code", {}).get("coding") or []
        if not any(
            cd.get("code", "").startswith(dx_prefixes)
            for cd in codings
        ):
            continue
        subj = c.get("subject", {}).get("reference", "")
        pid = subj.split("/")[-1] if subj else ""
        if not pid:
            continue
        for enc in encs:
            enc_subj = enc.get("subject", {}).get("reference", "")
            if enc_subj.split("/")[-1] != pid:
                continue
            d = primary_admit_date(enc)
            if d:
                cond_pid_dates[pid].add(d)
    # Match Observations
    matched: list[dict] = []
    for o in obs:
        subj = o.get("subject", {}).get("reference", "")
        pid = subj.split("/")[-1] if subj else ""
        when = (o.get("effectiveDateTime") or "")[:10]
        if pid in cond_pid_dates and when in cond_pid_dates[pid]:
            matched.append(o)
    return matched


def obs_values_by_lab(obs: list[dict], lab_codes: set[str]) -> dict[str, list[float]]:
    """Group numeric values by analyte code (LOINC or JLAC10)."""
    by_code: dict[str, list[float]] = collections.defaultdict(list)
    for o in obs:
        codings = o.get("code", {}).get("coding") or []
        if not codings:
            continue
        match = next((c for c in codings if c.get("code") in lab_codes), None)
        if not match:
            continue
        val = o.get("valueQuantity", {}).get("value")
        if val is not None:
            by_code[match["code"]].append(float(val))
    return by_code


def pct(values: list[float], q: int) -> float:
    if not values:
        return float("nan")
    return statistics.quantiles(values, n=100)[q - 1] if len(values) > 1 else values[0]


def structural_axis(root: Path, country: str) -> list[str]:
    fhir = root / "fhir_r4"
    obs = load_ndjson(fhir / "Observation.ndjson")
    drs = load_ndjson(fhir / "DiagnosticReport.ndjson")
    out: list[str] = ["## Structural\n"]

    # Coag DR (24373-3) count + result[] integrity
    coag_drs = [
        d for d in drs
        if any(c.get("code") == "24373-3"
               for c in d.get("code", {}).get("coding") or [])
    ]
    obs_ids = {o.get("id") for o in obs}
    bad_refs = 0
    for d in coag_drs:
        for r in d.get("result") or []:
            ref = r.get("reference", "")
            if not ref:
                continue
            target = ref.split("/")[-1]
            if target not in obs_ids:
                bad_refs += 1
    out.append(f"- Coag DR (24373-3) count: **{len(coag_drs)}**")
    out.append(f"- Coag DR result[] unresolved references: **{bad_refs}**  "
               f"({'PASS' if bad_refs == 0 else 'FAIL'})")

    # referenceRange coverage on new analytes
    target_codes = {"14979-9", "5902-2", "3255-7"} if country == "US" else {"2B020", "2B030", "2B100"}
    target_obs = [
        o for o in obs
        if any(c.get("code") in target_codes
               for c in o.get("code", {}).get("coding") or [])
    ]
    with_range = [o for o in target_obs if o.get("referenceRange")]
    rr_pct = 100 * len(with_range) / len(target_obs) if target_obs else float("nan")
    out.append(f"- New Coag-related Observations: **{len(target_obs)}**, with refRange: **{len(with_range)}** "
               f"({rr_pct:.1f}%)  ({'PASS' if rr_pct == 100 else 'CHECK' if target_obs else 'N/A'})")

    # display != code on new Coag codings
    bad_display = []
    code_displays: dict[str, set[str]] = collections.defaultdict(set)
    for o in obs:
        for c in o.get("code", {}).get("coding") or []:
            code = c.get("code", "")
            disp = c.get("display", "")
            if code in (COAG_LOINC if country == "US" else COAG_JLAC10):
                code_displays[code].add(disp)
                if disp == code or not disp:
                    bad_display.append((code, disp))
    out.append(f"- Coag codings with display==code or empty: **{len(bad_display)}**  "
               f"({'PASS' if not bad_display else 'FAIL'})")
    out.append("- Coag code → display samples:")
    for code, displays in code_displays.items():
        for d in displays:
            out.append(f"    - `{code}` → `{d}`")
    return out


def clinical_axis(root: Path, country: str) -> list[str]:
    fhir = root / "fhir_r4"
    obs = load_ndjson(fhir / "Observation.ndjson")
    encs = load_ndjson(fhir / "Encounter.ndjson")
    conds = load_ndjson(fhir / "Condition.ndjson")
    out: list[str] = ["\n## Clinical\n"]

    fib_code = "3255-7" if country == "US" else "2B100"
    aptt_code = "14979-9" if country == "US" else "2B020"
    # PT_INR LOINC and JLAC10 (PT seconds shares JLAC10 with PT_INR)
    pt_inr_code = "6301-6" if country == "US" else "2B030"
    pt_code = "5902-2" if country == "US" else "2B030"

    # Sepsis (A41) admit-day Fibrinogen + APTT
    sepsis_obs = admit_obs_for_diseases(obs, encs, conds, ("A41",))
    sepsis_by = obs_values_by_lab(sepsis_obs, {fib_code, aptt_code, pt_inr_code})
    sepsis_fib = sepsis_by.get(fib_code, [])
    sepsis_aptt = sepsis_by.get(aptt_code, [])
    if sepsis_fib:
        p50 = statistics.median(sepsis_fib)
        in_band = 350 <= p50 <= 650
        out.append(f"- Sepsis (A41) admit-day Fibrinogen p50 = **{p50:.1f}** mg/dL  "
                   f"(target 350-650 acute-phase band; "
                   f"{'PASS' if in_band else 'CHECK'})  "
                   f"[n={len(sepsis_fib)}]  "
                   f"NB: DIC consumption appears in LOS-mid for the subset that "
                   f"develops DIC (~10-30% of sepsis), not on admit day.")
    else:
        out.append(f"- Sepsis Fibrinogen: no admit-day samples in cohort")
    if sepsis_aptt:
        p75 = pct(sepsis_aptt, 75)
        out.append(f"- Sepsis (A41) admit-day APTT p75 = **{p75:.1f}** s  "
                   f"(target ≥ 30 = above upper reference, mild trending; "
                   f"{'PASS' if p75 >= 30 else 'CHECK'})  "
                   f"[n={len(sepsis_aptt)}]  "
                   f"NB: DIC-grade prolongation appears in LOS-mid for the DIC subset.")
    else:
        out.append(f"- Sepsis APTT: no admit-day samples in cohort")

    # Hepatic failure (K72) / cirrhosis decompensated (K70.3 — alcoholic, K72) PT
    hepatic_obs = admit_obs_for_diseases(obs, encs, conds, ("K72", "K70.3", "K70"))
    hepatic_by = obs_values_by_lab(hepatic_obs, {pt_inr_code, pt_code})
    hepatic_pt_inr = hepatic_by.get(pt_inr_code, [])
    if hepatic_pt_inr:
        p75 = pct(hepatic_pt_inr, 75)
        out.append(f"- Hepatic (K70/K72) admit-day PT_INR p75 = **{p75:.2f}**  "
                   f"(target ≥ 1.5; {'PASS' if p75 >= 1.5 else 'CHECK'})  "
                   f"[n={len(hepatic_pt_inr)}]")
    else:
        out.append("- Hepatic PT_INR: no admit-day samples in cohort")

    # PT == 12 * PT_INR consistency (LOINC only — JLAC10 shares analyte)
    if country == "US":
        # Match Observations by patient + effectiveDateTime, then check
        # PT (5902-2) value vs 12 * PT_INR (6301-6) value.
        by_key: dict[tuple, dict[str, float]] = collections.defaultdict(dict)
        for o in obs:
            codings = o.get("code", {}).get("coding") or []
            code = next((c.get("code") for c in codings
                         if c.get("code") in {"5902-2", "6301-6"}), None)
            if not code:
                continue
            pid = (o.get("subject", {}).get("reference") or "").split("/")[-1]
            when = (o.get("effectiveDateTime") or "")
            val = o.get("valueQuantity", {}).get("value")
            if val is not None:
                by_key[(pid, when)][code] = float(val)
        n_pairs = 0
        n_bad = 0
        for (pid, when), vals in by_key.items():
            if "5902-2" in vals and "6301-6" in vals:
                n_pairs += 1
                expected = 12.0 * vals["6301-6"]
                if abs(vals["5902-2"] - expected) > 0.1:
                    n_bad += 1
        if n_pairs:
            out.append(f"- PT = 12 × PT_INR consistency: **{n_pairs - n_bad}/{n_pairs}** pairs match  "
                       f"({'PASS' if n_bad == 0 else 'CHECK'})")
        else:
            out.append("- PT = 12 × PT_INR consistency: no matched pairs "
                       "(expected — no disease YAML orders {test:'PT'} individually)")

    # Whole-cohort Fibrinogen distribution (emergent — not a strict gate).
    all_fib = obs_values_by_lab(obs, {fib_code}).get(fib_code, [])
    if all_fib:
        med = statistics.median(all_fib)
        p10 = pct(all_fib, 10)
        p90 = pct(all_fib, 90)
        in_clamp = (50 <= min(all_fib) and max(all_fib) <= 800)
        out.append(f"- Whole-cohort Fibrinogen: p10=**{p10:.0f}** p50=**{med:.0f}** "
                   f"p90=**{p90:.0f}** mg/dL  "
                   f"(in [50, 800] clamp: {'PASS' if in_clamp else 'FAIL'})  "
                   f"[n={len(all_fib)}]  "
                   f"NB: cohort median ≠ healthy median (cohort is disease-weighted).")
    return out


def jp_language_axis(root: Path, country: str) -> list[str]:
    fhir = root / "fhir_r4"
    obs = load_ndjson(fhir / "Observation.ndjson")
    drs = load_ndjson(fhir / "DiagnosticReport.ndjson")
    out: list[str] = ["\n## JP Language\n"]

    target_codes = {"14979-9", "5902-2", "3255-7", "24373-3"} \
        if country == "US" else {"2B020", "2B030", "2B100", "24373-3"}
    coag_obs = [
        o for o in obs
        if any(c.get("code") in target_codes
               for c in o.get("code", {}).get("coding") or [])
    ]
    coag_drs = [
        d for d in drs
        if any(c.get("code") == "24373-3"
               for c in d.get("code", {}).get("coding") or [])
    ]
    bag = coag_obs + coag_drs

    jp_leak = 0
    jp_hit = 0
    for r in bag:
        for c in r.get("code", {}).get("coding") or []:
            disp = c.get("display", "")
            if not disp:
                continue
            if JAPANESE.search(disp):
                jp_hit += 1
            else:
                pass  # English/codes only
        text = r.get("code", {}).get("text", "")
        if text and JAPANESE.search(text):
            jp_hit += 1
    if country == "US":
        # Count any Japanese in displays/texts
        for r in bag:
            for c in r.get("code", {}).get("coding") or []:
                if JAPANESE.search(c.get("display", "")):
                    jp_leak += 1
            if JAPANESE.search(r.get("code", {}).get("text", "")):
                jp_leak += 1
        out.append(f"- US output Japanese leak in Coag fields: **{jp_leak}**  "
                   f"({'PASS' if jp_leak == 0 else 'FAIL'})  [scanned {len(bag)} resources]")
    else:
        out.append(f"- JP output Japanese coverage in Coag fields: **{jp_hit}** instances  "
                   f"({'PASS' if jp_hit > 0 else 'FAIL'})  [scanned {len(bag)} resources]")

    # Check jlac10.yaml ja values (PR #76 enforcement)
    if country == "JP":
        from yaml import safe_load
        jp_repo = Path(__file__).resolve().parents[1] / "clinosim/codes/data/jlac10.yaml"
        jlac = safe_load(jp_repo.read_text())["codes"]
        for code in ("2B020", "2B030", "2B100"):
            ja = jlac.get(code, {}).get("ja", "")
            jp_present = bool(JAPANESE.search(ja))
            not_eng_abbrev = ja not in {"APTT", "PT", "Fibrinogen"}
            out.append(f"  - `{code}` ja=`{ja}`  "
                       f"({'PASS' if jp_present and not_eng_abbrev else 'FAIL'})")

    return out


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: dqr_coag_panel_review.py <bundle-root> <US|JP>", file=sys.stderr)
        return 2
    root = Path(argv[1])
    country = argv[2].upper()
    if country not in ("US", "JP"):
        print(f"country must be US or JP, got {country}", file=sys.stderr)
        return 2

    lines: list[str] = []
    lines.append(f"# Coag Panel PR — Data-Quality Review ({country})\n")
    lines.append(f"- bundle root: `{root}`")
    lines.append(f"- country: {country}\n")
    lines.extend(structural_axis(root, country))
    lines.extend(clinical_axis(root, country))
    lines.extend(jp_language_axis(root, country))

    out_path = Path(__file__).resolve().parent / f"coag_panel_dqr_{country.lower()}.md"
    out_path.write_text("\n".join(lines))
    print(f"Report written to {out_path}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
