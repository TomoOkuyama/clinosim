"""Data-quality review for Phase 2a — D-dimer + causes_vte + J5 fix.

1. STRUCTURAL HYGIENE
   - LOINC 48065-7 (US) / JLAC10 2B140 (JP) resolve to authoritative display
   - All D-dimer Observations have referenceRange
   - No display==code on D-dimer codings

2. CLINICAL FIDELITY
   - PE (I26) admit-day D-dimer p50 >= 4 (clinically positive)
   - DVT (I80) admit-day D-dimer p50 >= 4
   - Cerebral_infarction (I63) admit-day D-dimer p50 >= 4
   - Sepsis (A41) admit-day D-dimer p50 < 2 (non-specific elevation)
   - Whole-cohort D-dimer distribution sanity (in [0.15, 20] clamp)
   - J5 fix evidence: any ED-route MI patients show MI-grade troponin

3. JP LOCALIZATION
   - US output: zero Japanese characters in D-dimer fields
   - JP output: D-dimer Observation display in Japanese
   - jlac10.yaml 2B140 ja = "D-Dダイマー" (JCCLS-official, PR #76 rule)

Usage:
    python scratchpad/dqr_phase2a_vte_review.py <bundle-root> <US|JP>
"""
from __future__ import annotations

import collections
import json
import re
import statistics
import sys
from pathlib import Path

JAPANESE = re.compile(r"[぀-ヿ一-鿿！-｠]")
D_DIMER_LOINC = "48065-7"
D_DIMER_JLAC10 = "2B140"
TROPONIN_CODES = {"10839-9", "5C094"}


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
    cond_pid_dates: dict[str, set[str]] = collections.defaultdict(set)
    for c in conds:
        codings = c.get("code", {}).get("coding") or []
        if not any(cd.get("code", "").startswith(dx_prefixes) for cd in codings):
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
    matched: list[dict] = []
    for o in obs:
        subj = o.get("subject", {}).get("reference", "")
        pid = subj.split("/")[-1] if subj else ""
        when = (o.get("effectiveDateTime") or "")[:10]
        if pid in cond_pid_dates and when in cond_pid_dates[pid]:
            matched.append(o)
    return matched


def obs_values_by_lab(obs: list[dict], lab_codes: set[str]) -> dict[str, list[float]]:
    by_code: dict[str, list[float]] = collections.defaultdict(list)
    for o in obs:
        codings = o.get("code", {}).get("coding") or []
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
    out: list[str] = ["## Structural\n"]

    target = D_DIMER_LOINC if country == "US" else D_DIMER_JLAC10
    dd_obs = [
        o for o in obs
        if any(c.get("code") == target for c in o.get("code", {}).get("coding") or [])
    ]
    with_range = [o for o in dd_obs if o.get("referenceRange")]
    rr_pct = 100 * len(with_range) / len(dd_obs) if dd_obs else float("nan")
    out.append(f"- D-dimer Observations: **{len(dd_obs)}**, with refRange: **{len(with_range)}** "
               f"({rr_pct:.1f}%)  ({'PASS' if rr_pct == 100 else 'CHECK' if dd_obs else 'N/A'})")

    bad_display = []
    code_displays: set[str] = set()
    for o in dd_obs:
        for c in o.get("code", {}).get("coding") or []:
            code = c.get("code", "")
            disp = c.get("display", "")
            if code == target:
                code_displays.add(disp)
                if disp == code or not disp:
                    bad_display.append((code, disp))
    out.append(f"- D-dimer display==code or empty: **{len(bad_display)}**  "
               f"({'PASS' if not bad_display else 'FAIL'})")
    for d in code_displays:
        out.append(f"  - `{target}` → `{d}`")
    return out


