# clinosim 設計ガイドライン

## 1. 大原則: Realism Above All (リアリズム最優先)

**clinosim の最高優先度はリアリズム**。あらゆる設計判断、あらゆる
パラメータ選択、あらゆるモジュール挙動は、唯一の問いに対して評価
される: _「これは本物の病院で起こるか?」_

### clinosim におけるリアリズムの意味

リアリズムは単一の軸ではない。3 次元にわたり、全てが同時に満たさ
れる必要がある:

| 次元 | 問い | 例 |
|---|---|---|
| **生物学的リアリズム** | これは生理学的・病理学的に妥当か? | CRP は感染発症 2 時間後に 200 mg/L に上昇しない。Cr は透析なしで一晩に 3 mg/dL 下がらない。 |
| **行動リアリズム** | 実際の臨床医、看護師、患者がこう振る舞うか? | 医師は安定した肺炎患者に午前 3 時に CT オーダーしない。35 歳が外傷なく大腿骨骨折を呈さない。日本人患者は肺炎で 14 日入院しうるが、米国人患者は 5 日で退院する。 |
| **システムリアリズム** | この医療システムと施設内でこれが起こりうるか? | 小規模コミュニティ病院は心臓カテーテル検査を行わない。夜勤の検査結果は時間がかかる。週末の consultant availability は限定的。 |

### 全モジュールに対するリアリズム原則

1. **実世界の分布、一様乱数ではない。** 年齢、性別、血液型、併存
   疾患 prevalence、疾患 incidence — 全て恣意的な range ではなく
   公表された疫学分布に従う。パラメータ生成時、実データソースま
   たは公表統計に追跡可能でなければならない。

2. **相関、独立ではない。** 現実では患者属性は相関している: 年齢
   と併存疾患、性別と疾患 incidence、社会経済的地位と健康リテラ
   シー、血液型分布と民族。生成データはこれらの相関を保持する。

3. **時間的整合性。** イベントは臨床的に意味のある順序で、現実的
   な時間差で起こる。検査結果は検体採取後に到着。抗生物質は培養
   採取後 (前ではなく) に開始。CRP は感染から 48 時間後にピーク、
   同時ではない。

4. **施設コンテキスト。** 同じ臨床シナリオは異なる設定で異なる
   データを produce する。大学病院はコミュニティクリニックとは
   異なるスタッフ配置、機器、文書化パターンを持つ。日本と米国は
   在院日数、検査オーダー頻度、退院基準、文書スタイルが異なる。

5. **不完全さこそリアル。** 実データは欠損値、測定エラー、遅延
   結果、誤診、workaround を持つ。完全にクリーンなデータそれ自体
   が非現実的。不完全さは context 依存で説明可能でなければならず、
   決してランダムノイズであってはならない。

6. **現実に対して検証。** 各モジュールは定量的なリアリズム
   ベンチマーク (公表統計、臨床ガイドライン、疫学データ) を定義
   し、それに対して生成出力を検証可能でなければならない。実世界
   参照を引用できないパラメータは疑わしい。

### この原則がどう設計判断を統治するか

設計選択に直面したとき:
- 「X を簡略化すべきか?」 → ドメイン専門家が偽物と認識するデータ
  を produce しない場合のみ。
- 「どれくらいの詳細が必要か?」 → 生成データが臨床医の sniff test
  に合格するのに十分。それ以上でもそれ以下でもない。
- 「Y をモデル化すべきか?」 → Y を省略するとリアリズムに顕著な
  ギャップ (例: 看護記録の欠落、検査所要時間に週末効果なし) が
  生まれるなら、モデル化する。

### 検証: リアリズムを仮定するのではなく証明する

リアリズムは主観的な主張ではない — **測定** されなければならない。
clinosim は 3 層検証フレームワークを使用する:

**Tier 1: 統計的検証 (自動化)**
生成データ分布を公表実世界統計と比較。各シミュレーション後に
自動実行、乖離をフラグ。

**Tier 2: 臨床パターン検証 (自動化 + 専門家レビュー)**
時系列パターン、臨床シーケンス、変数間相関が既知の臨床挙動と
一致することを検証。自動テストが構造を check、専門家レビュアが
臨床的妥当性を check。

**Tier 3: ドメイン専門家盲検テスト**
生成レコードを実 (匿名化された) レコードと並べて臨床医に提示。
生成と実を確実に区別できなければ、リアリズム目標は満たされている。

完全な検証フレームワークは `modules/validator/SPEC.md` 参照。

---

## 2. モジュラーアーキテクチャ原則

### なぜモジュール化するか

- **コンテキスト局所性**: 各モジュールは全体を把握する必要なく
  独立に設計・変更可能
- **並列開発**: モジュール間 interface が定義されれば、モジュール
  は独立に実装可能
- **漸進的設計**: open question はモジュール単位で管理; 決定は
  下されたら lock-in

### モジュール境界の基準

1. 各 **パイプライン段階** が 1 モジュールにマップ
2. 全モジュールは **明確に定義された入力と出力** を持つ
3. 内部実装詳細はモジュール境界を越えて漏れない
4. **データ駆動設定** (疾患定義、医療システムルール) は専用
   モジュールに存在

---

## 2. LLM 統合アーキテクチャ

### なぜ LLM

ルールベースシミュレーションは構造的に正しいデータを produce
するが、実臨床文書の nuance を欠く。実臨床レコードは以下を含む:
- 異なるスタイルで異なる医師が書いた自然言語ノート
- 確率更新だけでなく散文で表現された診断推論
- ルールシステムが捕捉できない context を考慮した臨床判断
- 患者自身の言葉での症状申告
- 実世界の実践を反映する微妙な不整合と workaround

LLM は「構造的に有効」と「臨床的に実物と区別不能」の間のギャップ
を埋める。

### 設計原則: 選択的増幅

LLM は **選択的増幅器** として使用される — 自然言語生成や
コンテキスト推論から最も恩恵を受ける specific 出力を強化する一方、
全数値・構造データはルールベースのまま。

```
ルールベースエンジン (高速、決定的、安価)
  │
  │  構造データを produce: 検査値、vital、タイムスタンプ、コード、状態変数
  │
  ↓
LLM 層 (選択的、コンテキスト、高価)
  │
  │  強化: 臨床ノート、推論 narrative、症状記述、曖昧な決定点での
  │        臨床判断、生成レコードの一貫性レビュー
  │
  ↓
最終出力: 臨床的に整合的な構造データ + 自然言語
```

### 責任分割: モジュール vs llm_service

```
モジュールの仕事:                       llm_service の仕事:
  「これが起こった」        →           「これをどう記述するか」
  (構造化 ClinicalEventData)             (プロンプト構築、モデル選択、
                                          レスポンス解析、cache、コスト追跡)
```

モジュールは決してプロンプトテキストを書かず、モデル tier を
選ばず、出力 token 制限を設定しない。それら全ては
`llm_service/prompts/*.yaml` で定義され中央管理される。これは
以下を意味する:
- プロンプトエンジニアリングは 1 箇所 (prompts/ フォルダ) で発生
- LLM モデル切替は 1 config 変更、全モジュールではない
- 新 narrative type 追加 = llm_service に 1 YAML 追加

