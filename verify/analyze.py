"""Post-hoc analysis of a completed narrate throughput verify run.

Reads $OUT_DIR (scp'd back from H100) and produces:
  - Factor breakdown table (Cases A / A' / E / D / concurrency sweep)
  - L1/L2/L3 throughput per case
  - vLLM /v1/metrics diffs (prefix cache hits, tokens/sec, running req)
  - GPU utilization (from nvidia-smi dmon)
  - Recommendation section

Usage:
    python verify/analyze.py --out-dir /path/to/verify/out
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
        print(
            f"{cm.case:10s} "
            f"{d.get('L2_measure_wall_s', 0):>7d} s "
            f"{d.get('L2_docs_per_s', 0):>9.3f} "
            f"{d.get('L1_gen_tokens_per_s', 0):>13.1f} "
            f"{d.get('L1_avg_prompt_tokens_per_req', 0):>11.0f} "
            f"{d.get('L1_avg_gen_tokens_per_req', 0):>8.0f} "
            f"{pc*100 if pc is not None else '-':>6s}"
            if isinstance(pc, float) else
            f"{cm.case:10s} "
            f"{d.get('L2_measure_wall_s', 0):>7d} s "
            f"{d.get('L2_docs_per_s', 0):>9.3f} "
            f"{d.get('L1_gen_tokens_per_s', 0):>13.1f} "
            f"{d.get('L1_avg_prompt_tokens_per_req', 0):>11.0f} "
            f"{d.get('L1_avg_gen_tokens_per_req', 0):>8.0f} "
            f"{'-':>7s} "
            f"{sm if sm is not None else '-':>7} %"
        )

    print("=" * 100)

    # Factor breakdown
    by_case = {cm.case: (cm, d) for cm, d in cases}
    print("\nFactor breakdown:")
    if "A" in by_case and "A_prime" in by_case:
        a_dps = by_case["A"][1]["L2_docs_per_s"]
        ap_dps = by_case["A_prime"][1]["L2_docs_per_s"]
        print(f"  Factor A (JA vs EN prompt): "
              f"A {a_dps:.3f} → A' {ap_dps:.3f} doc/s ({100*(ap_dps-a_dps)/a_dps:+.1f}%)")
    if "A" in by_case and "E" in by_case:
        a_dps = by_case["A"][1]["L2_docs_per_s"]
        e_dps = by_case["E"][1]["L2_docs_per_s"]
        print(f"  Factor B+C (v22 vs v21): "
              f"A {a_dps:.3f} → E {e_dps:.3f} doc/s ({100*(e_dps-a_dps)/a_dps:+.1f}%)")
    if "A" in by_case and "D" in by_case:
        a_dps = by_case["A"][1]["L2_docs_per_s"]
        d_dps = by_case["D"][1]["L2_docs_per_s"]
        print(f"  Factor D (max-len 16k vs 8k): "
              f"A {a_dps:.3f} → D {d_dps:.3f} doc/s ({100*(d_dps-a_dps)/a_dps:+.1f}%)")
    if "A" in by_case and "A_c64" in by_case and "A_c128" in by_case:
        a = by_case["A"][1]["L2_docs_per_s"]
        c64 = by_case["A_c64"][1]["L2_docs_per_s"]
        c128 = by_case["A_c128"][1]["L2_docs_per_s"]
        print(f"  Factor E (concurrency sweep A): "
              f"32→{a:.3f} 64→{c64:.3f} 128→{c128:.3f} doc/s")

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
