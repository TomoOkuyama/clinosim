"""PR2 audit: empirical per-panel per-day component-count distribution.

Validates (does not derive) the canonical-N − 1 rule for CBC and BMP
min_components in lab_panel_groups.yaml. Generates a US p=4000 / JP p=4000
bundle on the current tree at seed=42, walks the resulting Observation.ndjson
+ orders.csv, then reports the distribution split into two buckets per panel:

  (a) panel-order-was-placed   ← the bucket whose 5th-percentile must be
                                  ≥ canonical N − 1 for the rule to hold.
  (b) post-hoc-coincidence-only ← bucket grouped only because individual
                                  lab orders co-occurred on the same day
                                  without a {test: "CBC"} / {test: "BMP"}
                                  parent order.

If (a)'s 5th-percentile is below the planned threshold, the spec returns
to brainstorming.
"""
import collections
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# LOINC → canonical analyte. Verified against
# docs/reviews/2026-06-23-cbc-bmp-byte-diff.md (US-branch audit table) and
# clinosim/codes/data/loinc.yaml. The audit only cares about US bundles
# because JP uses JLAC10 codes, which require a parallel mapping that is
# unnecessary for the rule-validation we're doing (per-panel grouping
# semantics are identical across locales).
LOINC_TO_COMPONENT = {
    "6690-2": "WBC", "718-7": "Hb", "4544-3": "Hct", "777-3": "Plt",
    "2951-2": "Na", "2823-3": "K", "1963-8": "HCO3", "3094-0": "BUN",
    "2160-0": "Creatinine", "2345-7": "Glucose",
    # Cl (2075-0) and Ca (17861-6) don't emit until derive_lab_values adds them.
}

CBC_COMPONENTS = {"WBC", "Hb", "Hct", "Plt"}
BMP_COMPONENTS = {"Na", "K", "HCO3", "BUN", "Creatinine", "Glucose"}  # 6 emit-able


def run_simulator(cwd: Path, out_dir: Path, country: str, n: int, seed: int = 42) -> None:
    subprocess.run([
        sys.executable, "-m", "clinosim.simulator.cli",
        "generate", "--country", country, "-p", str(n), "-s", str(seed),
        "-o", str(out_dir), "--format", "fhir", "csv",
    ], check=True, cwd=cwd)


def load_lab_observations(fhir_dir: Path):
    """Yield (encounter_id, day, component) for every lab Observation."""
    with open(fhir_dir / "Observation.ndjson") as f:
        for line in f:
            o = json.loads(line)
            if not o.get("id", "").startswith("lab-"):
                continue
            loinc = o["code"]["coding"][0].get("code", "")
            comp = LOINC_TO_COMPONENT.get(loinc)
            if not comp:
                continue
            enc_ref = (o.get("encounter") or {}).get("reference", "")
            enc_id = enc_ref.split("/")[-1] if enc_ref else ""
            day = (o.get("effectiveDateTime") or "")[:10]
            if enc_id and len(day) == 10:
                yield (enc_id, day, comp)


def load_panel_orders(csv_dir: Path):
    """Return {(encounter_id, day): set of panel display_names}."""
    out: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    with open(csv_dir / "orders.csv") as f:
        for row in csv.DictReader(f):
            if row["display_name"] in {"CBC", "BMP"}:
                day = (row["ordered_datetime"] or "")[:10]
                if len(day) == 10:
                    out[(row["encounter_id"], day)].add(row["display_name"])
    return out


def bucket_distributions(fhir_dir: Path, csv_dir: Path):
    """Return per-panel {with_parent: Counter[N], coincidence: Counter[N]}."""
    panel_orders = load_panel_orders(csv_dir)

    cbc_buckets: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    bmp_buckets: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for enc, day, comp in load_lab_observations(fhir_dir):
        key = (enc, day)
        if comp in CBC_COMPONENTS:
            cbc_buckets[key].add(comp)
        if comp in BMP_COMPONENTS:
            bmp_buckets[key].add(comp)

    out = {
        "CBC": {"with_parent": collections.Counter(),
                "coincidence":   collections.Counter()},
        "BMP": {"with_parent": collections.Counter(),
                "coincidence":   collections.Counter()},
    }
    for key, comps in cbc_buckets.items():
        if not comps:
            continue
        b = "with_parent" if "CBC" in panel_orders.get(key, set()) else "coincidence"
        out["CBC"][b][len(comps)] += 1
    for key, comps in bmp_buckets.items():
        if not comps:
            continue
        b = "with_parent" if "BMP" in panel_orders.get(key, set()) else "coincidence"
        out["BMP"][b][len(comps)] += 1
    return out


def percentile(counter, p: float) -> int:
    """Approximate p-th percentile from a Counter[component_count].

    `p` is in [0, 100]. The returned value is the smallest component_count
    `n` such that the cumulative fraction of buckets with size <= n is >= p%.
    With p=5 this returns a conservative *floor*: 95% of buckets have at
    least this many components.
    """
    items = sorted(counter.items())
    total = sum(c for _, c in items)
    if total == 0:
        return 0
    cutoff = total * p / 100.0
    running = 0
    for n, c in items:
        running += c
        if running >= cutoff:
            return n
    return items[-1][0]


def report(dist) -> int:
    """Pretty-print + validate. Return number of failures."""
    failures = 0
    plan = {"CBC": 3, "BMP": 5}
    canonical = {"CBC": 4, "BMP": 6}
    for panel, buckets in dist.items():
        wp = buckets["with_parent"]
        co = buckets["coincidence"]
        print(f"\n=== {panel} ===")
        print("  components-present distribution (with panel order):")
        for n in sorted(wp):
            print(f"    {n} components: {wp[n]:5d}")
        print("  components-present distribution (coincidence only):")
        for n in sorted(co):
            print(f"    {n} components: {co[n]:5d}")
        floor = percentile(wp, 5.0)
        canonical_minus_one = canonical[panel] - 1
        chosen = plan[panel]
        verdict = "PASS" if floor >= chosen else "FAIL"
        if verdict == "FAIL":
            failures += 1
        print(f"  5th-percentile floor (with panel order) = {floor}")
        print(f"  canonical N − 1 (proposed threshold)    = {canonical_minus_one}")
        print(f"  Verdict: {verdict}  (chosen min_components = {chosen})")
    return failures


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="cbcbmp-pr2-audit-"))
    us = work / "us"
    jp = work / "jp"
    print("Generating US p=4000 / JP p=4000 on the current tree (seed=42)...")
    run_simulator(REPO, us, "US", 4000)
    run_simulator(REPO, jp, "JP", 4000)

    print("\n##### US #####")
    us_dist = bucket_distributions(us / "fhir_r4", us / "csv")
    us_failures = report(us_dist)

    # JP runs with JLAC10 codes (not in LOINC_TO_COMPONENT), so JP-side
    # validation is left to the byte-diff cohort-drift gate in Task 5.
    # The structural rule itself is locale-independent.

    print(f"\n=== SUMMARY ===  US failures: {us_failures}")
    print(f"Outputs kept at {work} for inspection.")
    if us_failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