### モジュール別 LLM 呼び出しポイント

| モジュール | 呼び出しポイント | LLM の役割 | ルールベース維持部分 | Model tier | Context (in → out token) |
|---|---|---|---|---|---|
| **patient** | Chief complaint 生成 | 症状から自然言語 chief complaint | 症状選定と重症度 | Small | ~500 → 200 |
| **diagnosis** | 各判断点での差分更新 | Assessment 節の臨床推論 narrative | 確率計算 (Bayesian update)、LR 適用 | Medium | ~1,500 → 800 |
| **treatment** | 治療選択 / 変更判断 | 臨床 context 付き治療選択理由 | 薬剤選択ロジック、用量計算、相互作用チェック | Medium | ~1,200 → 600 |
| **encounter** | Admission H&P | 構造化データからフル History & Physical 文書 | データ収集自体 | Large | ~2,500 → 4,000 |
| **encounter** | Progress notes (キー日) | 臨床推論付き日次 SOAP note | Vitals / labs (構造化データとして挿入) | Medium | ~1,500 → 1,500 |
| **encounter** | 退院サマリ | 包括的退院文書 | 退院基準評価、タイミング | Large | ~4,000 → 5,000 |
| **encounter** | Consultation note | 専門科応答 (専門分野に適した言語で) | Consultation リクエストのルーティング | Medium | ~1,500 → 2,000 |
| **nursing** | シフトアセスメントノート | 構造化アセスメントからの看護 narrative | アセスメントデータ収集、vital sign 値 | Small | ~800 → 500 |
| **procedure** | Operative note | フル手術記録 | タイミング、チーム、合併症判定 | Large | ~2,000 → 3,000 |
| **validator** | 臨床整合性レビュー | 完全患者レコードの非妥当性レビュー | 変化率制限、相互排他 (ルールベース) | Large | ~6,000 → 1,500 |
| **population** | 受診決定 (エッジケース) | 患者の意思決定推論をシミュレート | 明確ケースは閾値ベース判断 | Small | ~500 → 200 |

**日本語 token 数注記:** 日本語テキストは tokenizer 特性により
同じセマンティック内容に対して英語より 1.5–2 倍多い token を必要
とする。上記見積は日本語出力を仮定。英語出力は ~30% 少ない
token。

**システムプロンプトオーバーヘッド注記:** 各 LLM 呼び出しは医師
/ 看護師 persona、国 context、出力形式を設定するシステム
プロンプト (~200–500 token) を含む。これは上記「in」見積に含まれ
ている。

### モデル tier 選択

| Tier | モデルクラス | 用途 | 呼出コスト目安 |
|---|---|---|---|
| **Small** | Haiku クラス | 大量、シンプルな生成 (chief complaint、簡潔な看護ノート、症状記述) | 最安 |
| **Medium** | Sonnet クラス | 臨床推論、治療理由、中長ノート | 中 |
| **Large** | Opus クラス | 退院サマリ、H&P ノート、整合性レビュー、複雑な臨床判断 | 最高 |

### コンテキスト最小化戦略

#### 1. コンパクトな構造化入力 (raw データではない)

患者履歴全体を LLM に渡す代わりに、**pre-summarized な臨床
コンテキスト** を渡す:

```python
@dataclass
class LLMClinicalContext:
    """LLM が臨床適切な出力を生成するのに十分な最小 context。"""
    # 患者サマリ (~100 token)
    age: int
    sex: str
    chief_complaint: str
    relevant_conditions: list[str]       # 現状況に関連する condition のみ
    relevant_medications: list[str]
    allergies: list[str]

    # 現在の臨床状態 (~100 token)
    current_diagnosis: str
    diagnosis_confidence: float
    key_findings: list[str]              # 例: ["CXR: lobar consolidation", "CRP 89", "PCT 1.8"]
    active_treatments: list[str]
    hospital_day: int

    # 前回ノート以降の変化 (~50 token)
    interval_events: list[str]           # 例: ["fever resolved Day 3", "CRP trending down"]
    pending_results: list[str]

    # 国 / 施設 context (~20 token)
    country: str
    hospital_type: str
    department: str
```

これは大半の呼び出しで入力を ~300 token 以下に保つ (患者レコード
全体送信の ~2000+ token に対して)。

#### 2. テンプレート誘導生成

LLM は自由形式テキストではなく構造化テンプレートの specific
セクションを埋める:

```python
PROGRESS_NOTE_TEMPLATE = """
## Progress Note — Day {hospital_day}
**S (Subjective):** {llm_generates}
**O (Objective):**
- Vitals: {rule_based_vitals}
- Labs: {rule_based_labs}
- Exam: {llm_generates}
**A (Assessment):** {llm_generates_with_diagnosis_context}
**P (Plan):** {llm_generates_with_treatment_context}
"""
```

これは LLM 出力を特定 field に制約、token 浪費を削減、構造的
整合性を保証する。

#### 3. バッチ生成

各時刻ステップで LLM を呼ぶ代わりに、関連呼び出しをバッチ化:

```python
# BAD: 14 日滞在で LLM を 14 回呼ぶ (日次ノートあたり 1 回)
for day in range(14):
    note = llm.generate_progress_note(day)

# GOOD: キー narrative ポイントを生成、そして拡張
key_events = rule_engine.identify_narrative_points(patient_timeline)
# 結果: [Day 0: 入院、Day 3: 発熱消失、Day 7: CXR 改善、Day 14: 退院]
# → 14 回ではなく 4 LLM 呼び出しのみ
# 中間日はテンプレートベースのノート (最小変動) を得る
```

#### 4. Cache とパターン再利用

共通臨床シナリオは類似の narrative を produce する:

```python
# Cache キー: (disease、archetype、severity、hospital_day、country)
# 例: ("bacterial_pneumonia", "smooth_recovery", "moderate", 3, "JP")
# 非常に類似のノートが以前生成されていたら、小変更 (名前、specific 値) で再利用

narrative_cache = LRUCache(max_size=1000)
cache_key = (disease_id, archetype, severity_bucket, day_bucket, country)
if cache_key in narrative_cache:
    note = narrative_cache[cache_key].adapt(patient_specific_values)
else:
    note = llm.generate(context)
    narrative_cache[cache_key] = note.generalize()
```

#### 5. LLM-free モード

システムは LLM 呼び出しなしで完全に機能する必要がある。LLM 強化
はオプション層:

```python
class NarrativeGenerator:
    def __init__(self, mode: str = "llm"):  # "llm" | "template" | "none"
        self.mode = mode

    def generate_progress_note(self, context):
        if self.mode == "llm":
            return self.llm_generate(context)
        elif self.mode == "template":
            return self.template_generate(context)  # ルールベース fill-in-the-blank
        else:
            return None  # narrative なし、構造データのみ
```

- **`none`**: 構造データのみ。最速、LLM コストゼロ。
- **`template`**: ルールベーステンプレート埋め。高速、LLM コスト
  なし、しかしフォームレターのように読める。
