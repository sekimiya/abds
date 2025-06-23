# SPデータの分離とマージ処理の改善

## 概要

OCR結果のJSON生成ルールを見直し、SP関連のデータを完全に分離して処理するように改善しました。これにより、カードのOCR時にはSPのJSON構造を渡さず、別途処理したSPデータを後でマージする仕組みになりました。

## 主な変更点

### 1. カードOCRプロンプトの修正

- **MSカードのプロンプト**から`special_attack`フィールドを削除
- **PLカードのプロンプト**を追加（従来は含まれていませんでした）

### 2. OCR処理フローの改善

#### 従来の処理フロー
1. カードのOCR処理で`special_attack`フィールドを検出
2. MSカードの場合、SP部分を切り取って詳細OCRを実行
3. SP詳細OCR結果を元のJSONの`special_attack`フィールドに上書き
4. SP詳細OCR結果を別ファイルとして保存

#### 新しい処理フロー
1. カードのOCR処理（SPデータは含まれない）
2. **MSカードの場合のみ**、SP部分を切り取って詳細OCRを実行
3. SP詳細OCR結果を別ファイル（`_sp.json`）として保存
4. SP生OCR結果を別ファイル（`_sp_raw.json`）として保存
5. **後でSPデータをカードのJSONにマージ**（オプション）

**注意**: PLカードにはSPが存在しないため、SP処理は実行されません。

### 3. 新しい関数の追加

#### `merge_sp_data_to_card_results(results_dir='ocr_results')`
- SPデータをカードのOCR結果にマージする関数
- **MSカードでSPデータが存在しない場合**のみ`sp_ocr_type: 'not_available'`フラグを追加
- **PLカード**の場合はSP関連フィールドを追加しない（SPが存在しないため）
- マージ処理の詳細なログを出力

#### `merge_all_card_data(results_dir='ocr_results')`
- **すべてのカードデータを統一的にマージする関数**
- SP詳細データ、SP生データ、カード基本データを1つのファイルに統合
- デバッグ・分析に必要なすべての情報を含む
- 統合処理の詳細なログを出力

### 4. コマンドラインオプションの追加

```bash
# SPデータのマージを含むOCR処理
python card_ocr.py --merge-sp

# すべてのデータを統合マージするOCR処理
python card_ocr.py --merge-all

# 通常のOCR処理（SPデータは別ファイルのみ）
python card_ocr.py
```

## ファイル構造

### 生成されるファイル

```
ocr_results/
├── FQ01_FQ01-001_ガンダム試作3号機.json          # カードのOCR結果（SPデータなし）
├── FQ01_FQ01-001_ガンダム試作3号機_sp.json       # SP詳細OCR結果
├── FQ01_FQ01-001_ガンダム試作3号機_sp_raw.json   # SP生OCR結果
└── sp_images/
    └── FQ01-001_ガンダム試作3号機_sp.jpg         # SP部分の切り取り画像
```

### マージ後のファイル

```
ocr_results/
├── FQ01_FQ01-001_ガンダム試作3号機.json          # カードのOCR結果（SPデータあり）
├── FQ01_FQ01-001_ガンダム試作3号機_sp.json       # SP詳細OCR結果（元ファイル）
├── FQ01_FQ01-001_ガンダム試作3号機_sp_raw.json   # SP生OCR結果（元ファイル）
└── sp_images/
    └── FQ01-001_ガンダム試作3号機_sp.jpg         # SP部分の切り取り画像
```

## 使用方法

### 1. 基本的なOCR処理

```bash
python card_ocr.py --api-key APIkey.txt
```

この場合、SPデータは別ファイルとして保存され、カードのJSONには含まれません。

### 2. SPデータのマージを含むOCR処理

```bash
python card_ocr.py --api-key APIkey.txt --merge-sp
```

この場合、OCR処理後にSPデータがカードのJSONにマージされます。

### 3. すべてのデータを統合マージするOCR処理

```bash
python card_ocr.py --api-key APIkey.txt --merge-all
```

