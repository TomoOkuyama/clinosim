# Loading clinosim output into a FHIR server

clinosim emits [HL7 FHIR R4 Bulk Data Access](https://hl7.org/fhir/uv/bulkdata/)
NDJSON — one file per `resourceType`. That format is designed to be
ingested by a FHIR server via the [`$import`](https://hl7.org/fhir/uv/bulkdata/OperationDefinition-import.html)
operation. This page walks through loading `datasets/jp-100` into a
generic FHIR server (HAPI FHIR is used as the concrete example; other
FHIR-R4-conformant servers work the same way).

!!! note "Vendor neutrality"
    This guide does **not** depend on any commercial FHIR server. HAPI
    FHIR is used as a concrete OSS example because it's the most widely
    deployed HAPI-based JPA server. Any FHIR R4 Bulk Data-conformant
    server should accept the same input.

## Pre-requisites

- A clinosim output directory produced by `clinosim simulate --format fhir`
  or `clinosim dataset build <preset>`, e.g. `./jp-100/`.
- Docker (for the local HAPI FHIR example) or an existing FHIR R4 server
  with the Bulk Data `$import` operation enabled.
- `curl` or an HTTP client.

## Verify the output shape

```bash
$ ls jp-100/fhir_r4/
AllergyIntolerance.ndjson    Encounter.ndjson             Location.ndjson
CareTeam.ndjson              Endpoint.ndjson              MedicationAdministration.ndjson
ClinicalImpression.ndjson    FamilyMemberHistory.ndjson   MedicationRequest.ndjson
Composition.ndjson           ImagingStudy.ndjson          Observation.ndjson
Condition.ndjson             Immunization.ndjson          Organization.ndjson
Coverage.ndjson              Patient.ndjson               PractitionerRole.ndjson
DiagnosticReport.ndjson      Practitioner.ndjson          Procedure.ndjson
DocumentReference.ndjson                                  ServiceRequest.ndjson
manifest.json
```

Each `.ndjson` is one FHIR resource per line. `manifest.json` is the
Bulk Data descriptor pointing at those files.

## Option A — Local HAPI FHIR (Docker)

### 1. Start the server

```bash
docker run -d --name hapi-fhir \
    -p 8080:8080 \
    -e hapi.fhir.default_encoding=json \
    -e hapi.fhir.bulk_export_enabled=true \
    -e hapi.fhir.bulk_import_enabled=true \
    -e hapi.fhir.fhir_version=R4 \
    hapiproject/hapi:latest
```

Wait until the health probe reports the server is up:

```bash
until curl -sf http://localhost:8080/fhir/metadata > /dev/null; do sleep 2; done
echo "HAPI FHIR ready at http://localhost:8080/fhir"
```

### 2. Push the NDJSON files

The simplest approach for small cohorts is to POST each resource as a
bundle. For larger cohorts, use the `$import` operation.

**Small cohort — per-file POST (works everywhere):**

```bash
BASE=http://localhost:8080/fhir

# Order matters: reference targets must exist before the referrers.
# Patient / Organization / Location first; then Encounter; then
# everything referring to Encounter (Condition, Observation,
# MedicationRequest, ...). CareTeam / Composition / DocumentReference /
# ClinicalImpression come last because they reference several types.
for rt in Organization Location Practitioner PractitionerRole Patient Coverage \
          Encounter Condition AllergyIntolerance Immunization FamilyMemberHistory \
          MedicationRequest MedicationAdministration Observation DiagnosticReport \
          Procedure ImagingStudy Endpoint ServiceRequest ClinicalImpression \
          Composition CareTeam DocumentReference
do
    if [ -f "jp-100/fhir_r4/${rt}.ndjson" ]; then
        echo "== Loading ${rt} =="
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            curl -sSf -X POST \
                -H 'Content-Type: application/fhir+json' \
                --data-raw "$line" \
                "${BASE}/${rt}" > /dev/null
        done < "jp-100/fhir_r4/${rt}.ndjson"
    fi
done
```

**Larger cohort — `$import`:**

```bash
# 1. Serve the NDJSON files over HTTP so the FHIR server can fetch them.
#    (In production, use an object store like S3 with pre-signed URLs.)
python3 -m http.server 9000 --directory jp-100/fhir_r4 &

# 2. Kick off the import.
curl -sSf -X POST \
    -H 'Content-Type: application/fhir+json' \
    -H 'Prefer: respond-async' \
    -H 'X-Provenance: {"resourceType":"Provenance","recorded":"2026-07-12T00:00:00Z","reason":[{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/v3-ActReason","code":"HRESCH"}]}],"agent":[{"who":{"identifier":{"value":"clinosim-dataset-loader"}}}]}' \
    "http://localhost:8080/fhir/\$import" \
    --data '{
      "resourceType": "Parameters",
      "parameter": [
        {"name": "inputFormat", "valueCode": "application/fhir+ndjson"},
        {"name": "inputSource", "valueUri": "http://host.docker.internal:9000/"},
        {"name": "storageDetail", "part": [
          {"name": "type", "valueCode": "https"}
        ]},
        {"name": "input", "part": [
          {"name": "type", "valueCode": "Patient"},
          {"name": "url", "valueUri": "http://host.docker.internal:9000/Patient.ndjson"}
        ]},
        {"name": "input", "part": [
          {"name": "type", "valueCode": "Encounter"},
          {"name": "url", "valueUri": "http://host.docker.internal:9000/Encounter.ndjson"}
        ]}
      ]
    }'
```

The response `Content-Location` header points at a status endpoint you
poll until the import completes:

```bash
STATUS_URL=$(curl -sSD - -X POST "..." | grep -i '^content-location:' | awk '{print $2}' | tr -d '\r')
while true; do
    curl -sSI "$STATUS_URL"    # 202 = in progress, 200 = complete, 4xx/5xx = failed
    sleep 5
done
```

### 3. Verify

```bash
BASE=http://localhost:8080/fhir

# Count Patients — should match your preset population.
curl -s "${BASE}/Patient?_summary=count" | jq '.total'

# Pull a physiologically-derived PT-INR observation.
curl -s "${BASE}/Observation?category=laboratory&code=6301-6&_count=1" \
    | jq '.entry[0].resource | {id, valueQuantity, interpretation}'

# Confirm JP Core profile declarations survived the round trip.
curl -s "${BASE}/Patient?_count=1" \
    | jq '.entry[0].resource.meta.profile'
```

## Option B — Other FHIR R4 servers

Any server that supports the FHIR R4 Bulk Data Access
[`$import`](https://hl7.org/fhir/uv/bulkdata/OperationDefinition-import.html)
operation accepts the same NDJSON payload. Examples include:

- **HAPI FHIR** (the OSS reference, walked through above).
- **Microsoft FHIR Server** (Azure API for FHIR).
- **Google Cloud Healthcare API FHIR store**.
- **InterSystems IRIS for Health FHIR Server** — supports `$import`;
  see the vendor documentation. This is listed here as an example of a
  conformant server, not as a required dependency.

If your server does not implement `$import`, the per-file POST approach
from Option A works everywhere at the cost of higher wire overhead.

## Troubleshooting

### Reference integrity errors

Symptom: `Invalid reference: Patient/… — no such resource`.

Cause: `Encounter` was loaded before the `Patient` it references, or the
NDJSON files were ingested in filesystem order rather than dependency
order.

Fix: load in the order shown in the loop above (`Organization` and
`Patient` first, then `Encounter`, then everything referring to
`Encounter`). For `$import`, list the `Parameters.parameter[].part[]`
entries in the same order — HAPI's importer respects the order.

### JP Core profile validation failures

Symptom: `MalformedResourceException: does not conform to profile
http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient`.

Cause: the target server does not have JP Core StructureDefinition
resources loaded, so validation fails on any resource that declares a
JP Core profile in `meta.profile`.

Fix: either

- disable strict profile validation on the ingesting server (fastest
  for smoke testing);
- or preload the JP Core profile pack from
  <https://jpfhir.jp/fhir/core/> into the server's terminology store.

### Import job stalls

Symptom: the poll on the status URL keeps returning `202 Accepted`
without progress.

Cause: the FHIR server can't reach the URLs in `input[].url` — usually
because Docker's `host.docker.internal` isn't reachable from inside the
container on Linux (works out of the box on macOS / Windows).

Fix: on Linux, add `--add-host=host.docker.internal:host-gateway` to the
`docker run` command that starts HAPI, then re-run the import.

### Determinism check after ingestion

If you want to verify that the ingested cohort matches the source
tarball byte-for-byte (round-trip), export it back out and diff:

```bash
curl -sSf "${BASE}/Patient?_count=99999&_format=ndjson" > exported/Patient.ndjson
# (repeat per resourceType, then compare sha256sum with the original)
```

The order of rows in the exported NDJSON is server-dependent, so sort
before diffing:

```bash
sort exported/Patient.ndjson > exported/Patient.sorted.ndjson
sort jp-100/fhir_r4/Patient.ndjson > original/Patient.sorted.ndjson
diff original/Patient.sorted.ndjson exported/Patient.sorted.ndjson
```

## See also

- [FHIR R4 Bulk Data Access spec](https://hl7.org/fhir/uv/bulkdata/)
- [HAPI FHIR docs](https://hapifhir.io/hapi-fhir/docs/)
- [jpfhir.jp — JP Core FHIR profile](https://jpfhir.jp/fhir/core/)
- clinosim [Reproducibility](development/reproducibility.md) — verify
  the source cohort byte-identity before you ingest anything.
- clinosim [Evaluation](eval.md) — score the source cohort with
  `clinosim eval` before ingesting so any determinism / clinical /
  locale finding is investigated up front, not blamed on the server.
