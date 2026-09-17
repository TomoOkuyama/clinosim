#!/usr/bin/env bash
# verify/vllm_start_8k.sh — start vLLM with max-model-len 8192.
#
# Case D config: test whether the S117 widening from 8192 → 16384 is the
# dominant cause of the 1.35 → 0.68 doc/s throughput regression.
#
# Same flags as vllm_start_16k.sh EXCEPT --max-model-len.
#
# Compatibility note: some v22 prompts + p=100 cohorts may generate
# prompt+response pairs >8192 tokens (S117 observed a 12289-token pair
# on a pre-existing 8192 limit). vLLM will 400 those requests. narrate
# should retry / abort gracefully, but if we see >5% error rate we know
# we hit that ceiling.

set -euo pipefail

MODEL="${VLLM_MODEL:-Qwen/Qwen3.8-27B-FP8}"

exec vllm serve "$MODEL" \
    --host 127.0.0.1 \
    --port 8000 \
    --max-model-len 8192 \
    --enable-prefix-caching \
    --gpu-memory-utilization 0.9 \
    --max-num-seqs 256 \
    --dtype auto \
    --gdn-prefill-backend triton \
    --served-model-name Qwen/Qwen3.8-27B-FP8
