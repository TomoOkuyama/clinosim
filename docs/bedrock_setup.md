# EC2 + AWS Bedrock setup for Stage 2

This guide shows how to run clinosim's Stage 2 (clinical document generation)
against **AWS Bedrock** from an EC2 instance.

Why this split?

- Stage 1 (`generate`) is deterministic, CPU-bound, and needs no network access.
  Run it anywhere.
- Stage 2 (`narrate`) is the only stage that calls a paid LLM API. If your
  workstation cannot reach Bedrock (corporate proxy, VPN, sovereignty
  constraints), ship the CIF directory to an EC2 instance and run Stage 2 there.
- Stage 3 (`export-fhir`) is a pure function of the CIF. Run it back on your
  workstation after pulling the narrative version.

```
┌────────────────┐                ┌───────────────────┐
│  local laptop  │                │  EC2 instance     │
│                │                │                   │
│ clinosim       │   scp / s3     │ clinosim          │
│   generate  ───┼───────────────▶│   narrate         │
│                │                │   (Bedrock)       │
│ clinosim       │◀───────────────┤                   │
│   export-fhir  │   scp / s3     │                   │
└────────────────┘                └───────────────────┘
```

---

## Prerequisites

- AWS account with **Bedrock model access approved** in the target region for
  the models you intend to use (see [Request model access](#1-request-bedrock-model-access)).
- An EC2 instance running Linux (Amazon Linux 2023, Ubuntu 22.04, or equivalent).
- Python 3.11+ on the instance.
- (Recommended) The instance attached to an IAM instance role with the
  required Bedrock permissions. Local credentials and AWS profiles are also
  supported if you prefer not to use instance roles.

---

## 1. Request Bedrock model access

1. Sign in to the AWS console in the region you intend to use (e.g. `us-east-1`).
2. Go to **Bedrock → Model access**.
3. Click **Manage model access** and request access for the Anthropic Claude
   models you plan to use, for example:
   - `anthropic.claude-3-5-haiku-20241022-v1:0`
   - `anthropic.claude-3-5-sonnet-20241022-v2:0`
   - `anthropic.claude-3-opus-20240229-v1:0`
4. Wait for approval (usually instant for Claude models, but can take several
   hours).

> **Cross-region inference profiles**
>
> If you plan to use a cross-region inference profile, also request access in
> the region(s) where the profile resolves to. Note the profile ARN (starts
> with `arn:aws:bedrock:...:inference-profile/...`) — you will reference it in
> `inference_profile_arn` below.

---

## 2. Create an IAM role for the EC2 instance

Minimum permissions required by clinosim Stage 2:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ClinosimBedrockConverse",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:Converse",
        "bedrock:ConverseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0",
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-opus-20240229-v1:0"
      ]
    },
    {
      "Sid": "ClinosimBedrockListModels",
      "Effect": "Allow",
      "Action": ["bedrock:ListFoundationModels"],
      "Resource": "*"
    }
  ]
}
```

If you use a cross-region inference profile, add its ARN to the `Resource`
list along with the foundation model ARNs.

1. **IAM → Roles → Create role → AWS service → EC2**
2. Attach a custom policy with the JSON above (save as
   `ClinosimBedrockAccess`).
3. Name the role e.g. `ClinosimBedrockRole`.
4. Attach the role to your EC2 instance (**EC2 → Instances → Actions →
   Security → Modify IAM role**).

---

## 3. Install clinosim on the EC2 instance

### SSH in and bootstrap Python

```bash
# Amazon Linux 2023
sudo dnf -y install python3.11 python3.11-pip git
# Ubuntu
sudo apt-get -y update && sudo apt-get -y install python3.11 python3.11-venv git
```

### Clone and install clinosim with the Bedrock extra

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pip install boto3   # Bedrock provider uses boto3
```

### Verify credentials

```bash
aws sts get-caller-identity       # should show the assumed role
aws bedrock list-foundation-models --region us-east-1 | head
```

---

## 4. Configure the LLM service for Bedrock

clinosim ships with `clinosim/config/llm_service.bedrock.yaml`. Copy it to a
project-local override so you can commit it to your deployment repo:

