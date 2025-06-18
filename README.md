# ガンダムアーセナルベース カードデータ管理システム

このプロジェクトは、ガンダムアーセナルベースのカードデータを管理・分析するためのシステムです。カードの表面・裏面画像の取得、OCRによるテキスト抽出、データの構造化を行います。

## 機能

- カードの表面・裏面画像の取得と保存
- OpenAI APIを使用したカード情報のOCR処理
- カードデータの構造化（MSカード、パイロットカード）
- カード情報のJSON形式での保存

## 将来の実装予定

- デッキシミュレータ
  - カードの組み合わせ検討
  - デッキの評価機能
  - デッキの保存と共有
  - コスト計算
  - リンク能力の相性チェック
  - 地形適性の評価

## 必要条件

- Python 3.8以上
- OpenAI APIキー
- 必要なPythonパッケージ（requirements.txtに記載）

## セットアップ

1. リポジトリをクローン
```bash
git clone [リポジトリURL]
cd [プロジェクトディレクトリ]
```

2. 必要なパッケージをインストール
```bash
pip install -r requirements.txt
```

3. OpenAI APIキーの設定
- `APIKey.txt`ファイルを作成し、OpenAI APIキーを記述

## 使用方法

### カードデータの取得

1. カードリストの生成
```bash
python generate_all_cards_list.py
```
- `all_cards_list`ディレクトリにカードデータが保存されます
- 各カードの表面・裏面情報がJSON形式で保存されます

### OCR処理の実行

1. 単一カードのOCR
```bash
python card_ocr.py [カード画像URL]
```

2. 全カードの一括OCR
```bash
python card_ocr.py --all
```
- `ocr_results`ディレクトリにOCR結果が保存されます
- 各カードの情報が構造化されたJSON形式で保存されます

## データ構造

### カードデータ（all_cards.json）
```json
{
  "front": {
    "url": "表面画像のURL",
    "number": "カード番号",
    "name": "カード名"
  },
  "back": {
    "url": "裏面画像のURL",
    "number": "カード番号",
    "name": "カード名"
  }
}
```

### OCR結果（MSカード）
```json
{
  "type": "MS",
  "name": "カード名",
  "model": "機体名",
  "cost": コスト,
  "category": "カテゴリ",
  "pilot": "パイロット名",
  "stats": {
    "height": "高さ",
    "weight": "重量",
    "mobility": 機動力,
    "ranged_attack": 遠距離攻撃力,
    "melee_attack": 近距離攻撃力,
    "hp": HP
  },
  "terrain_compatibility": {
    "ground": "地上適性",
    "space": "宇宙適性",
    "desert": "砂漠適性",
    "water": "水中適性"
  },
  "weapon": {
    "main": {
      "name": "メイン武器名",
      "range": 射程,
      "type": "武器タイプ"
    },
    "sub": {
      "name": "サブ武器名",
      "range": 射程,
      "type": "武器タイプ"
    }
  },
  "ms_ability": {
    "name": "能力名",
    "cost": コスト,
    "description": "能力説明"
  },
  "special_attack": {
    "name": "必殺技名",
    "target": "対象",
    "range": 射程,
    "power": 威力,
    "description": "必殺技説明"
  },
  "link_abilities": [
    {
      "name": "リンク能力名",
      "condition": "発動条件",
      "effect": "効果"
    }
  ]
}
```

### OCR結果（パイロットカード）
```json
{
  "type": "PL",
  "name": "パイロット名",
  "english_name": "英語名",
  "cost": コスト,
  "category": "カテゴリ",
  "age": 年齢,
  "height": "身長",
  "units": ["搭乗可能機体"],
  "pl_skill": {
    "name": "スキル名",
    "trigger": "発動条件",
    "effect": "効果"
  },
  "link_abilities": [
    {
      "name": "リンク能力名",
      "condition": "発動条件",
      "effect": "効果"
    }
  ],
  "stats": {
    "mobility": 機動力,
    "ranged_attack": 遠距離攻撃力,
    "melee_attack": 近距離攻撃力,
    "hp": HP
  }
}
```

## 注意事項

- OpenAI APIの利用には料金が発生します
- APIの利用制限に注意してください
- カード画像の著作権に注意してください

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。 