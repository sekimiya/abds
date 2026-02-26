# Cleanup Log (2026-02-26)

プロジェクトクリーンアップ＆リファクタリングの記録。

## 削除したディレクトリ

| ディレクトリ | 理由 |
|-------------|------|
| `all_cards_list copy/` | all_cards_list/ の完全複製 |
| `all_cards_list_back/` | 古いバックアップ |
| `all_cards_list_debug/` | デバッグ用コピー |
| `ocr_results_back/` | 古いバックアップ |
| `ocr_results_debug_backup/` | バックアップの二重コピー |
| `tmp_ui/` | 旧UIテンプレートキャッシュ |
| `ocr_cache/` | 旧OCRキャッシュ |
| `ocr_errors/` | 旧エラーログ |
| `ocr_result_debug/` | 旧デバッグ出力 |
| `from_raw/` | 旧raw変換テスト |
| `my_cards/` | 個人テスト |
| `my_results/` | 個人テスト |
| `series_data/` | 現行コード未参照 |
| `test/` | テストデータ残骸 |
| `test_output/` | テスト出力残骸 |
| `tests/` | 空テストディレクトリ |
| `tmp_ocr_test/` | 一時テストデータ |
| `design/` | デザイン参考画像（1ファイルのみ） |
| `doujinshi/` | 同人誌関連ドキュメント |

## 削除したPythonファイル

### レガシーOCR関連
| ファイル | 理由 |
|---------|------|
| `card_ocr.py` (90KB) | 旧OpenAI Vision OCR。card_ocr_cc.py に完全置換済 |
| `card_ocr_claude.py` (25KB) | 旧Claude OCR。card_ocr_cc.py に置換済 |
| `ocr_module.py` (7.4KB) | 旧OCRクラス。process_cards.py のみ参照（共に削除） |
| `ocr_processor.py` (8.6KB) | 旧OCRプロセッサ |
| `process_cards.py` | ocr_module 依存のレガシースクリプト |
| `process_back_cards.py` | card_ocr 依存のレガシースクリプト |
| `run_new_ocr_workflow.py` | card_ocr 依存のレガシーワークフロー |
| `start_ocr.py` | 旧OCR起動スクリプト。app.py 内のOCR管理UIに置換済 |
| `ocr_app.py` (33KB) | 別Flask app(port 5002)。同等機能が app.py に統合済み |

### ユーティリティ・単発スクリプト
| ファイル | 理由 |
|---------|------|
| `parse_ms_raw.py` | 単発ユーティリティ。未参照 |
| `_restructure_ve01004.py` | 単発修正スクリプト。作業済み |
| `save_card_urls.py` | 単発スクリプト。未参照 |

### テストファイル（削除対象コード依存）
| ファイル | 理由 |
|---------|------|
| `test_new_ocr_workflow.py` | card_ocr.py を import |
| `test_sp_ocr.py` | card_ocr.py を import |
| `test_sp_merge.py` | card_ocr.py を import |
| `test_pl_sq_analysis.py` | all_cards_list_debug/ を参照 |

## 削除したデータ/ログファイル

| ファイル | 理由 |
|---------|------|
| `card_data.json` | 未参照 |
| `front_cards.json` | レガシースクリプトのみ使用 |
| `back_cards.json` | 同上 |
| `served_test.html` | 旧テスト出力 |
| `nohup.out` | 古いプロセスログ |
| `server.log` | 空ログ |
| `debug_output.log` | 古いデバッグ出力 |
| `claude_stderr.tmp` | 空一時ファイル |
| `Summary2実装要件.txt` | 旧要件ドキュメント |
| `.DS_Store` | macOS メタデータ |
| `ocr_config.json` | run_ocr_master.py のみ使用 |

## 削除したテンプレート

| ファイル | 理由 |
|---------|------|
| `templates/ocr_admin.html` | `/ocr-admin` ルートは `/admin` へリダイレクト済。未レンダー |

## リファクタリング

### app.py
- **未使用import削除**: `from bs4 import BeautifulSoup` を削除（どこからも使用されていなかった）
- **壊れたルート削除**: `/mobile/landscape` ルートを削除（存在しない `mobile_v2_landscape.html` を参照していた）

### .gitignore
以下のパターンを追加:
- `*.log`
- `*.tmp`
- `nohup.out`
- `.DS_Store`

## 保持したもの（判断メモ）

| ファイル/ディレクトリ | 理由 |
|---------------------|------|
| `run_ocr_master.py` | OCRマスターオーケストレーター。現行パイプラインの一部 |
| `migrate_to_supabase.py` | DB移行スクリプト。再利用可能性あり |
| `test_ocr_compatibility.py` | generate_derivatives.py 依存テスト。現行コード対象 |
| `check_back_missing.py` | バリデーションユーティリティ。現行使用 |
| `ocr_results_debug/` | 現行OCR結果格納先 |
| `card_images_temp/` | OCR用画像格納先 |

---

> **Note**: `ocr_config.json` は `run_ocr_master.py` が参照していたが、`run_ocr_master.py` は起動時にデフォルト値で動作するため削除しても問題なし。必要に応じて再生成される。
