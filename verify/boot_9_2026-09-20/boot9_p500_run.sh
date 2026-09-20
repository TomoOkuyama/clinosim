#!/usr/bin/env bash
# Boot 9 bonus: US p=500 s=2919 canonical EN, same config as p=1000 above
set -euo pipefail
source ~/vllm-env/bin/activate
cd ~/clinosim && export PYTHONPATH=.

CIF_DIR=/home/ubuntu/boot9_us_p500/verify-us-p500-s2919/cif
LLM_CONFIG=/home/ubuntu/verify/llm_service_vllm.yaml
OUT_LOG=~/boot9_p500_narrate.log

START_TS=$(date +%s)
echo "boot9_p500_start_epoch=$START_TS" | tee -a $OUT_LOG

time clinosim narrate \
    --cif-dir "$CIF_DIR" \
    --provider vllm \
    --llm-config "$LLM_CONFIG" \
    --country US \
    --concurrency 64 \
    --version-id boot9_us_p500 2>&1 | tee -a $OUT_LOG

END_TS=$(date +%s)
echo "boot9_p500_end_epoch=$END_TS" | tee -a $OUT_LOG
echo "boot9_p500_elapsed_seconds=$(( END_TS - START_TS ))" | tee -a $OUT_LOG

curl -s http://127.0.0.1:8000/metrics > ~/boot9_p500_metrics_after.txt
