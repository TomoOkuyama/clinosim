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

# Activate the vllm-env venv where clinosim + vllm live.
# shellcheck source=/dev/null
source "${VLLM_VENV:-$HOME/vllm-env}/bin/activate"

VERIFY_DIR="${VERIFY_DIR:-$HOME/verify}"
OUT_DIR="${OUT_DIR:-$HOME/verify/out}"
VLLM_URL="${VLLM_URL:-http://localhost:8000}"
CLINOSIM_DIR="${CLINOSIM_DIR:-$HOME/clinosim}"

# Failed Run 1 (2026-09-17) hit vLLM's internal 600s engine-core-ready
# timeout during first-time CUDA graph capture. Boot 2 sets a generous
# 1800s ceiling for both the vLLM-side timeout and our own shell wait.
export VLLM_ENGINE_READY_TIMEOUT_S=1800

export VERIFY_DIR OUT_DIR VLLM_URL CLINOSIM_DIR

mkdir -p "$OUT_DIR"
echo "=== S117 narrate throughput verify @ $(date -u +%FT%TZ) ===" | tee "$OUT_DIR/run.log"

# -----------------------------------------------------------
# Step -2: Capture S117 baseline vLLM startup command from bash history
# BEFORE cleanup wipes any log evidence. This is the authoritative source
# of what flags S117 actually used — verify Case A's config matches (or
# note the differences).
# -----------------------------------------------------------
echo "--- Step -2: extract S117 vLLM config from history ---" | tee -a "$OUT_DIR/run.log"
{
    echo "=== S117 vllm serve command history (H100 shell) ==="
    grep -a "vllm serve\|vllm-serve" ~/.bash_history 2>/dev/null || echo "no vllm serve in .bash_history"
    echo
    echo "=== Any related config files in \$HOME ==="
    ls -la ~/vllm*.sh ~/start_vllm* ~/serve*.sh 2>/dev/null || echo "no local vllm scripts"
    echo
    echo "=== Recent processes (in case vLLM was in a systemd unit) ==="
    ps auxf 2>/dev/null | grep -E "vllm|python.*serve" | grep -v grep || echo "no live vLLM"
} | tee "$OUT_DIR/s117_vllm_config_recovery.txt"
echo "→ review $OUT_DIR/s117_vllm_config_recovery.txt to reconcile with verify/vllm_start_16k.sh" | tee -a "$OUT_DIR/run.log"

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
# Helper: start a vLLM config, wait ready, or abort.
# -----------------------------------------------------------
start_vllm() {
    local script="$1" logname="$2"
    echo "--- start vLLM: $script ($(date -u +%FT%TZ)) ---" | tee -a "$OUT_DIR/run.log"
    bash "$VERIFY_DIR/$script" > "$OUT_DIR/$logname" 2>&1 &
    VLLM_PID=$!
    echo "vLLM PID: $VLLM_PID" | tee -a "$OUT_DIR/run.log"
    # First-time vLLM boot on H100 = ~17-18 min (weight load 3.3 min +
    # torch.compile 2 min [cached after first success] + CUDA graph
    # capture ~12 min per process). Wait up to 1800s = 30 min.
    for i in {1..1800}; do
        if curl -sSf "$VLLM_URL/v1/models" >/dev/null 2>&1; then
            echo "  vLLM ready after ${i}s ($(date -u +%FT%TZ))" | tee -a "$OUT_DIR/run.log"
            return 0
        fi
        # Every 60s, echo a progress marker so log tails know we're alive.
        if (( i % 60 == 0 )); then
            local latest_line
            latest_line=$(tail -1 "$OUT_DIR/$logname" 2>/dev/null | tr -d '\r' | cut -c 1-120)
            echo "  … waiting ${i}s (last vllm log line: $latest_line)" | tee -a "$OUT_DIR/run.log"
        fi
        sleep 1
    done
    echo "ERROR: vLLM $script did not become ready within 1800s" | tee -a "$OUT_DIR/run.log"
    kill $VLLM_PID 2>/dev/null || true
    exit 1
}

stop_vllm() {
    kill $VLLM_PID 2>/dev/null || true
    wait $VLLM_PID 2>/dev/null || true
    sleep 3
}

# -----------------------------------------------------------
# vLLM #0: S117 EXACT replay (recovered from vllm_p100_v5.log):
# max_model_len=16384, gpu-mem=0.88, max-num-seqs=32, PREFIX-CACHING OFF,
# kv-cache-dtype=auto (FP16 default). Reproduces the 0.68 doc/s baseline.
# -----------------------------------------------------------
start_vllm vllm_start_16k_S117.sh vllm_16k_S117.log

