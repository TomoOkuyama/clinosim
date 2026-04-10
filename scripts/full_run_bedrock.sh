#!/usr/bin/env bash
# ============================================================================
# Full pipeline: CIF → Bedrock Narrative → FHIR Bulk Data
#
# Usage (on EC2 with Bedrock access):
#   ./scripts/full_run_bedrock.sh
#
# Output:
#   output/full_run/cif/            — Structural CIF
#   output/full_run/cif/narratives/ — Narrative CIF (Bedrock)
#   output/full_run/fhir_r4/        — FHIR Bulk Data NDJSON (with DocumentReference)
#   output/full_run/summary.txt     — Run summary
# ============================================================================
set -euo pipefail

OUTPUT="output/full_run"
CIF_DIR="${OUTPUT}/cif"
FHIR_DIR="${OUTPUT}/fhir_r4"
LLM_CONFIG="clinosim/config/llm_service.bedrock.yaml"
VERSION_ID="bedrock_full_en_v1"
SUMMARY="${OUTPUT}/summary.txt"

mkdir -p "${OUTPUT}"

{
echo "============================================================"
echo "  clinosim Full Run (Bedrock)"
echo "  Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"
echo ""

# Stage 1
echo "=== Stage 1: Structural CIF ==="
time python3 -m clinosim.simulator.cli generate \
    -o "${OUTPUT}" \
    -p 5000 \
    --country US \
    --format cif \
    -s 42
echo ""

# Stage 2
echo "=== Stage 2: Bedrock Narrative ==="
time python3 -m clinosim.simulator.cli narrate \
    --cif-dir "${CIF_DIR}" \
    --llm-config "${LLM_CONFIG}" \
    --language en \
    --version-id "${VERSION_ID}"
echo ""

# Stage 3
echo "=== Stage 3: FHIR Bulk Data ==="
time python3 -m clinosim.simulator.cli export-fhir \
    --cif-dir "${CIF_DIR}" \
    --narrative-version "${VERSION_ID}" \
    --country US \
    -o "${FHIR_DIR}"
echo ""

# Summary
echo "============================================================"
echo "  Run Complete"
echo "============================================================"
echo ""
echo "=== FHIR Output ==="
for f in "${FHIR_DIR}"/*.ndjson; do
    name=$(basename "$f")
    lines=$(wc -l < "$f")
    size=$(du -h "$f" | cut -f1)
    printf "  %-40s %7d lines  %s\n" "$name" "$lines" "$size"
done
echo ""
echo "=== Narrative Manifest ==="
python3 -c "
import json
m = json.load(open('${CIF_DIR}/narratives/${VERSION_ID}/manifest.json'))
print(f'  Documents: {m[\"total_documents\"]}')
for t, n in sorted(m['document_counts_by_type'].items()):
    print(f'    {t:20s} {n}')
c = m['llm_cost_report']
print(f'  LLM calls:    {c[\"total_calls\"]}')
print(f'  Cache hits:   {c[\"cache_hit_count\"]}')
print(f'  Fallbacks:    {c[\"fallback_count\"]}')
print(f'  Input tokens: {c[\"total_input_tokens\"]:,}')
print(f'  Output tokens:{c[\"total_output_tokens\"]:,}')
"
echo ""
echo "  Output: ${OUTPUT}/"
echo "============================================================"
} 2>&1 | tee "${SUMMARY}"

echo ""
echo "To push results:"
echo "  git add ${SUMMARY} && git commit -m 'full run summary' && git push"