- **`llm`**: フル LLM 強化。最遅、コストがかかるが最大限リアル。

### 患者あたり token 予算

典型的 14 日肺炎入院滞在 (日本) について:

- **JUDGMENT tasks** (常に英語 — 効率的 token、高品質): 6 呼び出し、
  合計 ~10,600 token (診断推論 3 × 1,200 + 治療決定 2 × 1,000 +
  整合性レビュー 1 × 5,000)。
- **NARRATIVE tasks** (日本語出力 — 自然テキストのためより大きな
  token 予算): 11 呼び出し、合計 ~29,900 token (chief complaint、
  admission H&P、progress notes キー日、退院サマリ、看護ノート
  キーシフト)。
- **患者あたり合計**: JP ~40,500 token、US ~30,600 (英語出力は
  ~30% 少ない token)、呼び出し数 17。
- **患者あたりコスト目安** (Bedrock 価格 2025): JP ~$0.46、US
  ~$0.35。
- **スケール見積 (JP)**: 100 患者 ~$46、1,000 患者 ~$460 (cache
  ~50% hit で半分)。

#### JUDGMENT タスク (常に英語 — 効率的 token、高品質)

| タスク | 回数 | Input | Output | 合計 | Model |
|---|---|---|---|---|---|
| 診断推論 | 3 | 800 × 3 | 400 × 3 | 3,600 | Medium |
| 治療判断 | 2 | 700 × 2 | 300 × 2 | 2,000 | Medium |
| 整合性レビュー | 1 | 4,000 | 1,000 | 5,000 | Large |
| **Judgment 小計** | **6** | **7,400** | **2,200** | **10,600** | |

#### NARRATIVE タスク (日本語出力 — 自然テキストのためより大きな token 予算)

| タスク | 回数 | Input (en) | Output (ja) | 合計 | Model |
|---|---|---|---|---|---|
| Chief complaint | 1 | 500 | 200 | 700 | Small |
| Admission H&P | 1 | 2,000 | 4,000 | 6,000 | Large |
| Progress notes (キー日) | 4 | 1,200 × 4 | 1,500 × 4 | 10,800 | Medium |
| 退院サマリ | 1 | 3,000 | 5,000 | 8,000 | Large |
| 看護ノート (キーシフト) | 4 | 600 × 4 | 500 × 4 | 4,400 | Small |
| **Narrative 小計** | **11** | **12,300** | **17,200** | **29,900** | |

#### 合算

| | JP 患者 | US 患者 (全英語) |
|---|---|---|
| Judgment tasks | 10,600 | 10,600 (同) |
| Narrative tasks | 29,900 | ~20,000 (英語出力は ~30% 少ない token) |
| **患者あたり合計** | **~40,500** | **~30,600** |
| **LLM 呼び出し数** | **17** | **17** |

#### 患者あたりコスト目安 (Bedrock 価格 2025)

| Model tier | 呼び出し数 | JP 患者コスト | US 患者コスト |
|---|---|---|---|
| Small (Haiku) | 5 | ~$0.003 | ~$0.002 |
| Medium (Sonnet) | 9 | ~$0.06 | ~$0.05 |
| Large (Opus) | 3 | ~$0.40 | ~$0.30 |
| **合計** | **17** | **~$0.46** | **~$0.35** |

#### スケール見積 (JP 患者)

| 患者数 | 合計 token | 概算コスト | Cache (~50% hit) 適用時 |
|---|---|---|---|
| 10 | ~405K | ~$4.60 | ~$2.50 |
| 100 | ~4.05M | ~$46 | ~$25 |
| 1,000 | ~40.5M | ~$460 | ~$250 |

#### 予算制御
設定された予算上限に達すると、llm_service は残り呼び出しに対して
自動的にテンプレートモードに切り替わる。これはシミュレーションを
停止せずにコスト予測可能性を保証する。

### アーキテクチャ判断記録

| ID | 判断 |
|---|---|
| AD-7 | LLM は選択的増幅器: narrative と臨床推論を強化; 全数値 / 構造データはルールベースのまま |
| AD-8 | 3 生成モード: `none` (構造のみ)、`template` (ルールベーステキスト)、`llm` (フル LLM 強化) |
| AD-9 | コンパクト context パターン: 患者レコード全体ではなく pre-summarized `LLMClinicalContext` (~300 token) |
| AD-10 | バッチ + cache 戦略: LLM はキー narrative ポイントのみで呼ばれ、パターン cache 付き |
| AD-11 | 全 LLM 呼び出しは `llm_service` モジュール経由。他のモジュールは直接 LLM を呼んではならない。プロンプトテンプレートと fallback ロジックはここに中央化。 |
| AD-13 | 2 LLM タスクカテゴリ: JUDGMENT (常に英語、構造化応答) と NARRATIVE (対象国言語で出力)。英語 judgment は品質と token 効率を最大化。 |
| AD-16 | 階層 seed 管理経由の再現性。同 seed + 同 config = 同一構造データ。LLM 出力は再現性のため cache。 |
| AD-17 | 3 段出力: (1) シミュレーション (+ JUDGMENT LLM) → CIF 構造 (immutable、JUDGMENT で患者あたり ~10.6K token) → (2) CIF + NARRATIVE LLM → narrative 層 (置換可能、異なる LLM で再生成可能、患者あたり ~30K token) → (3) 構造 + narrative → format adapter。 |
| AD-18 | 全 YAML-loaded config 型に Pydantic BaseModel (ロード時スキーマ検証)。YAML から読み込まれない runtime-only 型に @dataclass。 |
| AD-19 | プリセット + override 設定パターン: `SimulatorConfig.preset("japan_medium").override({...})` |
| AD-20 | LLM graceful degradation: リトライ (3 回指数バックオフ) → テンプレート fallback → 構造のみ。シミュレーションは LLM 失敗で決して停止しない。 |
| AD-21 | Vertical slice 実装: v0.1-alpha (1 患者 happy path) → v0.1-beta (集団 + archetype) → v0.1 (フル)。 |
| AD-22 | 3 レベルテスト: unit (per module、<30 秒) → integration (モジュールチェーン、<5 分) → e2e (golden ファイル、<30 分)。 |
| AD-23 | 患者レベル async LLM (Mode 1)。semaphore 経由の bounded concurrency。sync fallback は常に利用可能。 |
| AD-24 | JUDGMENT と NARRATIVE は独立に構成可能な LLM プロバイダ / モデルを使用。ローカル + クラウド、異なるモデルファミリ、異なる tier を mix 可能。`llm_service.yaml` の `judgment:` と `narrative:` セクションで構成。 |

### 再現性と seed 管理

再現性はデバッグ、検証、科学的使用に必須。同一設定 + 同一 seed
は同一結果を produce する必要がある。

#### 課題: 決定的シミュレーション + 非決定的 LLM

シミュレーションエンジン (集団、生理、疾患、オーダータイミング等)
は seed が与えられれば完全決定的。しかし LLM 呼び出しは非決定性
を導入 (temperature=0 でも API 呼び出し間で出力が変わりうる)。

