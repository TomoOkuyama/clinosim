#!/usr/bin/env bash
# verify/vllm_start_12k.sh — vLLM with max-model-len 12288 (S117's
# pre-widening value per .resume-prompt.md line 24).
#
# NOTE: The original Case D plan (max-model-len 8192) is UNVIABLE.
# R1 pre-boot measurement showed the current v22 JA system: block alone
# is 11,962 tokens — even a MINIMAL context adds ~270 tokens, and with
# max_tokens=3500 response, TOTAL = 15,733 tokens per request. This
# would 400-fail on ALL requests at max-model-len 8192.
#
# max-model-len 12288 (S117 pre-widening) is the realistic "smaller"
# config. It has known behavior: S117 hit an 8789+3500=12289 pair that
# failed by 1 token → S117 widened to 16384. So Case D at 12288 will
# handle typical docs but fail on the largest ~5-10% of docs. Report
# should note the failure rate.

set -euo pipefail

MODEL="${VLLM_MODEL:-Qwen/Qwen3.8-27B-FP8}"

exec vllm serve "$MODEL" \
    --host 127.0.0.1 \
    --port 8000 \
    --max-model-len 12288 \
    --enable-prefix-caching \
    --gpu-memory-utilization 0.9 \
    --max-num-seqs 256 \
    --dtype auto \
    --served-model-name Qwen/Qwen3.8-27B-FP8
