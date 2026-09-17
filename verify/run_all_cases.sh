#!/usr/bin/env bash
# verify/run_all_cases.sh — sequential all-case orchestrator (H100-side).
#
# Runs the S117 narrate throughput investigation on the Sakura H100 VM.
# Assumes:
#   - $VERIFY_DIR contains: run_case.sh, vllm_start_{16k,8k}.sh,
#     v22_prompt_ja.yaml, v22_prompt_en.yaml, v21_prompt_ja.yaml,
#     cohort_p100_jp_s917.tar.gz, cohort_warmup_jp_p10_s918.tar.gz,
#     llm_service_vllm.yaml, cleanup_paths.txt
#   - $CLINOSIM_DIR is a checkout of clinosim on the VM
#   - vLLM binary is installed and its weights (Qwen3.8-27B-FP8) are
#     cached under ~/.cache/huggingface
#
# Time budget: aims to complete all cases within a single 1h billing hour
# on Sakura H100 (¥990). See verify/WORK.md for the timeline.

set -euo pipefail

VERIFY_DIR="${VERIFY_DIR:-$HOME/verify}"
OUT_DIR="${OUT_DIR:-$HOME/verify/out}"
VLLM_URL="${VLLM_URL:-http://localhost:8000}"
CLINOSIM_DIR="${CLINOSIM_DIR:-$HOME/clinosim}"

export VERIFY_DIR OUT_DIR VLLM_URL CLINOSIM_DIR

mkdir -p "$OUT_DIR"
echo "=== S117 narrate throughput verify @ $(date -u +%FT%TZ) ===" | tee "$OUT_DIR/run.log"

# -----------------------------------------------------------
# Step -1: Cleanup past data on H100 (frees disk, protects weight cache).
# -----------------------------------------------------------
echo "--- Step -1: cleanup past narrate data ---" | tee -a "$OUT_DIR/run.log"
{
    du -sh ~/* 2>/dev/null | sort -h | tail -30 || true
    echo ""
    echo "Deleting: ~/n3_cif ~/*_out ~/narrate_* ~/*.log (excluding weight cache)"
    rm -rf ~/n3_cif ~/*_out ~/narrate_* 2>/dev/null || true
    find ~/ -maxdepth 1 -name '*.tar.gz' -not -path '*/.cache/*' -delete 2>/dev/null || true
    find ~/ -maxdepth 1 -name '*.log' -delete 2>/dev/null || true
    echo ""
    echo "AFTER cleanup:"
    du -sh ~/.cache/huggingface 2>/dev/null || echo "WARNING: weight cache missing!"
    df -h ~
} | tee -a "$OUT_DIR/run.log"

# -----------------------------------------------------------
# Verify weight cache is intact BEFORE spending billing hour on vLLM start.
# -----------------------------------------------------------
if [ ! -d ~/.cache/huggingface ]; then
    echo "ERROR: ~/.cache/huggingface missing. Weight will re-DL — abort." | tee -a "$OUT_DIR/run.log"
    exit 1
fi
WEIGHT_SIZE_GB=$(du -s ~/.cache/huggingface | awk '{printf "%d", $1/1024/1024}')
if [ "$WEIGHT_SIZE_GB" -lt 40 ]; then
    echo "WARNING: weight cache smaller than expected (${WEIGHT_SIZE_GB} GB, expected ~54 GB)" | tee -a "$OUT_DIR/run.log"
fi
echo "weight cache: ${WEIGHT_SIZE_GB} GB — OK" | tee -a "$OUT_DIR/run.log"

# -----------------------------------------------------------
# Step 1: Start vLLM with max-model-len 16384 (S117 production config).
# -----------------------------------------------------------
echo "--- Step 1: start vLLM (max-model-len 16384) ---" | tee -a "$OUT_DIR/run.log"
bash "$VERIFY_DIR/vllm_start_16k.sh" > "$OUT_DIR/vllm_16k.log" 2>&1 &
VLLM_PID=$!
echo "vLLM PID: $VLLM_PID" | tee -a "$OUT_DIR/run.log"

# Wait for server ready.
echo "waiting for vLLM /v1/models to respond..." | tee -a "$OUT_DIR/run.log"
for i in {1..120}; do
    if curl -sSf "$VLLM_URL/v1/models" >/dev/null 2>&1; then
        echo "  vLLM ready after ${i}s" | tee -a "$OUT_DIR/run.log"
        break
    fi
    sleep 1
    if [ "$i" -eq 120 ]; then
        echo "ERROR: vLLM did not become ready within 120s" | tee -a "$OUT_DIR/run.log"
        kill $VLLM_PID 2>/dev/null || true
        exit 1
    fi
done

# -----------------------------------------------------------
# Cases running on 16k config.
# -----------------------------------------------------------
run_one() {
    local case_id="$1" prompt="$2" conc="$3"
    bash "$VERIFY_DIR/run_case.sh" "$case_id" "$prompt" "$conc" 2>&1 | tee -a "$OUT_DIR/run.log"
}

# Case A: baseline (v22 JA, concurrency 32)
run_one A       "$VERIFY_DIR/v22_prompt_ja.yaml" 32

# Case A': Factor A isolation (Case A' EN scaffold, concurrency 32)
run_one A_prime "$VERIFY_DIR/v22_prompt_en.yaml" 32

# Case E: Factor B+C (v21 JA, concurrency 32)
run_one E       "$VERIFY_DIR/v21_prompt_ja.yaml" 32

# Case A concurrency sweep (Factor E)
run_one A_c64   "$VERIFY_DIR/v22_prompt_ja.yaml" 64
run_one A_c128  "$VERIFY_DIR/v22_prompt_ja.yaml" 128

# -----------------------------------------------------------
# Restart vLLM with max-model-len 8192 for Case D.
# -----------------------------------------------------------
echo "--- Step 5: restart vLLM (max-model-len 8192) ---" | tee -a "$OUT_DIR/run.log"
kill $VLLM_PID
wait $VLLM_PID 2>/dev/null || true
sleep 3

bash "$VERIFY_DIR/vllm_start_8k.sh" > "$OUT_DIR/vllm_8k.log" 2>&1 &
VLLM_PID=$!
echo "vLLM PID (8k): $VLLM_PID" | tee -a "$OUT_DIR/run.log"

for i in {1..120}; do
    if curl -sSf "$VLLM_URL/v1/models" >/dev/null 2>&1; then
        echo "  vLLM ready after ${i}s" | tee -a "$OUT_DIR/run.log"
        break
    fi
    sleep 1
    if [ "$i" -eq 120 ]; then
        echo "ERROR: vLLM 8k did not become ready within 120s" | tee -a "$OUT_DIR/run.log"
        kill $VLLM_PID 2>/dev/null || true
        exit 1
    fi
done

# Case D: Factor D (v22 JA, max-model-len 8192, concurrency 32)
run_one D "$VERIFY_DIR/v22_prompt_ja.yaml" 32

# -----------------------------------------------------------
# Wrap up.
# -----------------------------------------------------------
kill $VLLM_PID 2>/dev/null || true
wait $VLLM_PID 2>/dev/null || true

echo "=== all cases done @ $(date -u +%FT%TZ) ===" | tee -a "$OUT_DIR/run.log"
echo "output: $OUT_DIR"