```bash
cp clinosim/config/llm_service.bedrock.yaml ./llm_service.bedrock.yaml
```

```yaml
# llm_service.bedrock.yaml
judgment:
  mode: "template"
  provider: ""

narrative:
  mode: "llm"
  provider: "bedrock"
  bedrock:
    region: "us-east-1"
    profile: null                 # null → default credential chain (EC2 role)
    model_id: "anthropic.claude-3-5-sonnet-20241022-v2:0"
    # inference_profile_arn: "arn:aws:bedrock:..."
  model_map:
    small: "anthropic.claude-3-5-haiku-20241022-v1:0"
    medium: "anthropic.claude-3-5-sonnet-20241022-v2:0"
    large: "anthropic.claude-3-opus-20240229-v1:0"
  timeout_seconds: 60
  retry_attempts: 3
  retry_backoff_seconds: 2

prompts:
  registry_path: null             # null → default clinosim prompts

cache:
  enabled: true
  directory: "./.llm_cache/bedrock"
  max_entries: 100000
```

Key fields:

- `profile: null` tells `boto3` to use the default credential chain, which
  picks up the EC2 instance role automatically. If you prefer AWS profiles,
  set this to a named profile and ensure `~/.aws/credentials` is present.
- `model_id` is the default model for NARRATIVE tasks. `model_map` maps
  clinosim size tiers (`small` / `medium` / `large`) to specific Bedrock model
  IDs. NARRATIVE currently uses `medium`.
- `cache.directory` should be on the EC2 instance's local disk (or EFS) so
  re-runs can reuse previous responses. If you want the cache to persist
  across instances, point it at a shared EFS mount.

---

## 5. Transfer the CIF from your workstation

```bash
# On your workstation:
clinosim generate -o ./output -p 5000 --country US --format cif
scp -r ./output/cif ec2-user@<ec2-host>:/home/ec2-user/clinosim_cif
```

Or via S3:

```bash
aws s3 sync ./output/cif s3://my-bucket/clinosim_runs/<run_id>/cif/
# On EC2
aws s3 sync s3://my-bucket/clinosim_runs/<run_id>/cif/ /home/ec2-user/clinosim_cif/
```

---

## 6. Run Stage 2 on EC2

```bash
source .venv/bin/activate
clinosim narrate \
    --cif-dir /home/ec2-user/clinosim_cif \
    --llm-config ./llm_service.bedrock.yaml \
    --language en \
    --version-id bedrock_sonnet_en_v1
```

Expected output:

```
clinosim narrate: loading LLM config ./llm_service.bedrock.yaml
  CIF directory: /home/ec2-user/clinosim_cif
  Language:      en
  Mode:          llm
  Tasks:         all Tier A+B

  === Narrative Generation Summary ===
  Version ID:       bedrock_sonnet_en_v1
  Patients:         171
  Total documents:  374
    admission_hp         171
    discharge_summary    171
    operative_note       11
    procedure_note       19
    death_summary        2
  LLM calls:        374
  LLM input tokens: 412,389
  LLM output tokens:58,041
  Fallbacks:        0
  Cache hits:       0
```

### Re-running (cache hits)

Cache is SHA256-keyed on (system prompt + user prompt + model). Re-running
after a successful first run is free:

```bash
clinosim narrate \
    --cif-dir /home/ec2-user/clinosim_cif \
    --llm-config ./llm_service.bedrock.yaml \
    --version-id bedrock_sonnet_en_v2
# → LLM calls: 0, Cache hits: 374
```

### Running a subset of tasks

```bash
# Only the legally mandatory documents (Tier A)
clinosim narrate \
    --cif-dir /home/ec2-user/clinosim_cif \
    --llm-config ./llm_service.bedrock.yaml \
    --tasks discharge_summary,death_summary,operative_note \
    --version-id bedrock_tier_a_only
```

---

## 7. Pull results back and run Stage 3

### Pull narrative CIF back

```bash
# On your workstation
scp -r ec2-user@<ec2-host>:/home/ec2-user/clinosim_cif/narratives/bedrock_sonnet_en_v1 \
    ./output/cif/narratives/
```

Or via S3:

