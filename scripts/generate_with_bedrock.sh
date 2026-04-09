#!/usr/bin/env bash
# ============================================================================
# generate_with_bedrock.sh — Full pipeline: CIF → Narrative (Bedrock) → FHIR
#
# Run this on any machine with:
#   - Python 3.11+
#   - boto3 installed
#   - AWS credentials with bedrock:Converse permission
#     (IAM role, env vars, or ~/.aws/credentials)
#
# Usage:
#   ./scripts/generate_with_bedrock.sh                    # defaults
#   ./scripts/generate_with_bedrock.sh -p 10000 -c JP     # 10k pop, Japanese
#   BEDROCK_MODEL=anthropic.claude-3-opus-20240229-v1:0 \
#     ./scripts/generate_with_bedrock.sh                  # use Opus
#
# Environment variables:
#   POPULATION     Catchment population (default: 5000)
#   COUNTRY        US or JP (default: US)
#   SEED           Random seed (default: 42)
#   LANGUAGE       Document language: en or ja (default: en)
#   OUTPUT_DIR     Output directory (default: ./output/bedrock_run)
#   AWS_REGION     Bedrock region (default: us-east-1)
#   AWS_PROFILE    AWS profile name (default: unset → default chain)
#   BEDROCK_MODEL  Bedrock model ID (default: from llm_service.bedrock.yaml)
#   SKIP_GENERATE  Set to 1 to skip Stage 1 (use existing CIF)
#   CIF_DIR        Path to existing CIF (used when SKIP_GENERATE=1)
# ============================================================================
set -euo pipefail

# ---- Configuration ----
POPULATION="${POPULATION:-5000}"
COUNTRY="${COUNTRY:-US}"
SEED="${SEED:-42}"
LANGUAGE="${LANGUAGE:-en}"
OUTPUT_DIR="${OUTPUT_DIR:-./output/bedrock_run}"
AWS_REGION="${AWS_REGION:-us-east-1}"
SKIP_GENERATE="${SKIP_GENERATE:-0}"
CIF_DIR="${CIF_DIR:-${OUTPUT_DIR}/cif}"

# Parse CLI args (override env vars)
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--population) POPULATION="$2"; shift 2 ;;
        -c|--country) COUNTRY="$2"; shift 2 ;;
        -s|--seed) SEED="$2"; shift 2 ;;
        -l|--language) LANGUAGE="$2"; shift 2 ;;
        -o|--output) OUTPUT_DIR="$2"; CIF_DIR="${2}/cif"; shift 2 ;;
        --skip-generate) SKIP_GENERATE=1; shift ;;
        --cif-dir) CIF_DIR="$2"; SKIP_GENERATE=1; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

VERSION_ID="bedrock_${LANGUAGE}_$(date +%Y%m%d_%H%M%S)"
LLM_CONFIG="clinosim/config/llm_service.bedrock.yaml"

echo "============================================================"
echo "  clinosim Bedrock Pipeline"
echo "============================================================"
echo "  Population:    ${POPULATION}"
echo "  Country:       ${COUNTRY}"
echo "  Language:      ${LANGUAGE}"
echo "  Seed:          ${SEED}"
echo "  Output:        ${OUTPUT_DIR}"
echo "  CIF dir:       ${CIF_DIR}"
echo "  Version ID:    ${VERSION_ID}"
echo "  AWS Region:    ${AWS_REGION}"
echo "  LLM Config:    ${LLM_CONFIG}"
echo "  Skip generate: ${SKIP_GENERATE}"
echo "============================================================"

# ---- Pre-flight checks ----
echo ""
echo "=== Pre-flight checks ==="

# Python
python3 --version || { echo "ERROR: Python 3 not found"; exit 1; }

# boto3
python3 -c "import boto3; print(f'boto3 {boto3.__version__}')" || {
    echo "ERROR: boto3 not installed. Run: pip install boto3"
    exit 1
}

# AWS credentials
python3 -c "
import boto3
session = boto3.Session(region_name='${AWS_REGION}')
sts = session.client('sts')
identity = sts.get_caller_identity()
print(f'AWS Account: {identity[\"Account\"]}')
print(f'AWS ARN:     {identity[\"Arn\"]}')
" || {
    echo "ERROR: AWS credentials not configured."
    echo "Set up via: aws configure, IAM role, or env vars."
    exit 1
}

# Bedrock model access
python3 -c "
import boto3
client = boto3.Session(region_name='${AWS_REGION}').client('bedrock-runtime')
print('Bedrock runtime client: OK')
" || {
    echo "ERROR: Cannot create Bedrock runtime client."
    exit 1
}

# clinosim
python3 -c "import clinosim; print('clinosim: OK')" || {
    echo "ERROR: clinosim not installed. Run: pip install -e '.[dev]'"
    exit 1
}

echo ""
echo "All pre-flight checks passed."
echo ""

# ---- Stage 1: Generate structural CIF ----
if [ "${SKIP_GENERATE}" = "0" ]; then
    echo "=== Stage 1: Generating structural CIF ==="
    python3 -m clinosim.simulator.cli generate \
        -o "${OUTPUT_DIR}" \
        -p "${POPULATION}" \
        -s "${SEED}" \
        --country "${COUNTRY}" \
        --format cif
    echo ""
else
    echo "=== Stage 1: SKIPPED (using existing CIF at ${CIF_DIR}) ==="
    if [ ! -d "${CIF_DIR}/structural/patients" ]; then
        echo "ERROR: ${CIF_DIR}/structural/patients not found"
        exit 1
    fi
    echo ""
fi

# ---- Stage 2: Generate narrative documents with Bedrock ----
echo "=== Stage 2: Generating narrative documents (Bedrock) ==="
export AWS_DEFAULT_REGION="${AWS_REGION}"

python3 -m clinosim.simulator.cli narrate \
    --cif-dir "${CIF_DIR}" \
    --llm-config "${LLM_CONFIG}" \
    --language "${LANGUAGE}" \
    --version-id "${VERSION_ID}"

echo ""

# ---- Stage 3: Export FHIR Bulk Data ----
echo "=== Stage 3: Exporting FHIR R4 Bulk Data ==="
FHIR_DIR="${OUTPUT_DIR}/fhir_r4"

python3 -m clinosim.simulator.cli export-fhir \
    --cif-dir "${CIF_DIR}" \
    --narrative-version "${VERSION_ID}" \
    --country "${COUNTRY}" \
    -o "${FHIR_DIR}"

echo ""
echo "============================================================"
echo "  Pipeline complete!"
echo "============================================================"
echo "  CIF:             ${CIF_DIR}"
echo "  Narratives:      ${CIF_DIR}/narratives/${VERSION_ID}/"
echo "  FHIR Bulk Data:  ${FHIR_DIR}/"
echo ""
echo "  DocumentReference count:"
if [ -f "${FHIR_DIR}/DocumentReference.ndjson" ]; then
    wc -l < "${FHIR_DIR}/DocumentReference.ndjson"
else
    echo "  (none generated)"
fi
echo ""
echo "  To inspect a sample:"
echo "    head -1 ${FHIR_DIR}/DocumentReference.ndjson | python3 -m json.tool"
echo ""
echo "  To copy FHIR output to another location:"
echo "    cp -R ${FHIR_DIR} /path/to/destination/"
echo "============================================================"
