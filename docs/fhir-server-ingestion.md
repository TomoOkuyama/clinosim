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
AllergyIntolerance.ndjson    DocumentReference.ndjson     Observation.ndjson
CareTeam.ndjson              Encounter.ndjson             Organization.ndjson
ClinicalImpression.ndjson    Endpoint.ndjson              Patient.ndjson
Composition.ndjson           FamilyMemberHistory.ndjson   Practitioner.ndjson
Condition.ndjson             ImagingStudy.ndjson          PractitionerRole.ndjson
Coverage.ndjson              Immunization.ndjson          Procedure.ndjson
Device.ndjson                Location.ndjson              ServiceRequest.ndjson
DeviceUseStatement.ndjson    MedicationAdministration.ndjson  Specimen.ndjson
DiagnosticReport.ndjson      MedicationRequest.ndjson
manifest.json
```

The exact file set depends on which modules fire for the cohort —
`DeviceUseStatement.ndjson` (and the per-patient `Device` rows) emit
only when an inpatient transferred to the ICU received a CVC,
indwelling catheter or mechanical ventilator (`Device.ndjson` always
carries the shared facility infusion pump), and
`Specimen.ndjson` only when microbiology-cultures encounter chain
fires.

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
    -e hapi.fhir.enforce_referential_integrity_on_write=false \
    hapiproject/hapi:latest
```

