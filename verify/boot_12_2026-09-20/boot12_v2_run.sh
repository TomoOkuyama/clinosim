#!/usr/bin/env bash
# Boot 12 v2: timeout 900s (up from 300s) — same vLLM warm cache continues
set -euo pipefail
source ~/vllm-env/bin/activate
cd ~/clinosim && export PYTHONPATH=.

CIF_DIR=/home/ubuntu/boot12_jp_p10000_s3532/cif
LLM_CONFIG=/home/ubuntu/verify/llm_service_vllm_guided.yaml
OUT_LOG=~/boot12_v2_narrate.log

curl -s http://127.0.0.1:8000/metrics > ~/boot12_v2_metrics_before.txt

START_TS=$(date +%s)
echo "boot12_v2_start_epoch=$START_TS" | tee -a $OUT_LOG

time clinosim narrate \
    --cif-dir "$CIF_DIR" \
    --provider vllm \
    --llm-config "$LLM_CONFIG" \
    --country JP \
    --concurrency 64 \
    --version-id boot12_v2_jp_p10000_s3532_guided 2>&1 | tee -a $OUT_LOG

END_TS=$(date +%s)
echo "boot12_v2_end_epoch=$END_TS" | tee -a $OUT_LOG
echo "boot12_v2_elapsed_seconds=$(( END_TS - START_TS ))" | tee -a $OUT_LOG

curl -s http://127.0.0.1:8000/metrics > ~/boot12_v2_metrics_after.txt
