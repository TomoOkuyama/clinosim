#!/usr/bin/env bash
# Boot 9 = Boot 7 exact repro: US p=1000 s=1918 canonical EN, PC ON, conc 64
set -euo pipefail
source ~/vllm-env/bin/activate
cd ~/clinosim && export PYTHONPATH=.

CIF_DIR=/home/ubuntu/boot9_us_p1000/verify-us-p1000-s1918/cif
LLM_CONFIG=/home/ubuntu/verify/llm_service_vllm.yaml
OUT_LOG=~/boot9_narrate.log

START_TS=$(date +%s)
echo "boot9_start_epoch=$START_TS" | tee -a $OUT_LOG

# Snapshot vLLM metrics before
curl -s http://127.0.0.1:8000/metrics > ~/boot9_metrics_before.txt

# Run narrate
time clinosim narrate \
    --cif-dir "$CIF_DIR" \
    --provider vllm \
    --llm-config "$LLM_CONFIG" \
    --country US \
    --concurrency 64 \
    --version-id boot9_us_bench 2>&1 | tee -a $OUT_LOG

END_TS=$(date +%s)
echo "boot9_end_epoch=$END_TS" | tee -a $OUT_LOG
echo "boot9_elapsed_seconds=$(( END_TS - START_TS ))" | tee -a $OUT_LOG

curl -s http://127.0.0.1:8000/metrics > ~/boot9_metrics_after.txt
