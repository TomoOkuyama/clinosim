#!/usr/bin/env bash
# Full US pipeline on EC2: CIF → Narrative → FHIR → compress
# Each step is idempotent — safe to re-run if session drops.
#
# Usage (session-safe):
#   nohup ./scripts/full_run_us.sh > /dev/null 2>&1 &
#   tail -f test_data/bedrock_us_full_results.txt
#
# If interrupted, just re-run the same command. Each step checks
# for completion before starting:
#   Step 1 (CIF): skips if output/us_full/cif/metadata.json exists
#   Step 2 (narrate): PromptCache enables resume from where it left off
#   Step 3 (FHIR): overwrites (fast, ~2min)
#   Step 4 (archive): overwrites (fast)
set -euo pipefail

OUTPUT_DIR="output/us_full"
VERSION_ID="bedrock_en_full"
LLM_CONFIG="clinosim/config/llm_service.bedrock.yaml"
RESULT_FILE="test_data/bedrock_us_full_results.txt"
ARCHIVE="test_data/us_full.tar.gz"

log() {
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"
}

{
echo "============================================================"
echo "  Full US Pipeline (CIF → Narrative → FHIR → Archive)"
log "START PID=$$"
echo "  Config: US, 40K population, 50-bed hospital, seed=42"
echo "============================================================"
echo ""

# Step 1: CIF generation
if [ -f "${OUTPUT_DIR}/cif/metadata.json" ]; then
    log "Step 1/4: CIF already exists — SKIP"
    python3 -c "import json; d=json.load(open('${OUTPUT_DIR}/cif/metadata.json')); print(f'  patients={d[\"total_patients_generated\"]}, country={d[\"country\"]}')"
else
    log "Step 1/4: CIF generation START"
    python3 -m clinosim.simulator.cli generate \
        -o "${OUTPUT_DIR}" \
        -s 42 \
        --country US \
        --format cif
    log "Step 1/4: CIF generation DONE"
fi

# Step 2: English narrative via Bedrock (resumable via PromptCache)
echo ""
log "Step 2/4: Narrative generation START (Bedrock, EN, resumable)"
python3 -m clinosim.simulator.cli narrate \
    --cif-dir "${OUTPUT_DIR}/cif" \
    --llm-config "${LLM_CONFIG}" \
    --language en \
    --version-id "${VERSION_ID}"
log "Step 2/4: Narrative generation DONE"

# Step 3: FHIR R4 Bulk Data export
echo ""
log "Step 3/4: FHIR export START"
python3 -m clinosim.simulator.cli export-fhir \
    --cif-dir "${OUTPUT_DIR}/cif" \
    --country US \
    --narrative-version "${VERSION_ID}" \
    -o "${OUTPUT_DIR}/fhir_r4"
log "Step 3/4: FHIR export DONE"

# Step 4: Archive
echo ""
log "Step 4/4: Archive START"
tar czf "${ARCHIVE}" -C output us_full/
ls -lh "${ARCHIVE}"
log "Step 4/4: Archive DONE"

echo ""
echo "============================================================"
echo "  Generated Documents (1 sample per type)"
echo "============================================================"

python3 -c "
import json, os

docs_root = '${OUTPUT_DIR}/cif/narratives/${VERSION_ID}/documents'
seen = set()
for enc_dir in sorted(os.listdir(docs_root)):
    enc_path = os.path.join(docs_root, enc_dir)
    if not os.path.isdir(enc_path): continue
    for fn in sorted(os.listdir(enc_path)):
        d = json.load(open(os.path.join(enc_path, fn)))
        tt = d['task_type']
        if tt in seen: continue
        seen.add(tt)
        print()
        print('=' * 60)
        print(f'  {tt} (LOINC {d[\"loinc_code\"]})')
        print(f'  source={d[\"text_source\"]} model={d[\"llm_model\"]}')
        print(f'  tokens: in={d[\"llm_input_tokens\"]} out={d[\"llm_output_tokens\"]}')
        print('=' * 60)
        print(d['text'])
    if len(seen) >= 5: break
"

echo ""
echo "=== Narrative Manifest ==="
cat "${OUTPUT_DIR}/cif/narratives/${VERSION_ID}/manifest.json"

echo ""
echo "=== FHIR Export Summary ==="
cat "${OUTPUT_DIR}/fhir_r4/manifest.json"

echo ""
log "ALL DONE"
echo "  Results: ${RESULT_FILE}"
echo "  Archive: ${ARCHIVE}"
echo "  To push: git add -f ${ARCHIVE} ${RESULT_FILE} && git commit -m 'US full run' && git push"
echo "============================================================"
} 2>&1 | tee "${RESULT_FILE}"
