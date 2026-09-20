#!/usr/bin/env bash
set -euo pipefail
source ~/vllm-env/bin/activate
cd ~/clinosim && export PYTHONPATH=.

CIF_DIR=/home/ubuntu/boot10_us_p1000_s2918/cif
LLM_CONFIG=/home/ubuntu/verify/llm_service_vllm.yaml
OUT_LOG=~/boot10_narrate.log

curl -s http://127.0.0.1:8000/metrics > ~/boot10_metrics_before.txt

START_TS=$(date +%s)
echo "boot10_start_epoch=$START_TS" | tee -a $OUT_LOG

time clinosim narrate \
    --cif-dir "$CIF_DIR" \
    --provider vllm \
    --llm-config "$LLM_CONFIG" \
    --country US \
    --concurrency 64 \
    --version-id boot10_us_p1000_s2918 2>&1 | tee -a $OUT_LOG

END_TS=$(date +%s)
echo "boot10_end_epoch=$END_TS" | tee -a $OUT_LOG
echo "boot10_elapsed_seconds=$(( END_TS - START_TS ))" | tee -a $OUT_LOG

curl -s http://127.0.0.1:8000/metrics > ~/boot10_metrics_after.txt
