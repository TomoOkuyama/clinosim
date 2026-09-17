#!/usr/bin/env bash
# verify/run_case.sh — narrate a single Case (H100-side).
#
# Runs ON THE SAKURA H100 VM (not on Mac). Assumes:
#   - vLLM server is up on http://localhost:8000
#   - clinosim is installed on the VM (git checkout of same version)
#   - $VERIFY_DIR contains the tarballs + prompt yamls (scp'd from Mac)
#   - $OUT_DIR is writable and will hold this case's output
#
# Usage:
#   run_case.sh CASE_ID PROMPT_YAML CONCURRENCY [--warmup-only]
#
# CASE_ID: identifier, e.g. "A", "A_prime", "E", "D", "A_c64", "A_c128"
# PROMPT_YAML: absolute path to the prompt yaml to use for this case
# CONCURRENCY: --concurrency value for narrate
#
# Output layout under $OUT_DIR/case_${CASE_ID}/:
#   metrics_before.txt     # /v1/metrics snapshot before warmup
#   metrics_after_warmup.txt
#   metrics_after.txt      # /v1/metrics snapshot after measurement
#   nvidia_smi.log         # nvidia-smi dmon during the case
#   narrate_warmup.log     # narrate stdout+stderr during warmup
#   narrate_measure.log    # narrate stdout+stderr during measurement
#   wallclock.json         # start/end epoch seconds for each phase
#   narrate_output/        # actual narrative JSON docs

set -euo pipefail

# Activate the vllm-env venv where clinosim + vllm live.
# shellcheck source=/dev/null
source "${VLLM_VENV:-$HOME/vllm-env}/bin/activate"

CASE_ID="${1:?usage: run_case.sh CASE_ID PROMPT_YAML CONCURRENCY}"
PROMPT_YAML="${2:?usage: run_case.sh CASE_ID PROMPT_YAML CONCURRENCY}"
CONCURRENCY="${3:?usage: run_case.sh CASE_ID PROMPT_YAML CONCURRENCY}"

VERIFY_DIR="${VERIFY_DIR:-$HOME/verify}"
OUT_DIR="${OUT_DIR:-$HOME/verify/out}"
VLLM_URL="${VLLM_URL:-http://localhost:8000}"
CLINOSIM_DIR="${CLINOSIM_DIR:-$HOME/clinosim}"
COHORT_TARBALL="${COHORT_TARBALL:-$VERIFY_DIR/cohort_p100_jp_s917.tar.gz}"
WARMUP_TARBALL="${WARMUP_TARBALL:-$VERIFY_DIR/cohort_warmup_jp_p10_s918.tar.gz}"
LLM_CONFIG="${LLM_CONFIG:-$VERIFY_DIR/llm_service_vllm.yaml}"

CASE_OUT="$OUT_DIR/case_${CASE_ID}"
mkdir -p "$CASE_OUT/narrate_output"

echo "=== case $CASE_ID :: prompt=$PROMPT_YAML :: conc=$CONCURRENCY ==="
date -u +%s > "$CASE_OUT/wallclock.start"

# -------------------------------------------------------------------
# 1. Swap the prompt yaml into the deployed clinosim tree.
#    The narrate CLI loads clinosim/modules/llm_service/prompts/ja/narrative_seed_bundle.yaml
#    so we back up the original and symlink this case's variant in.
# -------------------------------------------------------------------
DEPLOYED_JA="$CLINOSIM_DIR/clinosim/modules/llm_service/prompts/ja/narrative_seed_bundle.yaml"
BACKUP_JA="$CLINOSIM_DIR/clinosim/modules/llm_service/prompts/ja/narrative_seed_bundle.yaml.orig"

if [ ! -f "$BACKUP_JA" ]; then
    cp "$DEPLOYED_JA" "$BACKUP_JA"
    echo "backed up deployed prompt to: $BACKUP_JA"
fi
cp "$PROMPT_YAML" "$DEPLOYED_JA"
echo "swapped in prompt: $PROMPT_YAML → $DEPLOYED_JA"
md5sum "$DEPLOYED_JA" | tee "$CASE_OUT/prompt_md5.txt"