```bash
# On EC2
aws s3 sync /home/ec2-user/clinosim_cif/narratives/ \
    s3://my-bucket/clinosim_runs/<run_id>/narratives/

# On workstation
aws s3 sync s3://my-bucket/clinosim_runs/<run_id>/narratives/ ./output/cif/narratives/
```

### Run Stage 3 locally

```bash
clinosim export-fhir \
    --cif-dir ./output/cif \
    --narrative-version bedrock_sonnet_en_v1 \
    -o ./output/fhir_r4
```

You should now see `DocumentReference.ndjson` in the output directory with one
line per generated document.

---

## Cost estimates

clinosim generates roughly **2.2 Tier A+B documents per inpatient encounter**
(1 admission H&P + 1 discharge summary + ~0.2 other). Token counts per
document depend on the complexity of the encounter, but typical ranges are:

| Document | Input tokens | Output tokens |
|---|---|---|
| Admission H&P | 800–1,200 | 400–600 |
| Discharge Summary | 1,200–1,800 | 600–1,000 |
| Operative Note | 700–1,000 | 300–500 |
| Procedure Note | 500–800 | 200–400 |
| Death Note | 900–1,300 | 400–700 |

For a 5,000-population, 171-inpatient run (374 documents total) using Claude
3.5 Sonnet on Bedrock:

- ~420 K input tokens × $3.00 / 1M = **~$1.26**
- ~58 K output tokens × $15.00 / 1M = **~$0.87**
- **Total: ~$2.15 per 5,000-patient run** (at the time of writing)

Haiku would be roughly 5x cheaper, Opus roughly 5x more expensive. Actual
prices vary — check the current [Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/).

Cache hits are free. A budget of **$10–20 per month** is sufficient for
typical development iteration if you leave the cache enabled and do not
regenerate prompts for every experiment.

---

## Troubleshooting

### `AccessDeniedException: You don't have access to the model with the specified model ID`

- Confirm **Model access** is approved for your region in the Bedrock console.
- Confirm the IAM role on the EC2 instance allows `bedrock:Converse` on the
  specific model ARN. Wildcards like `arn:aws:bedrock:*::foundation-model/*`
  work if your security policy allows them.

### `ModelNotReadyException` or `ThrottlingException`

- These are transient Bedrock-side throttles. clinosim's LLMService retries 3
  times with backoff by default (`retry_attempts: 3`, `retry_backoff_seconds: 2`
  in the YAML config). If retries fail, the service falls back to the template
  for that document and records `fallback_reason` in the narrative CIF so you
  can identify and re-run only the failed documents.

### `NoCredentialsError` from boto3

- If you set `profile: null` but the instance has no IAM role attached,
  boto3's default credential chain will fail. Either attach the role or set
  `profile:` to a named AWS profile with credentials in `~/.aws/credentials`.

### `ImportError: boto3 is required for BedrockProvider`

- Run `pip install boto3` (or `pip install 'clinosim[bedrock]'` once the extra
  is defined in `pyproject.toml`). The Bedrock provider is intentionally
  lazy-imported so hosts that never use Bedrock do not need boto3 installed.

### Cache is not hitting on re-run

- The cache key is `SHA256(system || user || model)`. If you:
  - Bumped the prompt `version:` field
  - Changed `model_map` values
  - Modified any hospital_course fact that affects the rendered user prompt
  ...then the key will differ and the previous cache entries will miss. This
  is intentional: different prompt + different output.
- The cache directory must be writable. Check `ls -la ./.llm_cache/bedrock/`
  after a run.

### Documents generated but `DocumentReference.ndjson` is empty

- Confirm `--narrative-version` matches an existing
  `cif/narratives/<version>/documents/` directory.
- Confirm the narrative CIF contains documents with non-empty `text`. Empty
  stubs are filtered out by Stage 3 (this is intentional — see
  [clinical_documents.md § FHIR mapping](clinical_documents.md#fhir-mapping)).

---

## See also

- [clinical_documents.md](clinical_documents.md) — full clinical document guide
- [README.md § LLM Integration](../README.md#llm-integration-optional) — provider overview
- [../DESIGN.md § 7](../DESIGN.md) — architecture decisions (AD-36 to AD-41)
- [AWS Bedrock documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/)
- [Bedrock Converse API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)
