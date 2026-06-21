# Seitijunrei-Scraper（聖地巡礼スクレイパ）

検索窓に**項目（作品名など）**を入力すると、**note の検索結果**（任意で Twitter 公式 API）から
聖地巡礼の投稿を集め、本文から**地名を抽出 → 座標化 → 投稿横断でまとめ直し**、各地点を
**`Seiti` クラス（座標・出典・スクリーンショット）**として収集する Web アプリ／ライブラリです。

### パイプライン（「まとめ直し」の自動化）

```
項目 ─▶ note検索（"項目 聖地巡礼" 等）─▶ 投稿本文から地名抽出（神社/駅/海岸…）
     ─▶ Nominatim で座標化（日本に限定）─▶ 同一地点を投稿横断で集約（出典URL・言及数）
     ─▶ Seiti化 ＋ 1m重複統合
```

- 同じ地点に複数投稿が言及していれば**出典をまとめ、言及数の多い順に並べ**ます。
- **座標が 1m 以内**の `Seiti` は同一の聖地とみなして統合し、出典は survivor に集約します。
- 統合で**消える側は「候補」として退避**し、候補は**最大 80 件**保持（超過時は古い順に破棄）。

### データ源

| ソース | 状態 | 備考 |
|---|---|---|
| **note** | ✅ 実装（スクレイプ） | 検索 JSON を利用。規約上グレーのため低頻度・私的利用前提 |
| **Twitter/X** | ⚠️ 公式 API のみ | 環境変数 `TWITTER_BEARER_TOKEN` がある時だけ有効。**スクレイプはしない**（規約違反・凍結リスク） |
| **Nominatim** | 地名→座標 変換に使用 | 抽出地名のジオコーディング専用 |

> ⚠️ 当初仕様の「Googleサジェスト類似ワードマップ」「Google検索スクレイプ」は
> 利用規約リスク回避のため**不採用**です。

---

## 構成

```
app/
  models.py       Coordinate / Seiti / SeitiStore（重複統合・出典集約・候補退避の中核）
  sources.py      検索ソース: NoteSource（スクレイプ）/ TwitterSource（公式APIのみ）
  extract.py      投稿本文からの地名抽出ヒューリスティック
  geocode.py      Nominatim(OSM) ジオコーディング（レート制御つき・日本限定可）
  aggregate.py    note→抽出→座標化→まとめ直し のパイプライン（本体）
  screenshot.py   Playwright による地図スクショ（失敗時は None でグレースフル）
  scraper.py      旧: Nominatim 地名検索のみの簡易フロー（後方互換）
  main.py         FastAPI Web アプリ + JSON API
  templates/      検索 UI（Jinja2）
tests/            pytest（抽出・集約・重複統合・ソース・認証 をカバー）
```

### Twitter を有効にする（任意）

```bash
export TWITTER_BEARER_TOKEN='＜X API のトークン＞'
uvicorn app.main:app --reload
```
トークンが無ければ note のみで動作します。

## セットアップ

```bash
pip install -r requirements.txt
python -m playwright install chromium    # スクショ機能を使う場合のみ
```

## 起動（ローカル）

```bash
uvicorn app.main:app --reload
# http://127.0.0.1:8000 にアクセス
```

## 公開（簡易パスワード付き）

全ルート（`/screenshots` 含む）に **HTTP Basic 認証**が掛かります。
パスワードは環境変数で設定します。

```bash
export SEITI_USER=admin            # 既定: admin
export SEITI_PASSWORD='強いパスワード'  # 既定: seichi（公開時は必ず変更）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- ブラウザでアクセスするとユーザー名／パスワードを求められます。
- ローカル開発で認証を切るには `SEITI_AUTH=0`。
- ⚠️ **Basic 認証は資格情報を Base64 で送るだけ**なので、インターネット公開時は
  **必ず HTTPS（リバースプロキシ: Caddy / Nginx / Cloudflare 等）の背後**で運用し、
  平文 HTTP で晒さないでください。

- 検索窓に作品名等を入れて「検索」。`スクショ取得` を ON にすると各地点の
  地図 PNG を取得します（遅くなります）。
- JSON API: `GET /api/search?item=作品名&screenshots=false`

## ライブラリとしての利用

```python
from app.scraper import scrape, ScrapeConfig

store = scrape("らき☆すた", ScrapeConfig(take_screenshots=False))
for s in store.seiti:
    print(s.name, s.coordinate.lat, s.coordinate.lon, s.source)
print("候補:", len(store.candidates))   # 統合で退避した重複（最大80）
```

## テスト

```bash
python -m pytest -q
```

---

## 使用上、確認・注意すべきこと（重要）

ご依頼の「使用上確認すべきこと」への回答です。

1. **聖地の検出精度（recall）に構造的な限界がある**
   類似ワードマップとGoogleを外したため、地点探索は **Nominatim の地名一致** に依存します。
   Nominatim は「地名・施設名」を返すもので、「ここはアニメ◯◯の聖地」という意味づけは持ちません。
   実際の聖地（背景に使われた風景・交差点など）は OSM に固有名で載っていないことが多く、
   **取りこぼし（ヒット0件）が起こり得ます**。
   → 精度を上げるなら、Overpass / 自前の聖地DB / 別の検索ソースを `geocode.py` 互換I/Fで
   差し替える設計にしてあります。必要なら拡張します。

2. **Nominatim 利用規約**（公開サーバを使う場合）
   - **最大 1 リクエスト/秒**（本実装は送出間隔を強制済み）。
   - **連絡先を含む User-Agent が必須**。`geocode.py` の `DEFAULT_USER_AGENT` を
     **自分の連絡先に必ず差し替えてください**。
   - 大量・常時利用は禁止。業務利用は自前 Nominatim か商用プロバイダを使用。
   - 規約: https://operations.osmfoundation.org/policies/nominatim/
   - ※サンドボックス環境では `403 Forbidden`（egress制限/ブロック）を確認。
     **実運用は外向き通信が許可された環境で実行**してください。失敗時はその検索を
     スキップして処理継続します（全体は止まりません）。

3. **スクリーンショットの取得元とタイル利用ポリシー**
   スクショは `openstreetmap.org` の地図ページを描画して撮ります。OSM タイルにも
   利用ポリシーがあり、**大量撮影は不可**。多用するなら自前タイルサーバ等を検討してください。
   また Playwright のブラウザ（`playwright install chromium`）が無い環境では
   スクショは `None` になり、`Seiti` はスクショ無しで作成されます。

4. **データのライセンス（OSM/ODbL）**
   取得した座標・地名は OpenStreetMap 由来で **ODbL**。再配布・公開時は
   **出典表示（© OpenStreetMap contributors）**が必要です。

5. **重複統合のルール（仕様の確定事項）**
   - 距離判定は haversine（球面近似）。1m 前後の判定に十分な精度。
   - 1m 以内 → 同一。**情報量（スクショ有無・名称・ソース）が多い方を残し**、
     少ない側を候補へ。**同点なら先に登録された既存を残す**（＝新規が消える側）。
   - 候補は最大 80 件。超過時は `found_at` が**最古のものから破棄**。
   - しきい値・上限は `ScrapeConfig` / `SeitiStore` で変更可能。

6. **検索キーワード**
   既定は `["聖地", "聖地巡礼", "舞台", "ロケ地"]`。`ScrapeConfig(keywords=[...])` で変更可。

7. **個人情報・私有地への配慮**
   聖地巡礼は実在の場所・住宅が含まれます。収集結果の公開時はマナー／私有地配慮を。
