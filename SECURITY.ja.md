# セキュリティポリシー

## サポート対象バージョン

clinosim は pre-1.0 リリーストラックの独立した個人プロジェクトです。
セキュリティ修正は **最新リリースバージョンのみ**に backport されます。
それ以前は先にアップグレードしてください。

| Version | Supported |
|---------|-----------|
| 0.2.x   | ✅ |
| < 0.2   | ❌ |

## 脆弱性の報告

**公開 GitHub Issue、GitHub Discussion、pull request では
セキュリティ問題を報告しないでください。** 公開報告は修正前に
攻撃者に問題を知らせることになります。

代わりに、GitHub 組み込みの **Security Advisories** チャンネル
経由で非公開に報告してください:

- [https://github.com/TomoOkuyama/clinosim/security/advisories/new](https://github.com/TomoOkuyama/clinosim/security/advisories/new)
  にアクセスして draft advisory を作成。
- 問題の明確な説明、影響 (何のデータ / 挙動が侵害されうるか)、
  proof-of-concept または最小再現手順、既知の緩和策 を含める。

draft advisory は published されるまで報告者とプロジェクト
メンテナのみに可視です。

## セキュリティ問題とみなす対象

clinosim は **合成データ生成器**であり実患者データに触れないため、
セキュリティ表面は小さいものの空ではありません。以下は **報告して
ください**:

- 不正な YAML / template / CLI 入力による code execution / injection。
- clinosim が実質的に露出させる依存ライブラリの脆弱性 (ユーザー入力
  に到達しない transitive noise は不要)。
- CIF / FHIR output writer での path traversal または任意書き込み。
- 再現可能な研究出力を silent に破壊する決定論への影響
  (data-integrity 脆弱性として扱う)。

以下は **報告不要**:

- 生成された合成データが実在人物に「似ている」という懸念 — data は
  population level 分布から乱数生成しており、類似は偶然です。
  README の免責参照。
- 認証 / 認可の追加要求 — clinosim は CLI であり service ではない。

## 対応時間

個人プロジェクトで on-call rotation は無いため猶予をください。
best-effort target:

| Step | Target |
|---|---|
| 受領確認 | 5 営業日 |
| 評価 + 深刻度判定 | 10 営業日 |
| 修正 or 緩和リリース | 受領確認から 90 日、または報告者と協議 |
| 公開 advisory 公表 | 修正リリース後 |

報告者は公開 advisory で名前を credit されます (匿名希望の場合
除く)。

## 適用範囲

本ポリシーは本 repository master branch 上の `clinosim` パッケージ
と、そこから publish される wheel / sdist artifact を対象とします。
サードパーティ fork や下流ディストリビューションは対象外です。

英語版: [`SECURITY.md (English)`](SECURITY.md)。
