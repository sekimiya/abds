# セキュリティレビュー (2026-02-25)

## CRITICAL（公開前に必ず対応）

### 1. APIキー・シークレットの漏洩リスク

| ファイル | 内容 | `.gitignore` | Git履歴 |
|----------|------|:---:|:---:|
| `.env` | Supabase URL + Key | 記載あり | 要確認 |
| `APIkey.txt` | OpenAI APIキー | 記載あり | **履歴に残っている可能性大** |

- `.gitignore`に入っていても、過去にcommitされていればgit履歴に残る
- リポジトリを公開した瞬間に全世界から閲覧可能になる

**対応:**
1. 今すぐAPIキーをローテーション（OpenAI / Supabase両方）
2. git履歴からの除去（`git filter-repo` or BFG Repo-Cleaner）
3. もしくは新しいリポジトリを作り直して公開用にする（履歴を引き継がない）

---

### 2. 管理エンドポイントが認証なしで全公開

以下のルートに認証が一切ない。誰でもアクセス可能：

| ルート | メソッド | リスク |
|--------|----------|--------|
| `/admin` | GET | 管理画面が丸見え |
| `/api/admin/collect` | POST | 外部から全カードスクレイピングを起動される |
| `/api/admin/collect/status` | GET | 収集ステータスが外部から見える |
| `/api/admin/stats` | GET | 内部統計情報の漏洩 |
| `/api/admin/cards` | GET | カードデータの列挙 |
| `/ocr-run` | GET | OCR管理画面が丸見え |
| `/api/ocr-run/start` | POST | **外部からOCR処理を起動される（OpenAI API消費＝課金）** |
| `/api/ocr-run/stop` | POST | 外部からOCR処理を停止される |
| `/api/ocr-run/status` | GET | OCRステータスが外部から見える |
| `/api/ocr-run/series-stats` | GET | 内部統計情報の漏洩 |
| `/api/ocr-admin/stats` | GET | 内部統計情報の漏洩 |
| `/api/ocr-admin/cards` | GET | カードデータの列挙 |
| `/api/ocr-admin/card/<number>` | GET | カード詳細の列挙 |
| `/api/cache/clear` | POST | 外部からキャッシュを消去される |

特に `/api/ocr-run/start` は OpenAI APIを叩く処理のため、第三者に無限に課金させられる危険がある。

---

### 3. パスワードハッシュが脆弱

`db.py` で SHA-256 をソルトなしで使用：
```python
hashlib.sha256(pw.encode('utf-8')).hexdigest()
```
- レインボーテーブル攻撃に対して脆弱
- `bcrypt` や `werkzeug.security.generate_password_hash` に変更すべき

---

## HIGH（公開時に対応推奨）

### 4. `__pycache__` / `.pyc` がGit追跡されている

`.gitignore`に記載があっても、既にtrackされたファイルは無視されない。
```bash
git rm -r --cached __pycache__/ logic/__pycache__/
```

### 5. デバッグ・バックアップ・一時ファイルが大量に存在

公開リポジトリに含めるべきでないもの：
```
debug_output.log            # デバッグログ
server.log                  # サーバーログ
all_cards_list copy/        # バックアップ
all_cards_list_back/        # バックアップ
all_cards_list_debug/       # デバッグ用
ocr_results_back/           # バックアップ
ocr_results_debug_backup/   # バックアップ
card_images_temp/           # 一時ファイル
from_raw/                   # 中間ファイル
tmp_ui/                     # 一時UI
doujinshi/                  # 用途不明
test_*.py                   # 開発用テストスクリプト
_restructure_*.py           # 開発用ユーティリティ
ocr_cc_progress.json        # 内部処理状態
ocr_config.json             # 内部設定
```

### 6. Flask セキュリティ設定の不足

- `SECRET_KEY` 未設定 → セッション偽装のリスク
- CSRF保護なし
- セキュリティヘッダなし（CSP, X-Frame-Options, X-Content-Type-Options等）
- レートリミットなし → DoS攻撃に対して無防備

---

## MEDIUM

### 7. Supabase RLS（Row Level Security）の確認

`.env`のキーは `anon`キー（公開前提）だが、Supabaseダッシュボードで
RLSが有効になっているか確認が必要。
無効だとanonキーでDBの全テーブルを読み書きできてしまう。

### 8. ファイル配信のパストラバーサルリスク

`/card_images/<path:filename>` 等のルートでファイル名バリデーションが不足。
`send_from_directory` の保護はあるが、追加のバリデーション推奨。

### 9. `host='0.0.0.0'` でのバインド

`app.run(debug=debug, host='0.0.0.0', port=port)` で全インターフェースに公開。
本番環境ではリバースプロキシ（nginx等）の背後に置くべき。

---

## LOW

### 10. 大きなJSONファイル

- `front_cards.json` (312KB)
- `back_cards.json` (315KB)
- Git LFSの利用またはビルド時生成を検討

### 11. `.DS_Store` が存在

macOSメタデータファイル。`.gitignore`に追加すべき。

---

## 推奨アクション（優先順）

| # | 対応 | 理由 |
|---|------|------|
| 1 | OpenAI / Supabase のキーを即座にローテーション | 既にgit履歴に入っている可能性 |
| 2 | git履歴をクリーン化 or 新規リポジトリで公開 | 秘密情報の完全除去 |
| 3 | 管理系エンドポイントに認証を追加 | 第三者による操作・課金の防止 |
| 4 | 不要ファイルを`.gitignore`に追加 + `git rm --cached` | 不要情報の非公開化 |
| 5 | パスワードハッシュを bcrypt 等に変更 | セキュリティ強化 |
| 6 | Flask セキュリティ設定（SECRET_KEY, CSRF, ヘッダ） | 基本的な防御 |
| 7 | レートリミット導入（flask-limiter等） | DoS対策 |
| 8 | Supabase RLS有効化の確認 | DB保護 |

---

## 公開方法の推奨

最も安全な方法: **新しいリポジトリを作って公開用ファイルだけをコピーし、クリーンな状態で公開する。**
これによりgit履歴に残った秘密情報を気にする必要がなくなる。