#### 解決: 階層 seed + LLM cache 分離

`SeedManager` は各モジュールに master seed から派生する決定的
sub-seed を割り当てる。

```python
class SeedManager:
    """全モジュールの再現可能な乱数生成を管理する。"""

    def __init__(self, master_seed: int):
        self.master_seed = master_seed
        self.rng = numpy.random.default_rng(master_seed)
        self._module_seeds = {}

    def get_module_seed(self, module_name: str) -> int:
        """各モジュールは master seed から派生する決定的 sub-seed を得る。"""
        if module_name not in self._module_seeds:
            self._module_seeds[module_name] = self.rng.integers(0, 2**32)
        return self._module_seeds[module_name]

    def get_patient_seed(self, patient_id: str) -> int:
        """各患者はそのシミュレーション用の決定的 sub-seed を得る。"""
        return hash((self.master_seed, patient_id)) % (2**32)
```

#### 再現性レベル

| Level | 保証 | 達成方法 |
|---|---|---|
| **Level 1: 構造** | 同患者、同疾患、同 encounter、同検査値、同タイムスタンプ | 全ルールベースモジュールに決定的 seed。LLM 依存なし。 |
| **Level 2: 構造 + cached LLM** | Level 1 + 同一 narrative テキスト | LLM 出力を disk に cache (task_type + event_data hash キー)。再実行時 cache がロードされ LLM 呼び出しなし。 |
| **Level 3: フルフレッシュ** | 構造データ同一。LLM テキストは僅かに変動しうる。 | LLM は fresh 呼び出し (cache なし)。構造データは依然決定的。 |

#### Seed 階層

master_seed から派生する sub-seed (population_seed、disease_seed、
staff_seed、encounter_seed、physiology_seed、order_seed、
nursing_seed、observation_seed、llm_cache_key)。各モジュールは
sub-seed から独自の `numpy.random.Generator` を初期化時に作成、
それのみを使用。モジュール間で random state を共有しない。

### テスト戦略

3 レベルのテスト、各明確な目的を持つ。

#### Level 1: 単体テスト (per module、高速、依存なし)

各モジュールが mock 入力で分離してテスト。テストプロパティ:
- **決定性**: 同 seed → 同出力。常に。
- **境界**: 検査値 0 未満なし、SpO2 100 超なし、負タイムスタンプ
  なし。
- **生理妥当性**: inflammation_level=0.5 からの CRP は 5–15 範囲、
  500 ではない。
- **カップリング正確性**: renal_function=0.3 → K 上昇、HCO3 減少。

#### Level 2: 統合テスト (モジュールチェーン、中速)

接続されたモジュールが coherent なデータフローを produce するか
テスト。例: 疾患プロトコルロード → 14 日生理走行 → 検査生成 →
CRP が Day 0-2 上昇、ピーク、14 日にわたって減少を検証。

#### Level 3: エンドツーエンド / golden ファイルテスト (フル
シミュレーション、遅い)

固定 seed で完全シミュレーションを実行、保存された「golden」CIF
と比較。例: seed=42 → 1 肺炎患者 → CIF JSON を
`tests/golden/seed42_1patient.json` と比較。任意の構造変化 =
テスト失敗 → 調査: 意図的か回帰か?

#### テスト実行戦略

```
make test-unit          # < 30 秒。各コミットで実行。
make test-integration   # < 5 分。各 PR で実行。
make test-e2e           # < 30 分。main へのマージで実行。
make test-all           # 全て。
```

---

### 実装規約

#### INTERFACES ファイル分割

`modules/INTERFACES.md` は単一の設計フェーズ文書。実装時にドメイン
別 Python モジュールに分割:

```
clinosim/types/
  __init__.py              # 便利のため全型を再エクスポート
  population.py            # PersonRecord、Household、LifeEvent、CareSeekingDecision、PregnancyState
  patient.py               # PatientProfile、PatientPhysiologicalProfile、BaselineVitals、ADLScore …
  clinical.py              # PhysiologicalState、StateChangeDirective、DifferentialDiagnosis …
  encounter.py             # Encounter、Order、OrderTimeline、ClinicalEvent …
  staff.py                 # StaffProfile、StaffAssignment、PersonName、StaffRole
  device.py                # DeviceReading、POCTResult
  output.py                # CIFPatientRecord、CIFDataset、CIFMetadata
  llm.py                   # ClinicalEventData、PatientSummary、LLMTaskType、LLMResponse
  config.py                # HealthcareSystemConfig、HospitalProfile、SimulatorConfig
```

全型は `@dataclass` を使用 (または Pydantic `BaseModel` — 下記
YAML 検証参照)。`from clinosim.types import PatientProfile` で
import。

#### YAML 設定検証

全 YAML config はロード時に検証される必要がある。型検証と
ドキュメント化の両方に **Pydantic** を使用:

```python
# 例: 疾患プロトコル検証
from pydantic import BaseModel, field_validator

class IncidenceConfig(BaseModel):
    base_rate_per_100k_per_year: dict[str, dict[str, float]]  # age_band → {M: rate, F: rate}
    risk_multipliers: list[RiskMultiplier]
    seasonal_curve: dict[int, float]  # month (1-12) → multiplier

    @field_validator("seasonal_curve")
    def validate_months(cls, v):
        assert set(v.keys()) == set(range(1, 13)), "Must have all 12 months"
        return v

class DiseaseProtocol(BaseModel):
    disease_id: str
    display_name: dict[str, str]
    icd_codes: ICDConfig
    incidence: IncidenceConfig
    severity: SeverityConfig
    # ... etc

# ロード時:
protocol = DiseaseProtocol(**yaml.safe_load(open("bacterial_pneumonia.yaml")))
# → スキーマ違反時に明確なメッセージで即エラー
```

利点:
- 無効な YAML はロード時に即失敗、実行時に silent には失敗しない
- スキーマがドキュメントとして機能
- IDE 自動補完と型 check
- 同モデルが検証 AND runtime 型として機能

**決定: 全 config 型に Pydantic BaseModel を使用。YAML から
ロードされない runtime-only 型に @dataclass を使用。**

#### 設定プリセット + override

ユーザは単一プリセットから開始し specific 値を override 可能で
あるべき:

```python
class SimulatorConfig:
    @classmethod
    def preset(cls, name: str) -> "SimulatorConfig":
        """名前付きプリセット設定をロード。"""
        presets = {
            "japan_medium": {"country": "JP", "hospital_scale": "medium", "catchment_population": 100_000},
            "japan_small": {"country": "JP", "hospital_scale": "small", "catchment_population": 20_000},
            "japan_large": {"country": "JP", "hospital_scale": "large", "catchment_population": 300_000},
            "us_medium": {"country": "US", "hospital_scale": "medium", "catchment_population": 100_000},
            # ... etc
        }
        return cls(**presets[name])

    def override(self, overrides: dict) -> "SimulatorConfig":
        """dot 記法 override を適用: {"facility.bed_count": 250, "population.size": 80000}"""
        for key, value in overrides.items():
            set_nested(self, key, value)
        return self

# 使用:
config = SimulatorConfig.preset("japan_medium")
config.override({
    "time_range": ("2024-04-01", "2025-03-31"),
    "random_seed": 42,
    "disease_modules": ["bacterial_pneumonia"],
    "llm.mode": "template",  # この実行では LLM なし
})
sim = Simulator(config)
```

