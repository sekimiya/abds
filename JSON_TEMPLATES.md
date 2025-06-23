# JSONテンプレート集

このドキュメントでは、カードOCRシステムで生成される各種JSONファイルの構造を説明します。

## 1. 基本カードOCR結果

### MSカード（SPあり）
```json
{
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
  "front": {
    "image_url": "http://example.com/front.jpg"
  },
  "back": {
    "image_url": "http://example.com/back.jpg"
  },
  "source_data": {
    "original": "data"
  }
}
```

### MSカード（SPなし）
```json
{
  "card_number": "MS-002",
  "card_name": "テストMSカード2",
  "series": "テストシリーズ",
  "type": "MS",
  "name": "テストMSカード2",
  "cost": "2",
  "power": "1500",
  "attribute": "闇",
  "rarity": "C",
  "effect": "テスト効果2",
  "front": {
    "image_url": "http://example.com/front2.jpg"
  },
  "back": {
    "image_url": "http://example.com/back2.jpg"
  },
  "source_data": {
    "original": "data2"
  }
}
```

### PLカード
```json
{
  "card_number": "PL-001",
  "card_name": "テストPLカード",
  "series": "テストシリーズ",
  "type": "PL",
  "name": "テストPLカード",
  "cost": "1",
  "power": "1000",
  "attribute": "無",
  "rarity": "UC",
  "effect": "PLテスト効果",
  "front": {
    "image_url": "http://example.com/pl_front.jpg"
  },
  "back": {
    "image_url": "http://example.com/pl_back.jpg"
  },
  "source_data": {
    "original": "pl_data"
  }
}
```

## 2. SP詳細OCR結果（新構造）

```json
{
  "card_info": {
    "card_number": "MS-001",
    "card_name": "テストMSカード",
    "series": "テストシリーズ",
    "front_image_url": "http://example.com/front.jpg",
    "back_image_url": "http://example.com/back.jpg"
  },
  "sp_data": {
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
  "ocr_info": {
    "sp_ocr_type": "detailed",
    "sp_image_path": "sp_images/MS-001_テストMSカード_sp.jpg",
    "ocr_timestamp": "2024-01-01T12:00:00",
    "source_data": {
      "original": "data"
    }
  }
}
```

## 3. SP生OCR結果（新構造）

```json
{
  "card_info": {
    "card_number": "MS-001",
    "card_name": "テストMSカード",
    "series": "テストシリーズ",
    "sp_image_path": "sp_images/MS-001_テストMSカード_sp.jpg"
  },
  "ocr_info": {
    "sp_ocr_type": "raw",
    "ocr_timestamp": "2024-01-01T12:00:00",
    "raw_ocr_result": "生のOCR結果テキスト",
    "parsed_sp_data": {
      "sp_info": {
        "type": "SQUAD SP",
        "name": "バズーカ連射"
      },
      "power": {
        "normal": 2500,
        "squad": 3500
      }
    }
  }
}
```

## 4. 統合マージ結果（新構造）

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
    "sp_raw": {
      "sp_ocr_type": "raw",
      "ocr_timestamp": "2024-01-01T12:00:00",
      "raw_ocr_result": "生のOCR結果テキスト",
      "parsed_sp_data": {
        "sp_info": {
          "type": "SQUAD SP",
          "name": "バズーカ連射"
        },
        "power": {
          "normal": 2500,
          "squad": 3500
        }
      }
    }
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

## 5. エラー結果

```json
{
  "error": "API呼び出し失敗の詳細",
  "card_number": "MS-001",
  "card_name": "テストMSカード",
  "series": "テストシリーズ",
  "front": {
    "image_url": "http://example.com/front.jpg"
  },
  "back": {
    "image_url": "http://example.com/back.jpg"
  },
  "source_data": {
    "original": "data"
  }
}
```

## フィールド説明

### 基本カード情報
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

### SP情報（新構造）
- `sp_info.type`: SPタイプ（"normal", "SQUAD SP", "UNITED SP"）
- `sp_info.name`: SP名
- `sp_info.partner`: 連携相手（UNITED SPのみ）
- `sp_info.target`: 攻撃対象
- `sp_info.attack_type`: 攻撃種別
- `sp_info.range`: 射程
- `sp_info.squad_sp`: SQUAD SPフラグ
- `sp_info.united_sp`: UNITED SPフラグ

### SP威力情報
- `power.normal`: 通常SP威力
- `power.squad`: SQUAD SP威力
- `power.united`: UNITED SP威力

### SP説明情報
- `descriptions.all_description`: 全説明文
- `descriptions.normal_description`: 通常SP説明
- `descriptions.squad_description`: SQUAD効果説明
- `descriptions.united_description`: UNITED効果説明

### メタデータ
- `metadata.note`: 補足情報
- `metadata.ocr_confidence`: OCR信頼度（0-1）
- `metadata.processing_notes`: 処理時の注意事項

### OCR情報
- `ocr_info.sp_ocr_type`: OCRタイプ
- `ocr_info.ocr_timestamp`: OCR実行時刻
- `ocr_info.sp_image_path`: SP画像パス

### マージ情報
- `merge_info.merge_timestamp`: マージ実行時刻
- `merge_info.merge_version`: マージ機能バージョン
- `merge_info.card_error`: カードOCRエラー
- `merge_info.card_warning`: カードOCR警告 