`enforce_referential_integrity_on_write=false` lets the server accept a
reference to a resource that has not been loaded yet. clinosim output
needs this because some references point forward no matter which order
you load in (see [Why load order alone is not enough](#why-load-order-alone-is-not-enough)).

Wait until the health probe reports the server is up:

```bash
until curl -sf http://localhost:8080/fhir/metadata > /dev/null; do sleep 2; done
echo "HAPI FHIR ready at http://localhost:8080/fhir"
```

### 2. Push the NDJSON files

clinosim's resources reference each other by their own ids
(`Encounter/enc-…`, `Patient/pt-…`). Load every resource with
`PUT [base]/[type]/[id]` so the server stores it under that same id.
Do **not** `POST` to `[base]/[type]`: a create assigns a new
server-side id, and every reference to the original id stops
resolving.

A `PUT` to an id that does not exist yet creates the resource
("update as create"). The server must allow client-assigned ids;
HAPI FHIR does by default for ids that are not purely numeric, which
covers all clinosim ids. The `id` inside each NDJSON line already
matches the URL, as FHIR requires for `PUT`.

**Small cohort — one `PUT` per resource (works on any FHIR R4 server
that supports update-as-create):**

```bash
BASE=http://localhost:8080/fhir
SRC=jp-100/fhir_r4

# Every resource type clinosim can emit, in an order where most
# references point at resources already loaded. Types that a cohort did
# not produce are skipped.
for rt in Organization Endpoint Practitioner Location PractitionerRole \
          Patient Coverage Device Encounter Condition AllergyIntolerance \
          FamilyMemberHistory Immunization ServiceRequest Specimen Observation \
          ImagingStudy DiagnosticReport MedicationRequest MedicationAdministration \
          Procedure DeviceUseStatement ClinicalImpression CareTeam \
          DocumentReference Composition
do
    [ -f "${SRC}/${rt}.ndjson" ] || continue
    echo "== Loading ${rt} =="
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        id=$(printf '%s' "$line" | jq -r '.id')
        printf '%s' "$line" | curl -sSf -X PUT \
            -H 'Content-Type: application/fhir+json' \
            --data-binary @- \
            "${BASE}/${rt}/${id}" > /dev/null
    done < "${SRC}/${rt}.ndjson"
done
```

The list above covers all 26 resource types the FHIR writer can emit.
To check that a cohort contains nothing the loop would skip, compare it
with `manifest.json`:

```bash
jq -r '.output[].type' "${SRC}/manifest.json" | sort
```

**Medium cohort — transaction Bundles of `PUT` entries:** one HTTP
round trip per chunk instead of per resource. Each entry carries
`request.method = PUT` and `request.url = [type]/[id]`, so ids are kept
exactly as with the loop above.

```bash
for rt in Organization Endpoint Practitioner Location PractitionerRole \
          Patient Coverage Device Encounter Condition AllergyIntolerance \
          FamilyMemberHistory Immunization ServiceRequest Specimen Observation \
          ImagingStudy DiagnosticReport MedicationRequest MedicationAdministration \
          Procedure DeviceUseStatement ClinicalImpression CareTeam \
          DocumentReference Composition
do
    [ -f "${SRC}/${rt}.ndjson" ] || continue
    echo "== Loading ${rt} =="
    # 500 resources per transaction
    jq -c -n --arg rt "$rt" '
        def chunks(n): [inputs] | range(0; length; n) as $i | .[$i:$i+n];
        chunks(500)
        | {resourceType: "Bundle", type: "transaction",
           entry: [ .[] | {resource: .,
                           request: {method: "PUT", url: "\($rt)/\(.id)"}} ]}
    ' "${SRC}/${rt}.ndjson" |
    while IFS= read -r bundle; do
        printf '%s' "$bundle" | curl -sSf -X POST \
            -H 'Content-Type: application/fhir+json' \
            --data-binary @- \
            "${BASE}" > /dev/null
    done
done
```

A transaction is posted to the server base (`POST [base]`); that is the
standard way to submit a Bundle and does not create new ids for the
`PUT` entries inside it.

#### Why load order alone is not enough

The order above loads most reference targets first, but clinosim output
always contains references that point forward:

- `Encounter.diagnosis.condition` and `Encounter.reasonReference`
  point at `Condition`, while `Condition.encounter` points back at
  `Encounter` — no order satisfies both.
- Within a single file, `Location.partOf`, `Organization.partOf` and
  `DocumentReference.relatesTo.target` can point at a row that appears
  later in the same file.

So the server must accept references to resources that are not there
yet. On HAPI FHIR that is
`hapi.fhir.enforce_referential_integrity_on_write=false` (set in the
`docker run` above); on other servers, turn off the equivalent
on-write reference check for the duration of the load. Once every file
is loaded, all references resolve.

**Larger cohort — `$import`:**

Bulk Data `$import` reads the NDJSON files directly and keeps the `id`
in each line, so references resolve the same way as with `PUT`. List
one `input` per file; the example below shows two of them — generate the
full list from `manifest.json` (for example
`jq '[.output[] | {name: "input", part: [{name: "type", valueCode: .type}, {name: "url", valueUri: ("http://host.docker.internal:9000/" + .url)}]}]' jp-100/fhir_r4/manifest.json`).

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

If your server does not implement `$import`, the `PUT` approaches from
Option A (one request per resource, or transaction Bundles of `PUT`
entries) work on any server that supports update-as-create, at the cost
of higher wire overhead.

## Troubleshooting

### Reference integrity errors

Symptom: `Invalid reference: Patient/… — no such resource`, or (HAPI
FHIR) `HAPI-1094: Resource Condition/… not found, specified in path:
Encounter.reasonReference` while loading `Encounter`.

Cause: the server checks references on write, and the resource being
loaded points at one that has not been loaded yet. Some of these
forward references are unavoidable (see
[Why load order alone is not enough](#why-load-order-alone-is-not-enough)).

Fix: disable the on-write reference check for the load
(`hapi.fhir.enforce_referential_integrity_on_write=false` on HAPI
FHIR), load in the order shown in the loop above, then re-enable the
check if you want it for later writes.

### References that point at missing ids

Symptom: the load succeeds, but searches such as
`Encounter?subject=Patient/pt-…` return nothing, or references show up
as unresolved.

Cause: the resources were created with `POST [base]/[type]`, so the
server assigned new ids and the clinosim ids in references no longer
match anything.

Fix: delete the loaded data and load again with
`PUT [base]/[type]/[id]` (or transaction Bundles of `PUT` entries) as
shown above.

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
