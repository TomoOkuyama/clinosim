#!/usr/bin/env python3
"""Run A/B narrative test on EC2.

Reads prompt JSON files (from prepare_ab_test_prompts.py), calls Bedrock
directly using the configured provider, writes generated text + metadata.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from clinosim.modules.llm_service.factory import build_from_config_file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts-dir", required=True)
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--llm-config", required=True)
    args = ap.parse_args()

    prompts_root = Path(args.prompts_dir)
    results_root = Path(args.results_dir)
    results_root.mkdir(parents=True, exist_ok=True)

    # Build LLM service from YAML (provides Bedrock provider + cache)
    svc = build_from_config_file(Path(args.llm_config))
    provider = svc.narrative_provider
    if provider is None:
        raise RuntimeError("No narrative provider configured")
    model_id = (
        svc.narrative_model_map.get("medium")
        or svc.narrative_model_map.get("large")
        or svc.narrative_model_map.get("small")
        or svc.narrative_model_map.get("default", "")
    )
    provider_key = getattr(provider, "__class__", type(provider)).__name__

    prompt_files = sorted(prompts_root.rglob("*.json"))
    print(f"Found {len(prompt_files)} prompt files")
    print(f"Provider: {provider_key}  Model: {model_id}")
    print()

    total_in = 0
    total_out = 0
    start = time.time()

    for idx, pf in enumerate(prompt_files, 1):
        blob = json.loads(pf.read_text(encoding="utf-8"))
        rel = pf.relative_to(prompts_root)
        out_file = results_root / rel
        out_file.parent.mkdir(parents=True, exist_ok=True)

        # Skip if already generated (resumable)
        if out_file.exists():
            print(f"[{idx}/{len(prompt_files)}] SKIP (exists): {rel}")
            continue

        try:
            t0 = time.time()
            resp = provider.complete(
                prompt=blob["user_prompt"],
                model=model_id,
                max_tokens=blob.get("max_tokens", 1500),
                system_prompt=blob["system_prompt"],
            )
            elapsed = time.time() - t0
            out_blob = {
                **{k: v for k, v in blob.items() if k not in ("system_prompt", "user_prompt")},
                "generated_text": resp.text,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "model": resp.model or model_id,
                "latency_ms": int(elapsed * 1000),
            }
            out_file.write_text(
                json.dumps(out_blob, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            total_in += resp.input_tokens
            total_out += resp.output_tokens
            print(f"[{idx}/{len(prompt_files)}] {rel} — in={resp.input_tokens} out={resp.output_tokens} ({elapsed:.1f}s)")
        except Exception as e:
            print(f"[{idx}/{len(prompt_files)}] FAIL: {rel} — {e}")

    elapsed = time.time() - start
    print()
    print(f"=== Summary ===")
    print(f"  Total tokens: in={total_in:,} out={total_out:,}")
    print(f"  Elapsed: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
