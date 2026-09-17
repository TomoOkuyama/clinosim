"""Post-hoc analysis of a completed narrate throughput verify run.

Reads $OUT_DIR (scp'd back from H100) and produces:
  - Factor breakdown table (Cases A / A' / E / D / concurrency sweep)
  - L1/L2/L3 throughput per case
  - vLLM /v1/metrics diffs (prefix cache hits, tokens/sec, running req)
  - GPU utilization (from nvidia-smi dmon)
  - Recommendation section

Usage:
    python verify/analyze.py --out-dir /path/to/verify/out

Measurement layers (from most-authoritative to most-conflated):

  L1 (pure LLM speed, PRIMARY):
     Server-side /v1/metrics deltas of `vllm:generation_tokens_total`
     and `vllm:e2e_request_latency_seconds_*`. Excludes narrate client
     setup / CIF I/O / prompt build / output save — measures ONLY what
     happens between the HTTP request hitting vLLM and vLLM emitting the
     final token. This is the metric the goal statement in WORK.md is
     about ("pure LLM 生成速度").

  L2 (narrate measurement wall, SECONDARY):
     Wall-clock between narrate CLI start and end. Includes CIF parse,
     prompt build, HTTP overhead, output save. Excludes vLLM startup
     and warmup narrate. Useful for end-to-end operator experience
     ("how long does narrating N docs take") but not for pure LLM
     tuning decisions.

  L3 (total wall, PARENTHETICAL only):
     Warmup + measurement + all narrate overhead. Includes reflex-level
     confounds. Reported only to sanity-check that L2 tracks it.

Primary throughput answers come from L1. If L1 and L2 diverge sharply,
that's itself a finding (narrate CLI is bottlenecking, not the LLM).
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# vLLM Prometheus metric names we care about.
METRICS = [
    "vllm:prompt_tokens_total",
    "vllm:generation_tokens_total",
    "vllm:num_requests_running",
    "vllm:num_requests_waiting",
    "vllm:prefix_cache_hits_total",
    "vllm:prefix_cache_queries_total",
    "vllm:gpu_cache_usage_perc",
    "vllm:e2e_request_latency_seconds_count",
    "vllm:e2e_request_latency_seconds_sum",
]


@dataclass
class CaseMetrics:
    case: str
    prompt_yaml_md5: str = ""
    warmup_start: int = 0
    warmup_end: int = 0
    measure_start: int = 0
    measure_end: int = 0
    metrics_before: dict = field(default_factory=dict)
    metrics_after_warmup: dict = field(default_factory=dict)
    metrics_after: dict = field(default_factory=dict)
    nvidia_smi_summary: dict = field(default_factory=dict)


def parse_prometheus_metrics(text: str) -> dict[str, float]:
    """Very small Prometheus exposition-format parser.

    Sums all label combinations for each METRICS entry.
    """
    out: dict[str, float] = {m: 0.0 for m in METRICS}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        # Match: metric_name{labels} value  or  metric_name value
        m = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(-?[\d.eE+]+)", line)
        if not m:
            continue
        name, _labels, value = m.groups()
        if name in out:
            out[name] += float(value)
    return out


def parse_nvidia_smi_dmon(text: str) -> dict:
    """Parse nvidia-smi dmon (`-s pucm`) output.

    Columns after header: gpu pwr gtemp mtemp sm mem enc dec fb bar1
    We track sm (utilization %) and fb (framebuffer MB).
    """
    sm_utils = []
    fb_mbs = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        toks = line.split()
        if len(toks) < 5:
            continue
        try:
            sm = float(toks[4])
            sm_utils.append(sm)
        except (ValueError, IndexError):
            pass
        try:
            fb = float(toks[8])
            fb_mbs.append(fb)
        except (ValueError, IndexError):
            pass
    if not sm_utils:
        return {"sm_util_mean": None, "sm_util_max": None, "fb_max_mb": None, "n_samples": 0}
    return {
        "sm_util_mean": sum(sm_utils) / len(sm_utils),
        "sm_util_max": max(sm_utils),
        "fb_max_mb": max(fb_mbs) if fb_mbs else None,
        "n_samples": len(sm_utils),
    }


def load_case(case_dir: Path) -> CaseMetrics | None:
    case_id = case_dir.name.replace("case_", "")
    cm = CaseMetrics(case=case_id)

    def _read_ts(name: str) -> int:
        p = case_dir / name
        if not p.exists():
            return 0
        try:
            return int(p.read_text().strip())
        except (ValueError, OSError):
            return 0

    cm.warmup_start = _read_ts("wallclock.warmup_start")
    cm.warmup_end = _read_ts("wallclock.warmup_end")
    cm.measure_start = _read_ts("wallclock.measure_start")
    cm.measure_end = _read_ts("wallclock.measure_end")

    for phase, fname in [
        ("metrics_before", "metrics_before.txt"),
        ("metrics_after_warmup", "metrics_after_warmup.txt"),
        ("metrics_after", "metrics_after.txt"),
    ]:
        p = case_dir / fname
        if p.exists():
            setattr(cm, phase, parse_prometheus_metrics(p.read_text()))

    md5_path = case_dir / "prompt_md5.txt"
    if md5_path.exists():
        cm.prompt_yaml_md5 = md5_path.read_text().split()[0]

    smi_path = case_dir / "nvidia_smi.log"
    if smi_path.exists():
        cm.nvidia_smi_summary = parse_nvidia_smi_dmon(smi_path.read_text())

    if cm.measure_start == 0:
        return None
    return cm


def compute_derived(cm: CaseMetrics, doc_count: int = 100) -> dict:
    """Compute L1/L2/L3 metrics from raw counters."""
    d = {}
    wallclock_measure_s = max(cm.measure_end - cm.measure_start, 1)
    wallclock_total_s = max(cm.measure_end - cm.warmup_start, 1)

    # L3: raw wall-clock (includes warmup & startup overhead ONLY for the case,
    # since vLLM startup was outside run_case.sh scope)
    d["L3_total_wall_s"] = wallclock_total_s
    d["L3_docs_per_s"] = doc_count / wallclock_measure_s

    # L2: measurement-window wall-clock, warmup excluded
    d["L2_measure_wall_s"] = wallclock_measure_s
    d["L2_docs_per_s"] = doc_count / wallclock_measure_s

    # L1: server-side pure inference from /v1/metrics deltas
    before = cm.metrics_after_warmup or cm.metrics_before
    after = cm.metrics_after
    if before and after:
        d_prompt = after.get("vllm:prompt_tokens_total", 0) - before.get(
            "vllm:prompt_tokens_total", 0
        )
        d_gen = after.get("vllm:generation_tokens_total", 0) - before.get(
            "vllm:generation_tokens_total", 0
        )
        d_reqs = after.get("vllm:e2e_request_latency_seconds_count", 0) - before.get(
            "vllm:e2e_request_latency_seconds_count", 0
        )
        d["L1_prompt_tokens"] = d_prompt
        d["L1_gen_tokens"] = d_gen
        d["L1_prompt_tokens_per_s"] = d_prompt / wallclock_measure_s if wallclock_measure_s else 0
        d["L1_gen_tokens_per_s"] = d_gen / wallclock_measure_s if wallclock_measure_s else 0
        d["L1_reqs"] = d_reqs
        d["L1_avg_prompt_tokens_per_req"] = d_prompt / d_reqs if d_reqs > 0 else 0
        d["L1_avg_gen_tokens_per_req"] = d_gen / d_reqs if d_reqs > 0 else 0

        d_pc_hits = after.get("vllm:prefix_cache_hits_total", 0) - before.get(
            "vllm:prefix_cache_hits_total", 0
        )
        d_pc_q = after.get("vllm:prefix_cache_queries_total", 0) - before.get(
            "vllm:prefix_cache_queries_total", 0
        )
        d["prefix_cache_hit_rate"] = d_pc_hits / d_pc_q if d_pc_q > 0 else None

    return d


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--doc-count", type=int, default=100,
                   help="expected docs per case measurement (default 100)")
    args = p.parse_args()

    cases = []
    for case_dir in sorted(args.out_dir.glob("case_*")):
        if case_dir.is_dir() and not case_dir.name.endswith("_scratch"):
            cm = load_case(case_dir)
            if cm is None:
                print(f"  ! skipping {case_dir.name} (no measurement window)")
                continue
            derived = compute_derived(cm, doc_count=args.doc_count)
            cases.append((cm, derived))

    if not cases:
        print("no cases found under", args.out_dir)
        return

    # Header
    print("=" * 100)
    print(f"{'case':10s} {'L2 wall':>9s} {'L2 doc/s':>9s} "
          f"{'L1 gen tok/s':>13s} {'avg prompt':>11s} {'avg gen':>8s} "
          f"{'PC hit':>7s} {'SM util':>8s}")
    print("=" * 100)
    for cm, d in cases:
        pc = d.get("prefix_cache_hit_rate")
        sm = cm.nvidia_smi_summary.get("sm_util_mean")
        pc_str = f"{pc*100:5.1f}%" if isinstance(pc, float) else "  -  "
        sm_str = f"{sm:5.1f}%" if isinstance(sm, float) else "  -  "
        print(
            f"{cm.case:10s} "
            f"{d.get('L2_measure_wall_s', 0):>7d} s "
            f"{d.get('L2_docs_per_s', 0):>9.3f} "
            f"{d.get('L1_gen_tokens_per_s', 0):>13.1f} "
            f"{d.get('L1_avg_prompt_tokens_per_req', 0):>11.0f} "
            f"{d.get('L1_avg_gen_tokens_per_req', 0):>8.0f} "
            f"{pc_str:>7s} "
            f"{sm_str:>8s}"
        )

    print("=" * 100)

    # Factor breakdown
    by_case = {cm.case: (cm, d) for cm, d in cases}
    print("\nFactor breakdown (dps = doc/s):")

    def _pct(new, base):
        if base <= 0:
            return "n/a"
        return f"{100*(new-base)/base:+.1f}%"

    def _cmp(label, base_case, target_case):
        if base_case in by_case and target_case in by_case:
            b = by_case[base_case][1]["L2_docs_per_s"]
            t = by_case[target_case][1]["L2_docs_per_s"]
            print(f"  {label}: {base_case} {b:.3f} → {target_case} {t:.3f} dps  ({_pct(t, b)})")

    _cmp("Factor A (JA→EN prompt scaffold)",   "A", "A_prime")
    _cmp("Factor B+C (v22→v21 content)",       "A", "E")
    _cmp("Factor D (max-len 16k→12k)",         "A", "D_revised")
    _cmp("Fix A (prompt struct — Case F)",     "A", "F")
    _cmp("Fix A + Fix B (KV FP8 — Case G)",    "A", "G")
    _cmp("Fix A + Fix B + conc 64 (G_c64)",    "A", "G_c64")

    # Concurrency ceiling (theory predicts A_c128 ≈ A due to KV budget bound)
    if "A" in by_case and "A_c128" in by_case:
        a = by_case["A"][1]["L2_docs_per_s"]
        c128 = by_case["A_c128"][1]["L2_docs_per_s"]
        print(f"  Concurrency ceiling (theory: no gain past ~22 seqs @ FP16 KV):")
        print(f"    A_c32 {a:.3f} → A_c128 {c128:.3f} dps ({_pct(c128, a)})")

    # Total recovery vs the 1.35 baseline
    if "A" in by_case:
        a = by_case["A"][1]["L2_docs_per_s"]
        for target in ["F", "G", "G_c64"]:
            if target in by_case:
                t = by_case[target][1]["L2_docs_per_s"]
                gap_to_baseline = 1.35 - a
                recovery = (t - a) / gap_to_baseline if gap_to_baseline > 0 else 0
                print(f"  Recovery toward 1.35 baseline via {target}: "
                      f"{100*recovery:+.1f}% of the regression gap closed")

    # Dump raw
    dump_path = args.out_dir / "analysis.json"
    dump_path.write_text(json.dumps({
        "cases": [
            {
                "case": cm.case,
                "wallclock": {
                    "warmup_start": cm.warmup_start,
                    "warmup_end": cm.warmup_end,
                    "measure_start": cm.measure_start,
                    "measure_end": cm.measure_end,
                },
                "prompt_md5": cm.prompt_yaml_md5,
                "metrics_deltas": derived,
                "nvidia_smi": cm.nvidia_smi_summary,
            }
            for cm, derived in cases
        ]
    }, indent=2, default=str))
    print(f"\nsaved: {dump_path}")


if __name__ == "__main__":
    main()
