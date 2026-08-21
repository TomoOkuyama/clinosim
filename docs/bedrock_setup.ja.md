# EC2 + AWS Bedrock で Stage 2 を動かす

本ガイドは clinosim の Stage 2 (臨床文書生成) を EC2 インスタンス
から **AWS Bedrock** に対して実行する手順を示します。

なぜこの分割か?

- Stage 1 (`simulate`、旧称 `generate` — deprecated alias として残存)
  は決定的、CPU-bound、ネットワークアクセス不要。どこでも実行可。
- Stage 2 (`narrate`) は有料 LLM API を呼び出す唯一のステージ。
  ワークステーションから Bedrock に到達できない場合 (企業プロキシ、
  VPN、主権制約)、CIF ディレクトリを EC2 インスタンスに転送して
  Stage 2 をそこで実行。
- Stage 3 (`export-fhir`) は CIF の純関数。narrative version を pull
  してワークステーションで実行。

```
┌────────────────┐                ┌───────────────────┐
│  local laptop  │                │  EC2 instance     │
│                │                │                   │
│ clinosim       │   scp / s3     │ clinosim          │
│   simulate  ───┼───────────────▶│   narrate         │
│                │                │   (Bedrock)       │
│ clinosim       │◀───────────────┤                   │
│   export-fhir  │   scp / s3     │                   │
└────────────────┘                └───────────────────┘
```

---

## 前提条件