# Case A_S117: pure S117 replay (v22 JA, prefix-caching OFF, gpu-mem 0.88)
run_one A_S117 "$VERIFY_DIR/v22_prompt_ja.yaml" 32

# -----------------------------------------------------------
# vLLM #1: same as #0 but --enable-prefix-caching ON.
# Case A_pc measures Factor E in isolation (just turn PC on).
# -----------------------------------------------------------
stop_vllm
start_vllm vllm_start_16k.sh vllm_16k.log

# -----------------------------------------------------------
# Cases running on 16k config.
# -----------------------------------------------------------
run_one() {
    local case_id="$1" prompt="$2" conc="$3" llm_config="${4:-}"
    bash "$VERIFY_DIR/run_case.sh" "$case_id" "$prompt" "$conc" "$llm_config" 2>&1 | tee -a "$OUT_DIR/run.log"
}

# -----------------------------------------------------------
# Cases on vLLM #1 config: max-len 16384, FP16 KV (S117 baseline).
# Revised per RESEARCH_FINDINGS.md — Case D at 8k dropped as unviable,
# Case A_c64 dropped (no theoretical gain at FP16 KV ceiling).
# -----------------------------------------------------------

# Case A_pc: Factor E in isolation (S117 config + prefix-caching ON)
run_one A_pc    "$VERIFY_DIR/v22_prompt_ja.yaml" 32

# Case A': Factor A isolation (EN scaffold, PC on, conc 32)
run_one A_prime "$VERIFY_DIR/v22_prompt_en.yaml" 32

# Case E: Factor B+C (v21 JA, PC on, conc 32)
run_one E       "$VERIFY_DIR/v21_prompt_ja.yaml" 32

# Case A_pc_c128: does concurrency scale up now with PC on?
run_one A_pc_c128 "$VERIFY_DIR/v22_prompt_ja.yaml" 128

# Case F: Fix A alone (PC on, prompt structure fix)
run_one F       "$VERIFY_DIR/v22_prompt_ja_fixA.yaml" 32

# Case J: Fix C (vLLM guided_json / structured output) — user's
# "fallback 0" goal. Same PC-on config, v22 JA baseline prompt, but
# routed through llm_service_vllm_guided.yaml which sets
# response_format={"type":"json_object"}. Expect fallback_summary.txt
# to show json_parse=0 across the case. Speed may drop 3-5% from
# xgrammar overhead; that trade-off vs eliminating parse failures is
# worth it if fallback rate on Case A_pc is nonzero.
run_one J       "$VERIFY_DIR/v22_prompt_ja.yaml" 32 llm_service_vllm_guided.yaml

# -----------------------------------------------------------
# vLLM #2: PC on + --kv-cache-dtype fp8. Fix B tests.
# -----------------------------------------------------------
stop_vllm
start_vllm vllm_start_16k_fp8kv.sh vllm_16k_fp8kv.log

# Case G: Fix A + Fix B (prompt struct + KV FP8, PC on, conc 32)
run_one G       "$VERIFY_DIR/v22_prompt_ja_fixA.yaml" 32

# Case G_c64: Fix A + Fix B + true concurrency scaling
run_one G_c64   "$VERIFY_DIR/v22_prompt_ja_fixA.yaml" 64

# -----------------------------------------------------------
# vLLM #3: PC on + max-model-len 12288 (S117 pre-widening).
# -----------------------------------------------------------
stop_vllm
start_vllm vllm_start_12k.sh vllm_12k.log

# Case D_revised: Factor D revised (max-model-len 12288 — S117 pre-widening).
# Uses current v22 JA prompt (max_tokens=3500). Expect ~5-10% of docs to
# 400-fail — XLARGE contexts exceed 12288+3500. Records failure rate.
run_one D_revised "$VERIFY_DIR/v22_prompt_ja.yaml" 32

# Case H: Level-1 tuning — Fix A + max_tokens=2500 + max-len 12288 (all
# FP16 KV, conc 32). Tests whether narrower response budget (3500→2500)
# is sufficient to make max-len 12288 viable — addressing user's
# "16384 is over-fit to 1 outlier doc" observation. If H succeeds with
# 0 truncations AND matches or beats D_revised throughput, then
# max-model-len 12288 with max_tokens=2500 is a clear quality-preserving
# improvement (smaller KV budget per seq → more concurrency headroom).
run_one H "$VERIFY_DIR/v22_prompt_ja_fixA_maxtok2500.yaml" 32

# -----------------------------------------------------------
# Wrap up.
# -----------------------------------------------------------
stop_vllm

echo "=== all cases done @ $(date -u +%FT%TZ) ===" | tee -a "$OUT_DIR/run.log"
echo "output: $OUT_DIR"