#### 非同期 LLM 呼び出し

LLM 呼び出しは支配的ボトルネック (~500ms–5s 各)。Mode 1 では
患者シミュレーションが独立なので、LLM 呼び出しは並列化可能。

**戦略: 呼び出しレベルではなく患者レベルで async。**

```python
# simulator main loop 内:
async def run_async(self) -> SimulationResult:
    # 集団と setup は逐次
    population = self.population_module.generate()
    events = list(self.population_module.generate_all_events(population))

    # 患者シミュレーションは並行 (bounded concurrency)
    semaphore = asyncio.Semaphore(self.config.max_concurrent_patients)  # default: 10

    async def simulate_one(event):
        async with semaphore:
            return await self._simulate_hospital_visit_async(event, population)

    tasks = [simulate_one(e) for e in events if e.requires_hospital_visit]
    records = await asyncio.gather(*tasks)

    return SimulationResult(records=records, population=population)
```

llm_service レベルでは、プロバイダが async をサポート:

```python
class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt, model, max_tokens) -> ProviderResponse: ...

    @abstractmethod
    async def complete_async(self, prompt, model, max_tokens) -> ProviderResponse: ...

class BedrockGatewayProvider(LLMProvider):
    async def complete_async(self, prompt, model, max_tokens) -> ProviderResponse:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.gateway_url}/v1/complete", json={...})
            return ProviderResponse(**response.json())
```

**v0.1-alpha**: 同期のみ (シンプル実装)。
**v0.1**: async サポート追加。同期は fallback として引き続き利用
可能。

---

### 国際化 (i18n) アーキテクチャ

CIF 内部データは **language-neutral** (コード、数値 ID、標準化
enum)。国 / 言語固有レンダリングは定義された境界で発生する。

#### 4 つの i18n 層

```
Layer 1: 人物名          -- 集団 / スタッフ作成時に生成 → CIF に保存
Layer 2: 臨床用語        -- 出力アダプタ時にマップ (code_mapping YAML)
Layer 3: 単位とフォーマット -- 出力アダプタ時に適用 (国別フォーマット規則)
Layer 4: Narrative テキスト -- llm_service により Stage 2 で生成 (対象言語)
```

#### Layer 1: 人物名 (population、staff)

名前はアイデンティティの一部 — 作成時に一度生成、CIF に保存。

国別名前構造:

| 国 | 構造 | 姓の位置 | 正式表示 | 例 |
|---|---|---|---|---|
| JP | 姓 + 名 | 先 | 田中 太郎 | 田中 太郎 (Tanaka Taro) |
| US | 名 + 姓 | 後 | John Smith | John Smith |

世帯命名規則:
- JP: 全メンバーが姓を共有 (旧姓を保持する既婚女性は ~5% を除く)
- US: 子供は父の姓を取る (通常); 既婚カップルは異なりうる

CIF 内データ型:
```python
@dataclass
class PersonName:
    family_name: str          # "田中" / "Smith"
    given_name: str           # "太郎" / "John"
    display_name: str         # "田中 太郎" / "John Smith" (国フォーマット)
    name_script: str          # "ja" / "en" (名前が書かれる script)
    phonetic: str | None      # "タナカ タロウ" (JP: カタカナ; US: None)
```

#### Layer 2: 臨床用語翻訳 (output/code_mapping)

全内部コードは標準システム (ICD-10、LOINC/JLAC10、RxNorm/YJ) を
使用。表示名は権威ソースから出力時にマップされる。

**権威データソース (翻訳に LLM を使用してはならない):**

| ドメイン | 日本ソース | US ソース |
|---|---|---|
| 診断名 | 厚生労働省 標準病名マスター | CMS ICD-10-CM Official Guidelines |
| 検査名 | JLAC10 マスター (日本臨床検査標準協議会) | LOINC (Regenstrief Institute) |
| 薬剤名 | 医薬品マスター (PMDA) | RxNorm (NLM) |
| 手技名 | 診療報酬点数表 (厚労省) | CPT (AMA) |

**規則: 臨床用語は LLM で決して翻訳しない。常に公式マスター
データを使用。**

#### Layer 3: 単位とフォーマット (output/adapters)

各出力アダプタが国別フォーマット規則を適用:

| 項目 | 日本 | US |
|---|---|---|
| 体温 | ℃ (常に摂氏) | ℃ または ℉ (施設依存; 大半は ℃) |
| 体重 | kg | kg (臨床) または lb (患者向け) |
| 身長 | cm | cm (臨床) または ft/in (患者向け) |
| 日付形式 | yyyy年MM月dd日 または yyyy/MM/dd | MM/dd/yyyy |
| 時刻形式 | 24h (14:30) | 12h (2:30 PM) または 24h |
| 数値形式 | 1,234.5 | 1,234.5 (同) |
| 薬剤用量 | mg、g (メトリック) | mg、g (臨床文脈で同) |

これらの規則はアダプタに存在、CIF ではない。同じ CIF が任意の
国に対して正しくフォーマットされた出力を produce する。

#### Layer 4: Narrative 言語 (llm_service)

臨床 narrative は Stage 2 で対象国の言語で生成される。

- JP 病院 → 日本語 narrative (「38.5℃の発熱を認め、胸部X線にて
  右下葉浸潤影あり。」)
