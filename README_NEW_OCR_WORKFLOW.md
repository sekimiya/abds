# 新しい3段階OCRワークフロー

このドキュメントでは、OCRロジック全体を見直した新しい3段階ワークフローの使用方法を説明します。

## 概要

新しいワークフローは以下の3段階で構成されています：

1. **すべてのカードの基本OCRを実行** - SP以外のOCR結果をJsonで保存
2. **MSカードを抽出** - 識別結果からMSカードを抽出
3. **MSカードにSPのOCRフローを適用** - 結果をJsonで保存

## 従来のワークフローとの違い

### 従来のワークフロー
- カードごとに基本OCRとSP OCRを同時実行
- 処理が複雑で、エラーが発生しやすい
- 結果の管理が困難

### 新しいワークフロー
- 段階的に処理を実行
- 各段階で結果を保存
- エラーハンドリングが改善
- 処理の追跡が容易

## 使用方法

### 1. 基本的な実行

```bash
python3 card_ocr.py
```

### 2. カスタムディレクトリを指定

```bash
python3 card_ocr.py --inputdir my_cards --outputdir my_results
```

### 3. 簡単実行スクリプトを使用

```bash
python3 run_new_ocr_workflow.py
```

### 4. 簡単実行スクリプトでカスタムディレクトリを指定

```bash
python3 run_new_ocr_workflow.py --inputdir my_cards --outputdir my_results
```

## 引数

- `--inputdir`: 入力カードリストディレクトリ（デフォルト: `all_cards_list`）
- `--outputdir`: OCR結果保存ディレクトリ（デフォルト: `ocr_results`）

## 出力ファイル構造

### 段階1: 基本OCR結果
```
ocr_results/
├── シリーズ名_カード番号_カード名_basic.json
├── シリーズ名_カード番号_カード名_basic.json
└── ...
```

### 段階2: MSカード抽出
- 基本OCR結果からMSカードを自動抽出
- 抽出結果はコンソールに表示

### 段階3: SP OCR結果
```
ocr_results/
├── シリーズ名_カード番号_カード名_sp_raw.json    # SP生データ
├── シリーズ名_カード番号_カード名_sp.json         # SPパース済みデータ
├── シリーズ名_カード番号_カード名_sp_raw.json
├── シリーズ名_カード番号_カード名_sp.json
└── ...
```

## ファイル形式

### 基本OCR結果（_basic.json）
```json
{
  "card_number": "MS-001",
  "card_name": "テストMSカード",
  "series": "テストシリーズ",
  "front_image_url": "https://example.com/front.jpg",
  "back_image_url": "https://example.com/back.jpg",
  "ocr_data": {
    "type": "MS",
    "card_id": "MS-001",
    "name": "テストMSカード",
    "model": "テストモデル",
    "cost": 3,
    "category": "近距離",
    "pilot": "テストパイロット",
    "stats": {
      "height": "18.0m",
      "weight": "50.0t",
      "mobility": 200,
      "ranged_attack": 150,
      "melee_attack": 250,
      "hp": 300
    },
    "terrain_compatibility": {
      "ground": "A",
      "space": "B",
      "desert": "C",
      "water": "D"
    },
    "weapon": {
      "main": {
        "name": "ビームソード",
        "range": 1,
        "type": "近距離"
      },
      "sub": {
        "name": "ビームライフル",
        "range": 3,
        "type": "遠距離"
      }
    },
    "ms_ability": {
      "name": "テストアビリティ",
      "type": "常時",
      "range": 0,
      "cost": 0,
      "description": "テスト効果"
    },
    "link_ability": [
      {
        "name": "テストリンク",
        "condition": "テスト条件",
        "effect": "テスト効果"
      }
    ],
    "impact_area": {
      "type": "circular",
      "radius": 1,
      "centered": true
    },
    "illustrator": "テストイラストレーター"
  },
  "ocr_timestamp": "2024-01-01T00:00:00",
  "ocr_type": "basic"
}
```

### SP生データ（_sp_raw.json）
```json
{
  "sp_info": {
    "type": "normal",
    "name": "テストSP攻撃",
    "partner": null,
    "target": "単体（敵）",
    "attack_type": "貫通（敵）",
    "range": 2,
    "squad_sp": false,
    "united_sp": false
  },
  "power": {
    "normal": 3000,
    "squad": null,
    "united": null
  },
  "descriptions": {
    "all_description": "敵単体に貫通攻撃でダメージを与える。",
    "normal_description": "敵単体に貫通攻撃でダメージを与える。",
    "squad_description": null,
    "united_description": null
  },
  "metadata": {
    "note": null,
    "ocr_confidence": 0.9,
    "processing_notes": null
  }
}
```

### SPパース済みデータ（_sp.json）
```json
{
  "sp_info": {
    "type": "normal",
    "name": "テストSP攻撃",
    "partner": null,
    "target": "単体（敵）",
    "attack_type": "貫通（敵）",
    "range": 2,
    "squad_sp": false,
    "united_sp": false
  },
  "power": {
    "normal": 3000,
    "squad": null,
    "united": null
  },
  "descriptions": {
    "all_description": "敵単体に貫通攻撃でダメージを与える。",
    "normal_description": "敵単体に貫通攻撃でダメージを与える。",
    "squad_description": null,
    "united_description": null
  },
  "metadata": {
    "note": null,
    "ocr_confidence": 0.9,
    "processing_notes": null
  },
  "card_number": "MS-001",
  "card_name": "テストMSカード",
  "series": "テストシリーズ",
  "sp_ocr_timestamp": "2024-01-01T00:00:00",
  "sp_ocr_type": "detailed"
}
```

## テスト

新しいワークフローをテストするには：

```bash
python test_new_ocr_workflow.py
```

このテストスクリプトは：
- モックデータを使用してワークフローをテスト
- 各段階の処理を検証
- 出力ファイルの構造を確認

## エラーハンドリング

### APIクォータエラー
- APIクォータの上限に達した場合、処理を停止
- 対処法をコンソールに表示

### ファイル処理エラー
- 破損ファイルをスキップ
- エラー情報をログに記録

### OCR結果パースエラー
- パースに失敗した場合、エラーを記録
- 処理を継続

## メリット

1. **段階的処理**: 各段階で結果を保存するため、途中でエラーが発生しても再開可能
2. **明確な分離**: 基本OCRとSP OCRが分離されているため、処理が理解しやすい
3. **効率的な処理**: MSカードのみにSP OCRを適用するため、処理時間を短縮
4. **追跡可能性**: 各段階の結果が保存されるため、処理の追跡が容易
5. **エラー耐性**: 各段階でエラーハンドリングが改善

## 注意事項

- 新しいワークフローを使用する場合は `--new-workflow` オプションを指定
- 従来のワークフローは引き続き利用可能
- 出力ディレクトリは処理開始時にクリーンアップされる
- APIキーは `APIkey.txt` ファイルから読み込まれる 