# -------------------------------------------------------------------
# 2. Extract the cohort tarballs to a case-local scratch dir.
# -------------------------------------------------------------------
CASE_SCRATCH="$OUT_DIR/case_${CASE_ID}_scratch"
rm -rf "$CASE_SCRATCH"
mkdir -p "$CASE_SCRATCH"
tar -xzf "$COHORT_TARBALL" -C "$CASE_SCRATCH"
tar -xzf "$WARMUP_TARBALL" -C "$CASE_SCRATCH"

MAIN_CIF=$(find "$CASE_SCRATCH" -maxdepth 2 -type d -name 'verify-jp-p100-*' | head -1)
WARMUP_CIF=$(find "$CASE_SCRATCH" -maxdepth 2 -type d -name 'verify-jp-p10-*warmup' | head -1)

test -d "$MAIN_CIF" || { echo "ERROR: main CIF dir not found under $CASE_SCRATCH"; exit 1; }
test -d "$WARMUP_CIF" || { echo "ERROR: warmup CIF dir not found under $CASE_SCRATCH"; exit 1; }

echo "main CIF:   $MAIN_CIF"
echo "warmup CIF: $WARMUP_CIF"

# -------------------------------------------------------------------
# 3. Start nvidia-smi dmon in background (captures GPU util during
#    both warmup + measurement windows).
# -------------------------------------------------------------------
nvidia-smi dmon -s pucm -d 1 > "$CASE_OUT/nvidia_smi.log" 2>&1 &
NV_PID=$!
trap "kill $NV_PID 2>/dev/null || true" EXIT

# -------------------------------------------------------------------
# 4. Snapshot /v1/metrics before warmup.
# -------------------------------------------------------------------
curl -sS "$VLLM_URL/metrics" > "$CASE_OUT/metrics_before.txt" || {
    echo "ERROR: cannot reach $VLLM_URL/metrics"; exit 1;
}

# -------------------------------------------------------------------
# 5. Warmup narrate (p=10, output discarded from timing).
# -------------------------------------------------------------------
echo "--- warmup narrate ($(date -u +%s)) ---"
date -u +%s > "$CASE_OUT/wallclock.warmup_start"
cd "$CLINOSIM_DIR"
clinosim narrate \
    --cif-dir "$WARMUP_CIF" \
    --provider vllm \
    --llm-config "$LLM_CONFIG" \
    --version-id "warmup_case_${CASE_ID}" \
    --concurrency "$CONCURRENCY" \
    --no-set-current \
    2>&1 | tee "$CASE_OUT/narrate_warmup.log"
date -u +%s > "$CASE_OUT/wallclock.warmup_end"

curl -sS "$VLLM_URL/metrics" > "$CASE_OUT/metrics_after_warmup.txt"

# -------------------------------------------------------------------
# 6. Measurement narrate (p=100, this is the throughput window).
# -------------------------------------------------------------------
echo "--- measure narrate ($(date -u +%s)) ---"
date -u +%s > "$CASE_OUT/wallclock.measure_start"
clinosim narrate \
    --cif-dir "$MAIN_CIF" \
    --provider vllm \
    --llm-config "$LLM_CONFIG" \
    --version-id "case_${CASE_ID}" \
    --concurrency "$CONCURRENCY" \
    --no-set-current \
    2>&1 | tee "$CASE_OUT/narrate_measure.log"
date -u +%s > "$CASE_OUT/wallclock.measure_end"

curl -sS "$VLLM_URL/metrics" > "$CASE_OUT/metrics_after.txt"

# -------------------------------------------------------------------
# 7. Copy narrate output to case dir + restore prompt.
# -------------------------------------------------------------------
NARR_DIR="$MAIN_CIF/narrative/case_${CASE_ID}"
if [ -d "$NARR_DIR" ]; then
    cp -r "$NARR_DIR"/* "$CASE_OUT/narrate_output/" 2>/dev/null || true
fi

# Restore the original prompt for the next case (defensive; each case
# runner overwrites it, but leaving prod state broken is bad).
cp "$BACKUP_JA" "$DEPLOYED_JA"

kill $NV_PID 2>/dev/null || true

date -u +%s > "$CASE_OUT/wallclock.end"

echo "=== case $CASE_ID done. output: $CASE_OUT ==="