この場合、OCR処理後にすべてのデータ（SP詳細、SP生データ、カード基本データ）が1つのファイルに統合されます。

### 4. 既存のOCR結果にSPデータをマージ

```python
from card_ocr import merge_sp_data_to_card_results, merge_all_card_data

# SPデータのみをマージ
merge_sp_data_to_card_results('ocr_results')

# すべてのデータを統合マージ
merge_all_card_data('ocr_results')
```

## テスト

テストスクリプトを実行して、SPデータのマージ処理を確認できます：

```bash
python test_sp_merge.py
```

## メリット

1. **データの分離**: SPデータとカードデータが明確に分離される
2. **柔軟性**: SPデータのマージを任意のタイミングで実行可能
3. **保守性**: SP関連の処理が独立しているため、修正が容易
4. **再利用性**: SPデータを他の用途でも利用可能
5. **エラーハンドリング**: SP処理の失敗がカード処理に影響しない
6. **統合性**: すべてのデータを1つのファイルに統合可能（`--merge-all`オプション）
7. **デバッグ性**: 生OCR結果も含めて統合することで、デバッグ・分析が容易

## 注意事項

- SPデータのマージは**オプション**です
- マージしない場合、カードのJSONには`special_attack`フィールドが含まれません
- **MSカードでSPデータが存在しない場合**のみ`sp_ocr_type: 'not_available'`フラグが追加されます
- **PLカード**にはSPが存在しないため、SP関連フィールドは追加されません
- 既存のOCR結果がある場合は、`--merge-sp`オプションで後からマージできます

# カードOCRとSPデータ統合マージ機能

## 概要

このシステムは、カード画像のOCR処理とSP（スペシャルアタック）データの統合マージ機能を提供します。MSカードのSP部分を自動的に切り取り、詳細なOCR処理を行い、結果を統合して保存します。

**重要**: デフォルトで統合マージ形式のJSONが出力されます。特別なオプション指定は不要です。

## 主な機能

### 1. カードOCR処理
- `all_cards_list`ディレクトリのJSONファイルから裏面画像を読み込み
- OpenAI APIを使用したOCR処理
- MSカードのSP部分を自動検出・切り取り
- SP部分の詳細OCR処理
- **デフォルトで統合マージ形式のJSONを出力**

### 2. SPデータ処理
- MSカードのSP部分を自動的に切り取り
- SP部分の詳細OCR処理
- SP生OCR結果の保存
- PLカードにはSP処理を適用しない

### 3. データマージ機能
- **デフォルト統合マージ**: すべてのデータを統一的にマージして出力
- **SPデータマージ**: SP詳細・生データを基本カードデータにマージ（既存結果に対して）
- **手動統合マージ**: すべてのデータを統一的にマージ（既存結果に対して）

## 使用方法

### 基本的なOCR処理（デフォルトで統合マージ形式）
```bash
python card_ocr.py APIkey.txt
```

### カスタムディレクトリ指定
```bash
python card_ocr.py APIkey.txt --cards-dir custom_cards --results-dir custom_results
```

### 既存のOCR結果に対してSPデータマージ
```bash
python card_ocr.py APIkey.txt --merge-sp
```

### 既存のOCR結果に対して統合マージ
```bash
python card_ocr.py APIkey.txt --merge-all
```

## 出力ファイル構造

### メインOCR結果（統合マージ形式）
```
{シリーズ名}_{カード番号}_{カード名}.json
```

### SP詳細OCR結果
```
{シリーズ名}_{カード番号}_{カード名}_sp.json
```

### SP生OCR結果
```
{シリーズ名}_{カード番号}_{カード名}_sp_raw.json
```

### 手動統合マージ結果
```
{シリーズ名}_{カード番号}_{カード名}_all.json
```

## デフォルト出力の統合マージ結果構造