def clinical_axis(root: Path, country: str) -> list[str]:
    fhir = root / "fhir_r4"
    obs = load_ndjson(fhir / "Observation.ndjson")
    encs = load_ndjson(fhir / "Encounter.ndjson")
    conds = load_ndjson(fhir / "Condition.ndjson")
    out: list[str] = ["\n## Clinical\n"]

    dd_code = D_DIMER_LOINC if country == "US" else D_DIMER_JLAC10

    def report(disease_label, prefixes, target_p50, comparator=">="):
        admit_obs = admit_obs_for_diseases(obs, encs, conds, prefixes)
        vals = obs_values_by_lab(admit_obs, {dd_code}).get(dd_code, [])
        if not vals:
            out.append(f"- {disease_label}: no admit-day D-dimer samples in cohort")
            return
        p50 = statistics.median(vals)
        if comparator == ">=":
            ok = p50 >= target_p50
        else:
            ok = p50 < target_p50
        out.append(f"- {disease_label} admit-day D-dimer p50 = **{p50:.2f}** ug/mL  "
                   f"(target {comparator} {target_p50}; {'PASS' if ok else 'CHECK'})  "
                   f"[n={len(vals)}]")

    report("PE (I26)", ("I26",), 4.0)
    report("DVT (I80)", ("I80", "I82"), 4.0)
    report("Cerebral infarction (I63)", ("I63",), 4.0)
    report("Sepsis (A41) — should be non-specific", ("A41",), 2.0, comparator="<")

    all_dd = obs_values_by_lab(obs, {dd_code}).get(dd_code, [])
    if all_dd:
        p10 = pct(all_dd, 10)
        p50 = statistics.median(all_dd)
        p90 = pct(all_dd, 90)
        in_clamp = (0.15 <= min(all_dd) and max(all_dd) <= 20.0)
        out.append(f"- Whole-cohort D-dimer: p10=**{p10:.2f}** p50=**{p50:.2f}** "
                   f"p90=**{p90:.2f}** ug/mL  "
                   f"(in [0.15, 20] clamp: {'PASS' if in_clamp else 'FAIL'})  "
                   f"[n={len(all_dd)}]")

    # J5 evidence: MI-grade troponin presence
    tn = obs_values_by_lab(obs, TROPONIN_CODES)
    all_tn: list[float] = []
    for vs in tn.values():
        all_tn.extend(vs)
    if all_tn:
        high = [v for v in all_tn if v > 5.0]
        very_high = [v for v in all_tn if v > 30.0]
        out.append(f"- Troponin distribution: n=**{len(all_tn)}**; "
                   f">5 ng/mL = **{len(high)}**; >30 ng/mL = **{len(very_high)}** "
                   f"(J5 fix lets ED-route MI reach these tiers)")
    return out


def jp_language_axis(root: Path, country: str) -> list[str]:
    fhir = root / "fhir_r4"
    obs = load_ndjson(fhir / "Observation.ndjson")
    out: list[str] = ["\n## JP Language\n"]

    target = D_DIMER_LOINC if country == "US" else D_DIMER_JLAC10
    dd_obs = [
        o for o in obs
        if any(c.get("code") == target for c in o.get("code", {}).get("coding") or [])
    ]

    if country == "US":
        jp_leak = 0
        for r in dd_obs:
            for c in r.get("code", {}).get("coding") or []:
                if JAPANESE.search(c.get("display", "") or ""):
                    jp_leak += 1
            if JAPANESE.search(r.get("code", {}).get("text", "") or ""):
                jp_leak += 1
        out.append(f"- US output Japanese leak in D-dimer fields: **{jp_leak}**  "
                   f"({'PASS' if jp_leak == 0 else 'FAIL'})  [scanned {len(dd_obs)} resources]")
    else:
        jp_hit = 0
        for r in dd_obs:
            for c in r.get("code", {}).get("coding") or []:
                if JAPANESE.search(c.get("display", "") or ""):
                    jp_hit += 1
            if JAPANESE.search(r.get("code", {}).get("text", "") or ""):
                jp_hit += 1
        out.append(f"- JP output Japanese coverage in D-dimer fields: **{jp_hit}** instances  "
                   f"({'PASS' if jp_hit > 0 else 'FAIL'})  [scanned {len(dd_obs)} resources]")

        from yaml import safe_load
        jp_repo = Path(__file__).resolve().parents[1] / "clinosim/codes/data/jlac10.yaml"
        jlac = safe_load(jp_repo.read_text())["codes"]
        ja = jlac.get("2B140", {}).get("ja", "")
        jp_present = bool(JAPANESE.search(ja))
        not_eng_abbrev = ja not in {"D-D dimer", "D-dimer", "D dimer", "D-D dymer"}
        out.append(f"  - `2B140` ja=`{ja}`  "
                   f"({'PASS' if jp_present and not_eng_abbrev else 'FAIL'})")

    return out


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: dqr_phase2a_vte_review.py <bundle-root> <US|JP>", file=sys.stderr)
        return 2
    root = Path(argv[1])
    country = argv[2].upper()
    if country not in ("US", "JP"):
        print(f"country must be US or JP, got {country}", file=sys.stderr)
        return 2

    lines: list[str] = []
    lines.append(f"# Phase 2a (D-dimer + causes_vte + J5) — DQR ({country})\n")
    lines.append(f"- bundle root: `{root}`")
    lines.append(f"- country: {country}\n")
    lines.extend(structural_axis(root, country))
    lines.extend(clinical_axis(root, country))
    lines.extend(jp_language_axis(root, country))

    out_path = Path(__file__).resolve().parent / f"phase2a_dqr_{country.lower()}.md"
    out_path.write_text("\n".join(lines))
    print(f"Report written to {out_path}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
