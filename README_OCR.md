# OCR機能の使用方法

## 概要
OCR機能は、Webアプリケーションから分離され、必要な時だけ実行される独立したプロセスです。
既存のOCR結果がある場合は自動的にスキップし、効率的に処理を行います。

## ファイル構成
- `ocr_processor.py` - OCR処理を実行するスクリプト
- `ocr_module.py` - OCR機能のコアモジュール
- `card_list.json` - 生成されたカードリスト（出力ファイル）
- `ocr_results/` - 個別のOCR結果を保存するディレクトリ

## 使用方法

### 1. OCR処理の実行
```bash
# OCR処理のみ実行（既存結果はスキップ）
python ocr_processor.py ocr

# OCR処理（強制再生成モード）
python ocr_processor.py ocr-force

# カードリスト生成のみ実行
python ocr_processor.py generate

# OCR処理とカードリスト生成を両方実行
python ocr_processor.py both

# OCR処理（強制再生成）とカードリスト生成を両方実行
python ocr_processor.py both-force
```

### 2. Webアプリケーションの起動
```bash
python app.py
```

## 処理の流れ

### ステップ1: OCR処理
1. サイトからカード画像のURLを取得
2. 既存のOCR結果ファイルをチェック
3. 未処理の画像のみOCR処理を実行
4. 結果を`ocr_results/`ディレクトリに保存

### ステップ2: カードリスト生成
1. カードURLとOCR結果を統合
2. `card_list.json`ファイルを生成

### ステップ3: Webアプリケーション
1. `card_list.json`からカードデータを読み込み
2. ユーザーに表示

## 新機能

### 1. 自動スキップ機能
- 既存のOCR結果ファイルがある場合は自動的にスキップ
- 処理時間を大幅に短縮
- 重複処理を防止

### 2. 強制再生成オプション
- `ocr-force`または`both-force`で既存結果を上書き
- OCR精度の改善やエラー修正時に使用

### 3. 詳細な処理結果表示
- スキップ件数、処理完了件数、失敗件数を表示
- 処理状況をリアルタイムで確認可能

## メリット

1. **パフォーマンス向上**
   - Webアプリケーションの起動が高速
   - サイトアクセス時にOCR処理が実行されない
   - 既存結果の自動スキップで処理時間短縮

2. **効率的な処理**
   - OCR処理は必要な時だけ実行
   - キャッシュ機能により重複処理を防止
   - 増分処理で新規カードのみ処理

3. **保守性の向上**
   - OCR処理とWebアプリケーションが分離
   - 独立してデバッグ・修正可能
   - 強制再生成で柔軟な処理が可能

## 注意事項

- `APIKey.txt`ファイルが必要です
- OCR処理には時間がかかります（カード数に依存）
- 初回実行時は`ocr_processor.py both`を実行してください
- 強制再生成時は既存のOCR結果が上書きされます

## トラブルシューティング

### card_list.jsonが見つからない場合
```bash
python ocr_processor.py generate
```

### OCR処理が失敗する場合
1. `APIKey.txt`の存在を確認
2. インターネット接続を確認
3. 画像URLのアクセス可能性を確認

### 既存のOCR結果を再生成したい場合
```bash
python ocr_processor.py ocr-force
```

### 特定のカードのOCR結果を確認したい場合
```bash
ls ocr_results/
cat ocr_results/FQ01-001_ocr.json
``` 