- 使用予定モデルに対しターゲットリージョンで **Bedrock model access
  approved** な AWS アカウント
  ([Bedrock model access をリクエスト](#1-bedrock-model-access-をリクエスト) 参照)。
- Linux 稼働の EC2 インスタンス (Amazon Linux 2023 / Ubuntu 22.04 /
  同等)。
- インスタンスに Python 3.11+。
- (推奨) 必要な Bedrock 権限を持つ IAM instance role をインスタンスに
  attach。ローカル認証情報と AWS profile もサポート。

---

## 1. Bedrock model access をリクエスト

1. 使用予定リージョン (例: `us-east-1`) で AWS console にサインイン。
2. **Bedrock → Model access** へ。
3. **Manage model access** をクリックし、使用予定の Anthropic Claude
   モデルへのアクセスをリクエスト。例:
   - `anthropic.claude-3-5-haiku-20241022-v1:0`
   - `anthropic.claude-3-5-sonnet-20241022-v2:0`
   - `anthropic.claude-3-opus-20240229-v1:0`
4. 承認を待つ (Claude モデルは通常即時、数時間かかる場合もあり)。

> **Cross-region inference profile**
>
> cross-region inference profile を使用予定の場合、profile が解決する
> リージョンでもアクセスをリクエスト。profile ARN
> (`arn:aws:bedrock:...:inference-profile/...` で開始) をメモ — 後述
> の `inference_profile_arn` で参照。

---

## 2. EC2 インスタンス用 IAM ロールを作成

clinosim Stage 2 が必要とする最小権限:

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

cross-region inference profile を使う場合、foundation model ARN と
ともにその ARN を `Resource` リストに追加。

1. **IAM → Roles → Create role → AWS service → EC2**
2. 上記 JSON でカスタムポリシーを attach (`ClinosimBedrockAccess`
   として保存)。
3. ロール名を例えば `ClinosimBedrockRole`。
4. ロールを EC2 インスタンスに attach (**EC2 → Instances → Actions
   → Security → Modify IAM role**)。

---

## 3. EC2 インスタンスに clinosim をインストール

### SSH ログインと Python bootstrap

```bash
# Amazon Linux 2023
sudo dnf -y install python3.11 python3.11-pip git
# Ubuntu
sudo apt-get -y update && sudo apt-get -y install python3.11 python3.11-venv git
```

### clinosim のクローンとインストール (Bedrock extra 付き)

```bash
git clone https://github.com/TomoOkuyama/clinosim.git
cd clinosim
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pip install boto3   # Bedrock provider は boto3 を使用
```

### 認証情報の確認

```bash
aws sts get-caller-identity       # assumed role が表示されるはず
aws bedrock list-foundation-models --region us-east-1 | head
```

---

## 4. LLM サービスを Bedrock 向けに設定

clinosim は `clinosim/config/llm_service.bedrock.yaml` を同梱。
デプロイ repo にコミットできるようプロジェクトローカル override に
コピー:

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
    profile: null                 # null → デフォルト credential chain (EC2 role)
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

主要フィールド:

- `profile: null` は `boto3` にデフォルト credential chain 使用を
  指示、EC2 instance role を自動 pickup。AWS profile を好むなら
  named profile に設定し `~/.aws/credentials` を用意。
- `model_id` は NARRATIVE タスクのデフォルトモデル。`model_map` は
  clinosim サイズ tier (`small` / `medium` / `large`) を Bedrock
  モデル ID にマップ。NARRATIVE は現状 `medium` を使用。
- `cache.directory` は EC2 のローカルディスク (または EFS) に配置し
  re-run で以前のレスポンスを再利用可能に。インスタンス間で cache を
  永続化したい場合は共有 EFS mount に向ける。

---

## 5. ワークステーションから CIF を転送

```bash
# ワークステーション側:
clinosim simulate -o ./output -p 5000 --country US --format cif
scp -r ./output/cif ec2-user@<ec2-host>:/home/ec2-user/clinosim_cif
```

または S3 経由:

```bash
aws s3 sync ./output/cif s3://my-bucket/clinosim_runs/<run_id>/cif/
# EC2 側
aws s3 sync s3://my-bucket/clinosim_runs/<run_id>/cif/ /home/ec2-user/clinosim_cif/
```

---

## 6. EC2 上で Stage 2 を実行

```bash
source .venv/bin/activate
clinosim narrate \
    --cif-dir /home/ec2-user/clinosim_cif \
    --llm-config ./llm_service.bedrock.yaml \
    --language en \
    --version-id bedrock_sonnet_en_v1
```

期待出力:

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

### 再実行 (cache hit)

Cache は (system prompt + user prompt + model) の SHA256 でキー化。
初回成功後の再実行は無料:

```bash
clinosim narrate \
    --cif-dir /home/ec2-user/clinosim_cif \
    --llm-config ./llm_service.bedrock.yaml \
    --version-id bedrock_sonnet_en_v2
# → LLM calls: 0, Cache hits: 374
```

### タスクサブセットの実行

```bash
# 法的必須文書 (Tier A) のみ
clinosim narrate \
    --cif-dir /home/ec2-user/clinosim_cif \
    --llm-config ./llm_service.bedrock.yaml \
    --tasks discharge_summary,death_summary,operative_note \
    --version-id bedrock_tier_a_only
```

---

## 7. 結果を pull し Stage 3 を実行

### Narrative CIF を pull

```bash
# ワークステーション側
scp -r ec2-user@<ec2-host>:/home/ec2-user/clinosim_cif/narratives/bedrock_sonnet_en_v1 \
    ./output/cif/narratives/
```

または S3 経由:

```bash
# EC2 側
aws s3 sync /home/ec2-user/clinosim_cif/narratives/ \
    s3://my-bucket/clinosim_runs/<run_id>/narratives/

# ワークステーション側
aws s3 sync s3://my-bucket/clinosim_runs/<run_id>/narratives/ ./output/cif/narratives/
```

### ローカルで Stage 3 を実行

```bash
clinosim export-fhir \
    --cif-dir ./output/cif \
    --narrative-version bedrock_sonnet_en_v1 \
    -o ./output/fhir_r4
```

これで出力ディレクトリに `DocumentReference.ndjson` (生成文書ごとに
1 行) が現れるはず。

---

## コスト見積り

clinosim は入院エンカウンター 1 件あたり **約 2.2 Tier A+B 文書** を
シミュレート (入院 H&P 1 + 退院サマリー 1 + ~0.2 その他)。文書あたり
トークン数はエンカウンターの複雑さに依存するが、典型範囲:

| 文書 | 入力 tokens | 出力 tokens |
|---|---|---|
| Admission H&P | 800–1,200 | 400–600 |
| Discharge Summary | 1,200–1,800 | 600–1,000 |
| Operative Note | 700–1,000 | 300–500 |
| Procedure Note | 500–800 | 200–400 |
| Death Note | 900–1,300 | 400–700 |

5,000 population・171 inpatient run (374 文書) に Bedrock 上の Claude
3.5 Sonnet を使用:

- ~420 K 入力 tokens × $3.00 / 1M = **~$1.26**
- ~58 K 出力 tokens × $15.00 / 1M = **~$0.87**
- **合計: 5,000 患者 run あたり ~$2.15** (執筆時点)

Haiku は約 5x 安、Opus は約 5x 高。実際の価格は変動 — 現行
[Bedrock 料金ページ](https://aws.amazon.com/bedrock/pricing/) 参照。

Cache hit は無料。cache を有効化し実験ごとにプロンプトを再生成しな
ければ、**月 $10–20** の予算で通常の開発反復に十分。

---

## トラブルシューティング

### `AccessDeniedException: You don't have access to the model with the specified model ID`

- Bedrock console で対象リージョンの **Model access** が承認済みか
  確認。
- EC2 インスタンスの IAM ロールが specific model ARN に対する
  `bedrock:Converse` を許可しているか確認。セキュリティポリシーが
  許すなら `arn:aws:bedrock:*::foundation-model/*` のワイルドカード
  も可。

### `ModelNotReadyException` または `ThrottlingException`

- 一時的な Bedrock 側 throttle。clinosim の LLMService はデフォルト
  で 3 回リトライ + backoff (`retry_attempts: 3`,
  `retry_backoff_seconds: 2`)。リトライ失敗時はその文書について
  テンプレートにフォールバックし narrative CIF に `fallback_reason`
  を記録するので、失敗文書のみを識別・再実行可能。

### boto3 からの `NoCredentialsError`

- `profile: null` に設定したがインスタンスに IAM ロールが attach
  されていない場合、boto3 のデフォルト credential chain が失敗。
  ロールを attach するか `profile:` を認証情報を持つ named AWS
  profile (`~/.aws/credentials`) に設定。

### `ImportError: boto3 is required for BedrockProvider`

- `pip install boto3` (または `pyproject.toml` で extra が定義され
  次第 `pip install 'clinosim[bedrock]'`) を実行。Bedrock provider
  は意図的に lazy import なので、Bedrock を使わないホストは boto3
  インストール不要。

### 再実行で cache がヒットしない

- Cache キーは `SHA256(system || user || model)`。以下を変更した
  場合キーが変わり過去 cache エントリがミス:
  - プロンプトの `version:` フィールドを bump
  - `model_map` 値を変更
  - レンダリング済 user プロンプトに影響する hospital_course の
    fact を変更
  これは意図的: 異なるプロンプト → 異なる出力。
- Cache ディレクトリは書き込み可能である必要あり。実行後
  `ls -la ./.llm_cache/bedrock/` で確認。

### 文書は生成されたが `DocumentReference.ndjson` が空

- `--narrative-version` が既存の
  `cif/narratives/<version>/documents/` ディレクトリと一致するか確認。
- narrative CIF が空でない `text` を持つ文書を含むか確認。空の
  stub は Stage 3 でフィルタされる (意図的 —
  [clinical_documents.md § FHIR mapping](clinical_documents.ja.md#fhir-mapping)
  参照)。

---

## 関連

- [clinical_documents.ja.md](clinical_documents.ja.md) — 臨床文書
  ガイド全体
- [README.md § LLM Integration](../README.md#llm-integration-optional) —
  プロバイダ概要
- [../DESIGN.md § 7](../DESIGN.md) — アーキテクチャ判断 (AD-36〜AD-41)
- [AWS Bedrock ドキュメント](https://docs.aws.amazon.com/bedrock/latest/userguide/)
- [Bedrock Converse API リファレンス](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)
