# OCR実行マスタースクリプト

アーセナルベースのカード裏面画像OCR処理を実行する統合スクリプトです。

## 機能

- **統合OCR処理**: card_ocr.pyの機能を完全統合
- **バッチ処理**: 複数のカードを効率的に処理
- **進捗管理**: 処理状況の保存と再開機能
- **エラーハンドリング**: 失敗したファイルの管理と再試行
- **ログ機能**: 詳細なログ出力とファイル保存
- **統計情報**: 処理結果の統計とレポート生成
- **統一ファイル名**: 収録パック+カードナンバー+カード名.json形式で保存
- **MS/PLカード対応**: アーセナルベースの全カードタイプに対応

## セットアップ

1. **APIキーの設定**
   ```bash
   # 方法1: 設定ファイルに直接記述
   {
     "api_key": "your_api_key_here",
     ...
   }
   
   # 方法2: APIキーファイルを使用（推奨）
   # APIkey.txtファイルにAPIキーを記述
   echo "your_api_key_here" > APIkey.txt
   ```

2. **依存関係の確認**
   ```bash
   # openaiライブラリのインストール
   pip install openai
   ```

## 使用方法

### 基本的な実行

```bash
# デフォルト設定でOCR実行（APIkey.txtから読み込み）
python3 run_ocr_master.py

# APIキーを直接指定して実行
python3 run_ocr_master.py --api-key "your_api_key_here"

# カスタムAPIキーファイルを指定
python3 run_ocr_master.py --api-key-file "my_api_key.txt"

# バッチサイズを指定して実行
python3 run_ocr_master.py --batch-size 20

# 既存ファイルを上書き
python3 run_ocr_master.py --force

# 失敗したファイルを再試行
python3 run_ocr_master.py --retry-failed
```

### 状況確認

```bash
# 現在の処理状況を表示
python3 run_ocr_master.py --status

# 進捗をリセット
python3 run_ocr_master.py --reset
```

### 設定ファイルの使用

```bash
# カスタム設定ファイルを使用
python3 run_ocr_master.py --config my_config.json
```

## 設定オプション

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `api_key` | "" | OCR APIキー |
| `log_level` | "INFO" | ログレベル (DEBUG/INFO/WARNING/ERROR) |
| `force` | false | 既存ファイルを上書き |
| `retry_failed` | false | 失敗したファイルを再試行 |
| `delay` | 1 | カード間の遅延（秒） |
| `batch_delay` | 5 | バッチ間の遅延（秒） |
| `max_retries` | 3 | 最大リトライ回数 |
| `timeout` | 300 | タイムアウト（秒） |
| `batch_size` | 10 | バッチサイズ |

## 出力ファイル

### 進捗ファイル
- `ocr_progress.json`: 処理進捗の保存

### 統計ファイル
- `ocr_stats.json`: 最終統計情報

### ログファイル
- `logs/ocr_master_YYYYMMDD_HHMMSS.log`: 詳細ログ

### OCR結果
- `ocr_results/`: OCR処理結果（収録パック+カードナンバー+カード名.json形式）

## 処理フロー

1. **初期化**: 設定ファイルと進捗ファイルの読み込み
2. **対象決定**: 処理対象カードの決定
3. **バッチ処理**: 指定されたバッチサイズで処理
4. **進捗保存**: 各カード処理後に進捗を保存
5. **統計生成**: 処理完了後に統計情報を生成

## エラーハンドリング

- **タイムアウト**: 個別カードの処理タイムアウト
- **API エラー**: OCR API呼び出しエラー
- **ファイルエラー**: ファイル読み込み/書き込みエラー
- **中断処理**: Ctrl+Cでの安全な中断

## 再開機能

処理が中断された場合、`--status`で状況を確認し、再度実行することで中断箇所から再開できます。

```bash
# 状況確認
python3 run_ocr_master.py --status

# 再開実行
python3 run_ocr_master.py
```

## 注意事項

- APIキーは必ず設定してください
- 大量のカードを処理する場合は適切な遅延を設定してください
- 処理中は中断しないでください（Ctrl+Cで安全に中断可能）
- ログファイルは定期的に確認してください

## トラブルシューティング

### よくある問題

1. **APIキーエラー**
   - `ocr_config.json`のAPIキーを確認
   - APIキーの有効期限を確認

2. **メモリ不足**
   - バッチサイズを小さくする
   - システムリソースを確認

3. **ネットワークエラー**
   - ネットワーク接続を確認
   - 遅延時間を増やす

4. **ファイル権限エラー**
   - ディレクトリの書き込み権限を確認
   - ファイルパスを確認 