```json
{
  "card_info": {
    "card_number": "MS-001",
    "card_name": "テストMSカード",
    "series": "テストシリーズ",
    "type": "MS",
    "name": "テストMSカード",
    "cost": "3",
    "power": "2000",
    "attribute": "光",
    "rarity": "R",
    "effect": "テスト効果",
    "front_image_url": "http://example.com/front.jpg",
    "back_image_url": "http://example.com/back.jpg"
  },
  "sp_data": {
    "has_sp_data": true,
    "sp_detail": {
      "sp_info": {
        "type": "SQUAD SP",
        "name": "バズーカ連射",
        "partner": null,
        "target": "単体（敵）",
        "attack_type": "貫通（敵）",
        "range": 3,
        "squad_sp": true,
        "united_sp": false
      },
      "power": {
        "normal": 2500,
        "squad": 3500,
        "united": null
      },
      "descriptions": {
        "all_description": "敵1体に2500ダメージを与える。/味方1体と連携時、3500ダメージを与える。",
        "normal_description": "敵1体に2500ダメージを与える。",
        "squad_description": "味方1体と連携時、3500ダメージを与える。",
        "united_description": null
      },
      "metadata": {
        "note": null,
        "ocr_confidence": 0.95,
        "processing_notes": null
      }
    },
    "sp_raw": null
  },
  "source_data": {
    "original": "data"
  },
  "merge_info": {
    "merge_timestamp": "2024-01-01T12:00:00",
    "merge_version": "1.0",
    "card_error": null,
    "card_warning": null
  }
}
```

## フィールド説明

### 基本フィールド
- `card_info`: カードの基本情報
- `sp_data`: SP関連データ
- `source_data`: 元のall_cards_listデータ
- `merge_info`: マージ情報

### カード情報フィールド
- `card_number`: カード番号
- `card_name`: カード名
- `series`: シリーズ名
- `type`: カードタイプ（MS/PL）
- `name`: カード名（OCR結果）
- `cost`: コスト
- `power`: パワー
- `attribute`: 属性
- `rarity`: レアリティ
- `effect`: 効果
- `front_image_url`: 表面画像URL
- `back_image_url`: 裏面画像URL

### SP関連フィールド
- `has_sp_data`: SPデータの有無
- `sp_detail`: SP詳細OCR結果
- `sp_raw`: SP生OCR結果

### マージ情報フィールド
- `merge_timestamp`: マージ実行時刻
- `merge_version`: マージ機能バージョン
- `card_error`: カードOCRエラー情報
- `card_warning`: カードOCR警告情報

## 処理フロー

1. **OCR処理開始**
   - `all_cards_list`ディレクトリのJSONファイルを読み込み
   - 裏面画像URLを取得

2. **基本OCR処理**
   - カード裏面のOCR処理
   - MSカードかどうかを判定

3. **SP処理（MSカードのみ）**
   - SP部分を自動切り取り
   - SP詳細OCR処理
   - SP生OCR結果保存

4. **統合マージ形式で保存（デフォルト）**
   - すべてのデータを統合
   - 統合マージ形式のJSONで保存

## メリット

### 1. シンプルな使用
- 特別なオプション指定が不要
- デフォルトで統合マージ形式を出力

### 2. データ統合
- 基本カードデータ、SP詳細、SP生データを1つのファイルに統合
- データの関連性が明確

### 3. エラーハンドリング
- 破損ファイルの適切なスキップ
- エラー情報の保持

### 4. バージョン管理
- マージタイムスタンプとバージョン情報の記録
- データの追跡可能性

## テスト

テストスクリプト`test_sp_merge.py`を使用して機能をテストできます：

```bash
python test_sp_merge.py
```

テスト内容：
- SPデータマージ機能
- 統合マージ機能
- エラーハンドリング
- 各種カードタイプ（MS/PL）の処理

## 注意事項

1. **API制限**: OpenAI APIの制限に注意
2. **ファイル名**: 特殊文字を含むファイル名は自動的にサニタイズ
3. **SP処理**: PLカードにはSP処理を適用しない
4. **エラー処理**: 破損ファイルは適切にスキップされる
5. **デフォルト出力**: 統合マージ形式のJSONがデフォルトで出力される 