# ABDS — Arsenal Base Deck Simulator

ガンダムアーセナルベースのデッキ構築シミュレータ＆カードデータ管理システムです。

カード画像のOCR処理によるデータ構造化、デッキ編成シミュレーション、ステータス計算、リンクアビリティ判定、デッキの投稿・共有などの機能を提供します。

## 主な機能

### デッキシミュレータ (v2)
- MS5枚 + PL5枚のデッキ編成
- ステータス自動計算（リンクバフ・地形補正込み）
- リンクアビリティ発動判定・表示
- 作戦カード（メイン・サブ）の設定
- SQ / EB発動条件の自動判定
- デッキの保存・読込（ブラウザローカル）
- デッキコードによる共有
- デッキのサーバー投稿（投稿者名・削除パスワード対応）
- デッキ画像スクリーンショット（PNG出力）
- ランダムデッキ生成（リンク指定対応）

### カード検索
- 多条件フィルター（レアリティ・カテゴリ・シリーズ・コスト・ステータス・地形適性）
- EB / SQ / SP / PLスキルの詳細フィルター
- テキスト検索（名前・番号・カードテキスト）
- カードブックマーク機能（OR条件で検索結果と統合）
- カード詳細モーダル（全OCRデータ表示）
- イラストレーター検索

### デッキ一覧
- 投稿デッキの閲覧・いいね・コメント
- デッキブックマーク（ローカル保存）
- ソート（新着・いいね順・ブックマーク順）
- 期間フィルター（全期間・週間・月間）
- コンパクト表示モード
- リンクアビリティ発動状況表示（EB/SQ色分け）

### カードデータ管理
- 公式サイトからのカードメタデータ自動取得
- OpenAI Vision API / Claude APIによるOCR処理
- 2段階OCR（Stage1: raw抽出 → Stage2: 構造化）
- OCR管理画面（進捗確認・一括実行）

### 画像キャッシュ
- ブラウザ IndexedDB によるカード画像キャッシュ
- 一括ダウンロード・管理機能
- オフライン表示対応

## 技術構成

| コンポーネント | 技術 |
|---|---|
| バックエンド | Flask (Python) |
| フロントエンド | HTML/CSS/JS（テンプレート内、SPA風） |
| データベース | Supabase PostgreSQL（本番） / JSON（ローカル開発） |
| OCR | OpenAI Vision API / Claude API |
| デプロイ | Render (gunicorn) |
| 画像キャッシュ | IndexedDB (ブラウザ側) |

## セットアップ

### 必要条件

- Python 3.10以上
- OpenAI APIキー（OCR機能を使う場合のみ）

### インストール

```bash
git clone https://github.com/sekimiya/abds.git
cd abds
pip install -r requirements.txt
```

### 環境変数（任意）

```bash
# Supabase（本番DB。未設定時はローカルJSON fallback）
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your-anon-key

# OCR用（OCR機能を使う場合のみ）
# APIkey.txt にOpenAI APIキーを記述
```

### 起動

```bash
python app.py
```

- ローカル: http://127.0.0.1:5001
- LAN: http://<自分のIP>:5001

## ページ一覧

| パス | ページ | 説明 |
|---|---|---|
| `/v2` | デッキシミュレータ v2 | メイン画面。デッキ構築・シミュレーション |
| `/decks.html` | デッキ一覧 | 投稿デッキの閲覧・検索 |
| `/` | デッキシミュレータ v1 | 旧版UI |
| `/search` | カード検索 | カード一覧（単体ページ） |
| `/admin` | カードデータ管理 | カードメタデータの収集・編集 |
| `/ocr-admin` | OCR管理 | OCR処理の進捗管理 |
| `/ocr-run` | OCR実行 | シリーズ別OCR一括実行 |

## API エンドポイント

### カードデータ
| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/card_index` | カードインデックス一覧 |
| GET | `/api/card/<number>` | カード詳細（OCRデータ込み） |
| POST | `/api/cards/batch` | 複数カード一括取得 |
| GET | `/api/cards/search` | カード検索 |
| GET | `/api/link_index` | リンクアビリティ一覧 |
| GET | `/api/tactics_cards` | 作戦カード一覧 |

### デッキ
| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/decks` | デッキ一覧 |
| POST | `/api/decks` | デッキ投稿 |
| PUT | `/api/decks/<id>` | デッキ更新 |
| DELETE | `/api/decks/<id>` | デッキ削除（パスワード認証） |
| POST | `/api/decks/<id>/like` | いいね |
| GET | `/api/decks/<id>/comments` | コメント取得 |
| POST | `/api/decks/<id>/comments` | コメント投稿 |

## プロジェクト構成

```
abds/
├── app.py                     # Flask メインアプリケーション
├── db.py                      # DB抽象化レイヤー (Supabase / JSON)
├── logic/                     # ゲームロジックライブラリ
│   ├── constants.py           #   ゲームルール・定数
│   ├── types.py               #   型定義
│   ├── stats.py               #   ステータス計算
│   ├── buff.py                #   リンクバフ計算
│   ├── link.py                #   リンク発動判定
│   ├── ability.py             #   アビリティ処理
│   ├── terrain.py             #   地形適性
│   ├── terrain_effect.py      #   地形効果
│   ├── matchup.py             #   タイプ相性
│   ├── commander.py           #   指揮官判定
│   ├── pilot_skill.py         #   パイロットスキル
│   ├── deck_code.py           #   デッキコード生成・復元
│   ├── deck_validation.py     #   デッキバリデーション
│   └── utils.py               #   ユーティリティ
├── templates/                 # HTMLテンプレート
│   ├── index_v2.html          #   v2 デッキシミュレータ (メイン)
│   ├── decks.html             #   デッキ一覧ページ
│   ├── index.html             #   v1 デッキシミュレータ
│   ├── search.html            #   カード検索
│   ├── admin.html             #   カードデータ管理
│   ├── ocr_admin.html         #   OCR管理
│   └── ocr_run.html           #   OCR実行
├── card_ocr_cc.py             # OCR処理 (OpenAI Vision API)
├── card_ocr_claude.py         # OCR処理 (Claude API)
├── fetch_cards.py             # カードメタデータ取得
├── fetch_series_ids.py        # シリーズID取得
├── download_card_images.py    # OCR用画像ダウンロード
├── all_cards_list/            # カードJSONデータ
├── ocr_results_debug/         # OCR結果
├── requirements.txt           # Python依存パッケージ
├── Procfile                   # Render デプロイ設定
└── runtime.txt                # Pythonバージョン指定
```

## 注意事項

- OpenAI / Claude APIの利用には料金が発生します
- カード画像の著作権は権利者に帰属します
- 本アプリはカード画像をサーバーから配信していません（ブラウザキャッシュ方式）

## ライセンス

MIT License

## 制作者

**sekimiya** — [https://x.com/sekimiya](https://x.com/sekimiya)

不具合・ご要望・お気づきの点がありましたら、上記Xアカウントまでお気軽にご連絡ください。
