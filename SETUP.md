# 環境構築ガイド

ガンダムアーセナルベース カードデータ管理システムのローカル開発環境構築手順です。

## 前提条件

| ソフトウェア | バージョン | 備考 |
|---|---|---|
| Python | 3.10 以上 | Windows: [python.org](https://www.python.org/downloads/) からインストール |
| Git | 任意 | リポジトリのクローンに必要 |
| OpenAI APIキー | - | OCR機能を使用する場合のみ必要 |

## セットアップ手順

### 1. リポジトリのクローン

```bash
git clone <リポジトリURL>
cd abds
```

### 2. Python仮想環境の作成

**Windows (Git Bash / PowerShell):**

```bash
py -3 -m venv .venv
source .venv/Scripts/activate    # Git Bash
# .venv\Scripts\activate         # PowerShell / cmd
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 依存パッケージのインストール

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

インストールされるパッケージ:

| パッケージ | 用途 |
|---|---|
| flask | Webアプリケーションフレームワーク |
| requests | HTTP通信（カード画像取得等） |
| beautifulsoup4 | HTMLパース（公式サイトスクレイピング） |
| Pillow | 画像処理 |
| opencv-python | 画像処理（OCR前処理） |
| numpy | 数値計算（opencv依存） |
| gunicorn | 本番用WSGIサーバー（Heroku/Render用） |

### 4. APIキーの設定（OCR機能を使う場合のみ）

プロジェクトルートに `APIkey.txt` を作成し、OpenAI APIキーを記述します。

```bash
echo "sk-your-api-key-here" > APIkey.txt
```

> **注意:** `APIkey.txt` は `.gitignore` に登録されていないため、コミットしないよう注意してください。

### 5. アプリケーションの起動

```bash
python app.py
```

起動すると以下のURLでアクセス可能になります:

- **ローカル:** http://127.0.0.1:5001
- **LAN内:** http://<自分のIP>:5001

## 主要ページ一覧

| パス | ページ | 説明 |
|---|---|---|
| `/` | デッキシミュレータ | メイン画面。デッキ構築・シミュレーション |
| `/v2` | デッキシミュレータ v2 | 改良版UI |
| `/search` | カード検索 | カード一覧・検索 |
| `/decks` | デッキ一覧 | 保存済みデッキの管理 |
| `/summary` | デッキ分析 | デッキの詳細分析 |
| `/admin` | カードデータ管理 | カードデータの編集・管理 |
| `/ocr_admin` | OCR管理 | OCR処理の管理画面 |
| `/mobile` | モバイル版 | スマートフォン向けUI |

## プロジェクト構成

```
abds/
├── app.py                  # Flaskメインアプリケーション
├── logic/                  # ゲームロジックライブラリ
│   ├── constants.py        #   ゲームルール・定数
│   ├── types.py            #   型定義
│   ├── stats.py            #   ステータス計算
│   ├── buff.py             #   リンクバフ計算
│   ├── link.py             #   リンク発動判定
│   ├── terrain.py          #   地形適性
│   ├── matchup.py          #   タイプ相性
│   └── deck_validation.py  #   デッキバリデーション
├── templates/              # HTMLテンプレート群
├── card_ocr_cc.py          # OCR処理（OpenAI Vision API）
├── card_ocr_claude.py      # OCR処理（Claude API）
├── fetch_series_ids.py     # シリーズIDの取得
├── fetch_cards.py          # カード画像の取得
├── generate_all_cards_list.py  # カードリスト生成
├── requirements.txt        # Python依存パッケージ
├── Procfile                # Heroku/Renderデプロイ設定
├── runtime.txt             # Pythonバージョン指定
├── ocr_config.json         # OCR設定
├── decks.json              # 保存デッキデータ
├── front_cards.json        # カード表面URL
├── back_cards.json         # カード裏面URL
└── all_cards_list/         # カード個別データ（JSON）
```

## データについて

- カードデータは `all_cards_list/` ディレクトリに個別のJSONファイルとして格納
- デッキデータは `decks.json` に保存
- 外部データベースは不使用（全てファイルベース）

## トラブルシューティング

### `pip install` で UnicodeDecodeError が出る

Windows環境でcp932エンコーディングの問題が起きる場合があります。

```bash
# pipを最新版にアップグレードしてから再試行
pip install --upgrade pip
pip install -r requirements.txt
```

### ポート5001が使用中

`app.py` 末尾の `port=5001` を別のポート番号に変更してください。

### OCR機能がエラーになる

- `APIkey.txt` が存在し、有効なOpenAI APIキーが記述されていることを確認
- `ocr_config.json` の設定を確認
- OCRを使わずにデッキシミュレータだけ利用する場合、APIキーは不要です