- US 病院 → 英語 narrative ("Fever of 38.5°C with RLL infiltrate
  on CXR.")

JUDGMENT タスクは常に英語 (AD-13)。NARRATIVE タスクは
`event.language` を使用。

テンプレートモードは stock フレーズから JP と EN 両方の narrative
を生成。LLM モード (Ollama/Claude) は指定言語で自然言語 narrative
を生成。

#### アーキテクチャ判断

| AD | 判断 |
|---|---|
| AD-25 | CIF は language-neutral。生成時に CIF に保存される唯一の国固有データは人物名。他の localization (用語翻訳、単位、フォーマット、narrative) は全て出力 / Stage 2 で発生。 |
| AD-26 | 臨床用語 (診断、薬剤、検査、手技名) は公式マスターデータのみを使用。LLM 翻訳は決してしない。マッピング YAML ファイルは権威ソースを引用。 |

---

### Condition-first シミュレーションモデル

#### 原則: 症状が診断より先

実病院では、患者は診断ではなく **condition** (症状、徴候、異常値)
を持って到着する。診断は臨床プロセスの **出力** であり、入力では
ない。

clinosim はこの forward プロセスをシミュレート:

```
Ground truth          臨床プロセス          EHR レコード
(hidden、CIF 内)      (シミュレート)         (出力)

原因:                 呈示:                 入院 Dx:
  既知疾患       -->    症状 / 徴候      -->    "Pneumonia, unspecified"
  混合原因       -->    重複症状          -->    "Pneumonia" (誤りかも)
  未知原因       -->    非特異的症状       -->    "Fever, unspecified"
                            |
                        Workup:
                          labs、imaging
                            |
                        Differential:
                          結果で更新
                            |
                        Working Dx:            Progress notes:
                          変わりうる           "Pneumonia suspected"
                            |
                        Final Dx:              Discharge Dx:
                          ground truth と      "Pneumonia due to S. pneumoniae"
                          異なりうる           (または 10% で "Fever, unresolved")
```

#### 3 つの condition 生成器タイプ

**Type 1: 既知原因 condition**
specific 疾患が状態変化を駆動。これは現行モデル。
- Ground truth: bacterial_pneumonia
- 状態軌跡: 疾患 YAML archetype に従う
- 診断プロセス: 臨床 workup は正しい疾患に収束すべき
- 臨床精度: ~85% 正しく診断 (調整可能)

**Type 2: 混合原因 condition**
複数疾患が同時に寄与。高齢者に一般的。
- Ground truth: pneumonia + heart_failure_exacerbation (両方
  活動)
- 状態軌跡: 両疾患影響の重ね合わせ
- 診断プロセス: 1 疾患が他をマスクしうる。初期診断は不完全
  かもしれない。
- 例: 80 歳、咳、呼吸困難、両側浸潤影。pneumonia、HF、両方?
  CXR は浸潤影 (どちらもありうる)。BNP 上昇 (HF?)。CRP 上昇
  (感染?)。利尿剤試行が部分的に効く (HF 成分)。抗生剤も効く
  (感染成分)。最終 dx: "Pneumonia with acute HF exacerbation"
  — 両方とも real。

**Type 3: 未知原因 condition**
明確な疾患メカニズムなしに状態変化が発生。
- Ground truth: `unknown` または `idiopathic_{symptom_pattern}`
- 状態軌跡: 確率的だが生理的に制約される
- 診断プロセス: 広範な workup、未診断のままかもしれない
- 例:
  - Fever of unknown origin (FUO): 明確な原因なしに炎症が上昇
  - 高齢者の説明されない体重減少
  - 軽度上昇炎症マーカー付き非特異的倦怠感
  - Drug fever (原因は医原性で疾患ではない)
- 最終 dx: "R50.9 Fever, unspecified" (~10% のケースで退院時
  未解決)

#### Ground truth vs 臨床診断

```python
@dataclass
class ConditionEvent:
    """患者に実際に起こること (hidden ground truth)。"""
    condition_id: str
    condition_type: str           # "known_disease" | "mixed" | "unknown"

    # known_disease 用:
    ground_truth_diseases: list[str]  # ["bacterial_pneumonia"] or ["bacterial_pneumonia", "heart_failure_exacerbation"]

    # unknown 用:
    symptom_pattern: str          # "fever_unknown" | "weight_loss" | "malaise"

    # 状態影響はタイプに関わらず適用される
    state_impacts: dict[str, float]   # 全原因からの combined impact

@dataclass
class ClinicalDiagnosis:
    """病院が結論すること (ground truth と異なりうる)。"""
    admission_diagnosis: str      # 入院時 ICD コード (しばしば漠然)
    working_diagnoses: list       # 滞在中に発展
    discharge_diagnosis: str      # 退院時 ICD コード (依然漠然かも)

    diagnosis_correct: bool       # 退院 dx が ground truth と一致するか? (CIF hidden field)
    missed_diagnoses: list[str]   # 識別されなかった ground truth 疾患
    overcalled_diagnoses: list[str]  # 診断されたが実際は存在しない
```

#### 診断精度パラメータ

実世界診断精度は変動する。clinosim は tunable パラメータとして
モデル化:

| パラメータ | デフォルト | 意味 |
|---|---|---|
| `initial_correct_rate` | 0.60 | 最初の working diagnosis が正しい確率 |
| `final_correct_rate` | 0.85 | 退院診断が ground truth と一致する確率 |
| `missed_secondary_rate` | 0.30 | 混合ケースで 2 次診断を見逃す確率 |
| `fuo_rate` | 0.05 | 発熱ケースが未診断のままの確率 |
| `incidental_finding_rate` | 0.08 | Workup 中に無関係な condition を発見する確率 |

これらは異なる「臨床品質」レベルでデータを生成するよう調整可能:
- **実世界デフォルト**: 公表誤診率と一致
- **高品質設定**: 平均より良い (理想シナリオテスト用)
- **低品質設定**: より多くのエラー (エラー検出アルゴリズム訓練
  用)

#### アーキテクチャ判断

| AD | 判断 |
|---|---|
| AD-28 | Condition-first モデル: 患者は診断ではなく症状で呈示する。Ground truth (hidden) は臨床診断 (記録) と異なりうる。3 condition タイプ: known-disease、mixed-cause、unknown-cause。 |
| AD-29 | 診断精度は tunable パラメータ。デフォルトは実世界レート (~85% 正しい) と一致。異なる用途のために調整可能。 |

---

## 3. 2 つのシミュレーションモード

clinosim は 2 つのシミュレーションモードをサポート。Mode 2 は
Mode 1 のスーパーセット。

### Mode 1: 患者レコード生成

個別患者用の臨床整合的 EHR レコードを生成。病院環境は妥当な
レコード帰属 (誰が何をオーダーしたか、誰が何を実施したか) の
コンテキストとしてのみ存在する。

- **焦点**: 一度に 1 患者、臨床整合性
- **病院リソース**: 利用可能と仮定 (ベッド不足なし、OR スケジュー
  ル競合なし)
- **スタッフ**: レコードの妥当性のためイベントごとに割当、しかし
  シフト / ワークロードシミュレーションなし
- **用途**: EHR 開発 / テスト、研究データセット、アルゴリズム
  検証、ML 訓練データ

### Mode 2: 病院運用シミュレーション

時間期間にわたって病院全体をシミュレート。複数患者が同時に存在
し、共有リソース (ベッド、OR スロット、スタッフ時間) を巡って
競合する。患者レコードと運用データの両方を produce。

- **焦点**: システムとしての病院、リソース競合、時間並列性
- **病院リソース**: 有限で制約される (ベッド稼働率、OR スケジュー
  ル、スタッフ配置レベル)
- **スタッフ**: フルシフトシミュレーション、ワークロード追跡、
  オンコールローテーション
- **用途**: 病院管理分析、ワークフロー最適化、キャパシティ計画、
  スタッフ配置モデル

### アーキテクチャ的含意

モジュールは Mode 2 (フルモデル) を念頭に設計される。Mode 1 は
同じモジュールを走らせるが以下:
- リソース競合ロジックをスキップ (ベッド常に利用可能、OR 常に
  開)
- スタッフ割当を簡略化 (妥当な practitioner を選ぶ、シフト負荷
  を無視)
- 並行 population ではなく一度に 1 患者を実行
- 運用イベント生成を省略 (ベッド管理イベントなし、シフト引継ぎ
  レコードなし)

各モジュールの SPEC.md はどの挙動が Mode 2 only かをドキュメント
化する。

---

## 3. Population-Driven シミュレーションアーキテクチャ

### コア原則

clinosim は患者を生成 **しない**。**集団** を生成し、人々に生活
させ、病院訪問時に何が起こるかを観察する。これは他の合成データ
生成器との根本的な違い。

```
伝統的アプローチ:      患者 → 疾患 → 病院レコード    (逆向き)
clinosim アプローチ:   集団 → ライフイベント → 病院訪問 → レコード    (前向き、現実のように)
```

### 2 層集団モデル

各人を詳細にシミュレートするのは計算的に不可能。集団は 2 層
モデルを使用:

**Layer 1 — 集団レジストリ (軽量)**
- catchment 地域の全人がここに存在
- 保存: demographics、世帯、慢性疾患 (要約)、healthcare engagement
  プロファイル
- 年次更新: 加齢、新慢性疾患発症 (確率的)、死亡、移住
- コスト: 人あたり ~100 バイト。100,000 人 ≈ 10 MB
- 病院を決して訪問しない人はこの層に永遠に残る

**Layer 2 — アクティブ患者 (詳細)**
- 人が病院を訪問すると (任意 encounter type) アクティブ化
- 生理パラメータ、詳細医療履歴、baseline vital 付きフル
  `PatientProfile`
- フル臨床シミュレーション: 生理、診断、治療、観察
- 退院 + フォローアップ完了後、人は Layer 1 に戻る (履歴は保持)
- 次の病院訪問で再アクティブ化 (全前データ intact で)

### 世帯ベース生成

人は孤立した個人としてではなく **世帯** に属して生成される:

- 世帯が最初に生成され、次にメンバーが配置される
- 世帯タイプ: 単身高齢、高齢者夫婦、核家族 (親 + 子)、3 世代、
  単身労働成人等
- メンバーが共有: 住所、家庭医、保険タイプ (部分的)、遺伝的
  リスク因子
- 感染症は世帯内で伝染可能 (例: インフルエンザ)
- 家族関係は明示的: 「家族歴」を実にする、ランダム生成しない
- 生活状況 (単身 vs 家族) は世帯から派生、独立に割当てられない

### ライフイベントエンジン

集団はシミュレート時間を通じてライフイベントで進化する:

**年次解像度 (全集団):**
- 加齢 (+1 年)
- 新慢性疾患発症 (年齢 / 性別固有 incidence)
- 慢性疾患進行 (例: CKD stage 3 → stage 4)
- 死亡 (年齢 / 性別固有死亡率)
- 移住 (catchment 地域への出入り)
- 雇用変化 (退職、転職 → 保険変化)

**確率イベント (連続、月次または細かい解像度で check):**
- 急性疾患発症 (季節依存 incidence)
- 事故 / 外傷 (年齢 / 活動依存)
- 慢性疾患急性増悪
- 妊娠 (病院サービスに関連する場合)

**Care-seeking 決定 (per event):**
- 症状を produce する各ライフイベントは人の care-seeking 閾値に
  対して評価される
- 決定要因: 症状重症度、健康リテラシー、時刻、曜日、保険 /
  コスト、家族影響
- 結果: 行動なし、self-care、外来訪問、ER 訪問、救急車呼び出し

### 紹介経路

大半の病院患者は直接ではなく紹介経由で到着する:

```
症状のある人
  ├── 軽度 → 地元クリニック / GP (かかりつけ医 / PCP)
  │     └── クリニックの capability を超える → 紹介状 → この病院
  ├── 中等度 → この病院外来 (紹介あり / なし)
  ├── 重度 → この病院 ER
  └── 緊急 → 救急車 → この病院 ER
```

紹介元クリニックは完全にはシミュレートされない — 以下として表現:
- 基本情報付き紹介元 (クリニック名、紹介医)
- 前レコード要約 (紹介につながったキー所見)
- これは現実的な紹介状と入院 context 生成に十分

### 一時訪問者

catchment 地域外の care を必要とする人:
- 集団への一時追加として生成
- 通常 ER 経由で呈示 (旅行 / 労働中の事故、急性疾病)
- 限定的な事前医療履歴 (この病院にレコードなし)
- 治療後: 帰宅または転送
- ボリューム: ER encounter の ~5–10% (観光 / ビジネスエリアで高
  い)
- 縦断的フォローアップなし (一回限りの encounter)

### アーキテクチャ判断記録

| ID | 判断 | 理由 |
|---|---|---|
| AD-3 | Population-driven forward シミュレーション | リアリズム: 実世界は病院需要ではなく集団動態で患者を生成する |
| AD-4 | 2 層集団モデル (registry + active) | 性能: 病院訪問者のみフルシミュレーション要 |
| AD-5 | 世帯ベース生成 | リアリズム: 家族構造が保険、生活状況、遺伝リスク、感染伝染を駆動 |
| AD-6 | シミュレーション対象ではなく context としての紹介元クリニック | Scope: 完全 GP シミュレーションはスコープ外; 紹介状と前レコードで十分 |

---

## 4. フォルダ構造

```
clinosim/
├── DESIGN.md              ← この文書 (設計ガイドライン)
├── docs/roadmap.md        ← ロードマップ (GitHub Issues board を指す)
├── docs/history/spec-2026-04.md  ← 歴史的 spec (2026-04、参考として保持)
├── README.md              ← プロジェクト紹介
│
├── modules/
│   ├── INTERFACES.md      ← コアデータ型定義 (モジュール間コントラクト)
│   ├── population/        ← catchment 集団、世帯、ライフイベント
│   ├── facility/          ← 病院施設定義 (規模、診療科、ベッド)
│   ├── staff/             ← 医療スタッフ生成、ライフサイクル & 割当
│   ├── patient/           ← Layer 1 → Layer 2 アクティブ化 & 臨床詳細
│   ├── encounter/         ← Encounter タイプ & ワークフロー state machine
│   ├── order/             ← Order ライフサイクル (order → execute → result)
│   ├── physiology/        ← 生理状態変数 & 状態空間
│   ├── disease/           ← 疾患定義 & イベントスケジューリング
│   ├── diagnosis/         ← 診断推論エンジン
│   ├── clinical_course/   ← 臨床コースエンジン (archetype、状態遷移)
│   ├── treatment/         ← 薬剤 & 治療モデル
│   ├── observation/       ← 検査 & vital sign 生成 (3 層エンジン)
│   ├── nursing/           ← 看護プロセス & ケアレコード
│   ├── procedure/         ← 手術 & 手技ワークフロー
│   ├── validator/         ← 整合性検証
│   ├── healthcare_system/ ← 医療システム設定 (日本 / US)
│   ├── llm_service/       ← LLM 統合サービス (LLM 接触の単一ポイント)
│   │   ├── prompts/       ← プロンプトテンプレート (YAML)
│   │   └── templates/     ← テンプレートモード fallback (LLM なし)
│   └── output/            ← データエクスポート (FHIR R4、CSV)
│
└── simulator/             ← メインオーケストレータ
```

### モジュールフォルダあたり必要ファイル

| File | 内容 |
|---|---|
| `SPEC.md` | モジュール目的、入出力定義、確定 spec、open question |

### SPEC.md テンプレート

```markdown
# Module Name

## Purpose
このモジュールが何をするか (1–2 文)。

## Inputs
- 受け取るもの (データ型、ソースモジュール)

## Outputs
- produce するもの (データ型、consumer モジュール)

## Dependencies
- 依存するモジュール

## Confirmed Specifications
(確定した設計判断をここに追記)

## Open Questions
(モジュール固有の open question)

## Design Notes
(議論中のアイデアとオプション)
```

---

## 5. モジュール間 Interface 規約

### データフロー — Population-driven シミュレーション

主要 flow は 2 フェーズ:

**World Setup (一度):**
`healthcare_system → facility → staff (roster)` + `population`
(catchment 生成 → 世帯 + person registry Layer 1)。

**Time シミュレーション (連続):**
`population → ライフイベント (疾患発症、事故、加齢、…)`
→ care-seeking 決定 → YES なら病院訪問:
`patient (Layer 1 → Layer 2 アクティブ化) → encounter →
clinical_course → observation → validator`。`diagnosis` /
`treatment` / `order` / `procedure` / `nursing` が clinical_course
とインタラクト。`staff` がイベントごとに割当。`disease` が
プロトコル提供。最終的に `output (FHIR / CSV)` へ。退院 →
Layer 2 → Layer 1 (更新履歴付き)。NO なら人は Layer 1 に留まる
(病院データ生成なし)。Mode 2 では: ベッド競合、OR
スケジューリング、スタッフワークロード、キュー追加。

```
┌─── World Setup (一度) ───────────────────────────────────┐
│                                                          │
│  healthcare_system ──→ facility ──→ staff (roster)       │
│          │                                               │
│          └──→ population (catchment area 生成)           │
│                  │                                       │
│                  ├── households                          │
│                  └── person registry (Layer 1)           │
└──────────────────────────────────────────────────────────┘

┌─── Time シミュレーション (連続) ────────────────────────────────────────┐
│                                                                          │
│  population ──→ ライフイベント (疾患発症、事故、加齢、…)                │
│       │              │                                                   │
│       │         受診決定                                                 │
│       │              │                                                   │
│       │         ┌────┴─── YES: 病院訪問 ────────┐                       │
│       │         │                                 │                      │
│       │    patient (Layer 1 → Layer 2 アクティブ化) │                    │
│       │         │                                 │                      │
│       │    encounter ──→ clinical_course ──→ observation ──→ validator   │
│       │         │              ↑                  ↑              │       │
│       │      order ←─── diagnosis            treatment          │       │
│       │         │              │                  │              │       │
│       │      procedure     nursing               │              │       │
│       │         │              │                  │              │       │
│       │         └── staff (イベントごとに割当) ───┘              │       │
│       │                                                          │       │
│       │    disease (プロトコル) ──────────────────────────────────┘       │
│       │                                                                  │
│       │    ──→ output (FHIR / CSV)                                      │
│       │                                                                  │
│       │    ──→ 退院 ──→ Layer 2 → Layer 1 (更新履歴付き)                │
│       │                                                                  │
│       └── NO: 人は Layer 1 に留まる (病院データ生成なし)                │
│                                                                          │
│  Mode 2 では追加: ベッド競合、OR スケジューリング、スタッフ負荷、キュー │
└──────────────────────────────────────────────────────────────────────────┘
```

### Interface 設計原則

1. **モジュールは dataclass / TypedDict 経由で通信**
   - 各モジュールの SPEC.md は入出力の型を定義
   - 実装は Python `dataclass` または `TypedDict` を使用

2. **`healthcare_system` は cross-cutting パラメータプロバイダ**
   - 全モジュールは国別パラメータを受け取り可能
   - `healthcare_system` 自身は他モジュールへの依存なし

3. **`facility` が施設 context を定義; `staff` がそれを埋める**
   - `facility` が病院規模、診療科、ベッド数を決定
   - `staff` は practitioner を生成し臨床イベントへの割当を管理
   - 全 EHR 記録イベントは一貫したスタッフ帰属を carry する必要
   - `staff` 割当はイベント生成時にシミュレータから呼び出される

4. **`encounter` がワークフローを制御; `order` がその中のアクション
   のライフサイクルを管理**
   - `encounter` は訪問タイプ (外来、ED、入院等) とその進行を統治
     する state machine を定義
   - `order` は全臨床アクション (labs、imaging、薬剤、手技) の
     order → execute → result サイクルを管理
   - `nursing` は看護固有イベント (アセスメント、vital sign
     スケジュール、ケア記録) を生成
   - `procedure` は手術 / 手技ワークフロー (術前、手術、術後回復)
     を処理
   - Mode 1 では encounter/order はリソース制約なしで走行
   - Mode 2 では encounter/order は facility リソース管理 (ベッド
     割当、OR スケジューリング、スタッフ利用可能性) とインタラ
     クト

5. **`disease` がプロトコル定義を提供**
   - Lab プロトコル、治療プロトコル、コースパターンは YAML で
     定義
   - エンジンモジュールは自身の挙動を駆動するために疾患定義を
     参照

6. **`simulator` がオーケストレーションを処理**
   - モジュール間の実行順序と依存解決を管理
   - モジュール間データフローを仲介
   - Mode 1: 一度に 1 患者を処理
   - Mode 2: 並行患者付き離散イベントシミュレーションを実行

---

## 4. 設計ワークフロー

### 原則

- **1 モジュール = 1 コンテキスト**: 設計セッションは一度に単一
  モジュールに焦点
- **Interface-first**: 内部実装前に入出力を定義
- **判断を即記録**: 合意されたら SPEC.md に確定 spec を書く
- **Open question を明示的に追跡**: TODO.md とモジュール SPEC.md
  の両方に

### 設計優先順序

1. モジュール間 interface (入出力型) に合意 (全モジュール横断)
2. その後個別モジュールの内部設計を肉付け
3. 疾患固有 config (YAML) は疾患ごとに漸進的に追加

---

## 5. 命名規則

| ターゲット | 規約 | 例 |
|---|---|---|
| モジュールフォルダ | snake_case | `clinical_course/` |
| Python ファイル | snake_case | `state_engine.py` |
| クラス名 | PascalCase | `PatientProfile` |
| 状態変数 | snake_case | `inflammation_level` |
| Config ファイル | snake_case.yaml | `pneumonia.yaml` |
| FHIR Resource id | type-encounter-suffix | `lab-ENC-POP-000001-000123-0042` |
| コードシステムキー | lowercase-with-hyphens | `icd-10-cm`、`loinc`、`k-codes` |

---

# Part 6 — アーキテクチャ更新 (v0.1-beta、2026-04-08)

このパートは初期 v0.1-alpha 基盤の後に下された主要なアーキテク
チャ判断をドキュメント化する。live codebase に統合されているが、
歴史的参照のため ADR としてここに記録される。

Part 6 の詳細な per-topic 議論は
[`architecture-notes.ja.md`](architecture-notes.ja.md) の
§6.1–§6.11 セクションに配置されている。ADR の完全リストは
[`adr-history.ja.md`](adr-history.ja.md) 参照。
