# 起動手順書

## 前提

- リポジトリは git worktree で2つのディレクトリに分離済み
  - `abds/` — `gh-pages` ブランチ（静的サイト）
  - `abds-main/` — `main` ブランチ（サーバーアプリ）
- Python実行は `py`（Windowsランチャー）を使用（`python` はPermission deniedになる）

## サーバー起動

### 1. メインアプリ（デッキシミュレータ）

```bash
cd C:/Users/sekimiya/workspace/abds-main
py app.py
```

- ポート: **5001**（`PORT` 環境変数で変更可）
- URL: http://localhost:5001/

### 2. OCRサーバー（OCR管理画面）

```bash
cd C:/Users/sekimiya/workspace/abds-main
py ocr_app.py
```

- ポート: **5002**（`OCR_PORT` 環境変数で変更可）
- URL一覧:
  - http://localhost:5002/admin — OCR管理トップ
  - http://localhost:5002/ocr-run — OCR実行
  - http://localhost:5002/ocr-validate — OCR検証
  - http://localhost:5002/ocr-quality — OCR品質チェック

### 両方まとめて起動（Git Bash）

```bash
cd C:/Users/sekimiya/workspace/abds-main
py app.py &
py ocr_app.py &
```

## 停止

```bash
# 個別停止
kill $(lsof -t -i:5001) 2>/dev/null
kill $(lsof -t -i:5002) 2>/dev/null

# Windows (PowerShell)
# netstat -ano | findstr :5001
# taskkill /PID <PID> /F
```

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `python` でPermission denied | `py` を使う |
| ポートが使用中 | 上記の停止手順でプロセスを終了 |
| モジュールが見つからない | `py -m pip install -r requirements.txt` |
