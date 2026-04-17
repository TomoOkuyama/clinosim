#!/usr/bin/env bash
# Full US pipeline on EC2: CIF → Narrative → FHIR → compress
#
# Usage (session-safe):
#   nohup ./scripts/full_run_us.sh > /dev/null 2>&1 &
#   tail -f test_data/bedrock_us_full_results.txt
set -euo pipefail

OUTPUT_DIR="output/us_full"
VERSION_ID="bedrock_en_full"
LLM_CONFIG="clinosim/config/llm_service.bedrock.yaml"
RESULT_FILE="test_data/bedrock_us_full_results.txt"
ARCHIVE="test_data/us_full.tar.gz"

{
echo "============================================================"
echo "  Full US Pipeline (CIF → Narrative → FHIR → Archive)"
echo "  Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "  PID: $$"
echo "============================================================"
echo ""

# Step 1: CIF generation (US, 40K population, seed=42, snapshot=today)
echo ">>> Step 1: CIF generation"
python3 -m clinosim.simulator.cli generate \
    -o "${OUTPUT_DIR}" \
    -s 42 \
    --country US \
    --format cif

# Step 2: English narrative via Bedrock
echo ""
echo ">>> Step 2: English narrative generation (Bedrock)"
python3 -m clinosim.simulator.cli narrate \
    --cif-dir "${OUTPUT_DIR}/cif" \
    --llm-config "${LLM_CONFIG}" \
    --language en \
    --version-id "${VERSION_ID}"

# Step 3: FHIR R4 Bulk Data export (with DocumentReference)
echo ""
echo ">>> Step 3: FHIR R4 Bulk Data export"
python3 -m clinosim.simulator.cli export-fhir \
    --cif-dir "${OUTPUT_DIR}/cif" \
    --country US \
    --narrative-version "${VERSION_ID}" \
    -o "${OUTPUT_DIR}/fhir_r4"

# Step 4: Archive (CIF + narratives + FHIR)
echo ""
echo ">>> Step 4: Archiving"
tar czf "${ARCHIVE}" -C output us_full/
ls -lh "${ARCHIVE}"

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
echo "============================================================"
echo "  DONE: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "  Results: ${RESULT_FILE}"
echo "  Archive: ${ARCHIVE}"
echo "  To push: git add -f ${ARCHIVE} ${RESULT_FILE} && git commit -m 'US full run' && git push"
echo "============================================================"
} 2>&1 | tee "${RESULT_FILE}"
