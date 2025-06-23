import openai
import sys
import os
import json
import re
import argparse
import glob
import requests
import base64
from PIL import Image
import io
import time
import shutil
from datetime import datetime

from openai import OpenAI

def read_api_key(file_path):
    with open(file_path, 'r') as f:
        return f.read().strip()

def extract_structured_data_from_url(image_path_or_url, api_key):
    client = OpenAI(api_key=api_key)

    prompt = """
これは「アーセナルベース（ARMS）」というカードゲームのカード画像です。  
このカードがどの形式かを判別し、対応するJSON形式で出力してください。

---

カードは以下の2種です：

1. MSカード（モビルスーツ）
2. PLカード（パイロット）

---

それぞれ、以下の形式でJSONを出力してください。  
各フィールドの型を守り、実際に読み取れた値だけを埋めてください。

### 【MSカードの形式】
```json
{
  "card_id": "string",                   // 例: "FQ01-001"
  "type": "MS",
  "card_label": {
    "class": "string",                  // 「近距離」「遠距離」「機動」など
    "cost_label": "string"             // 表示ラベル 例: "コスト6"
  },
  "name": "string",
  "model": "string",
  "cost": number,
  "category": "string",                // 「近距離」「遠距離」「機動」など
  "pilot": "string",
  "stats": {
    "height": "string",
    "weight": "string",
    "mobility": number,
    "ranged_attack": number,
    "melee_attack": number,
    "hp": number
  },
  "terrain_compatibility": {
    "ground": "string",
    "space": "string",
    "desert": "string",
    "water": "string"
  },
  "weapon": {
    "main": {
      "name": "string",
      "range": number,
      "type": "string"
    },
    "sub": {
      "name": "string",
      "range": number,
      "type": "string"
    }
  },
  "ms_ability": {
    "name": "string",
    "type": "string",
    "range": number,
    "cost": number,
    "description": "string"
  },
  "link_ability": [
    {
      "name": "string",
      "condition": "string",
      "effect": "string"
    }
  ],
  "impact_area": {
    "type": "string",              // "circular" など
    "radius": number,
    "centered": boolean
  },
  "illustrator": "string",
  "raw": "string"                        // OCRの生レスポンス文字列を必ず含めてください
}
```

### 【PLカードの形式】
```json
{
  "card_id": "string",                   // 例: "FQ01-P01"
  "type": "PL",
  "card_label": {
    "class": "string",                  // 「パイロット」など
    "cost_label": "string"             // 表示ラベル 例: "コスト3"
  },
  "name": "string",
  "cost": number,
  "category": "string",                // 「パイロット」など
  "pilot_skill": {
    "name": "string",
    "effect": "string",
    "has_sq_skill": boolean,           // SQ関連スキルを持つかどうか
    "sq_skill_details": {
      "sq_gauge_effect": "string",     // SQゲージ変動に関する効果（例: "SQゲージ+1"）
      "sq_max_effect": "string",       // SQゲージが最大値の場合の効果
      "squad_rush_effect": "string"    // SQUAD RUSH中に発動する効果
    }
  },
  "link_ability": [
    {
      "name": "string",
      "condition": "string",
      "effect": "string"
    }
  ],
  "illustrator": "string",
  "raw": "string"                        // OCRの生レスポンス文字列を必ず含めてください
}
```

**PLカードのSQ関連スキルについて**:

1. **SQ関連スキルの判定**: パイロットスキルに「SQ」「SQUAD」「ゲージ」「ガージ」などのキーワードが含まれている場合は `has_sq_skill: true` にしてください。

2. **pilot_skill.effectフィールドの重要事項**: 
   - パイロットスキルの説明文には、SQ関連の条件や効果を必ず含めてください
   - 「SQゲージが最大時」「SQUAD RUSH中」などの条件文があれば、それらをeffectフィールドに含めてください
   - 複数の効果がある場合は、改行（\\n）で区切って記載してください
   - 例: "SQゲージが最大時\\n自身の「遠距離攻撃力」「SP威力」をアップする。\\nSQUAD RUSH中\\n「遠距離攻撃力」「SP威力」の効果がさらに上昇する。"

3. **SQゲージ変動効果**: パイロットスキルの説明文で、SQゲージの増減に関する記述（例: "SQゲージ+1"、"SQゲージ-1"など）があれば抽出してください。

4. **SQゲージ最大値効果**: パイロットスキルの説明文で、SQゲージが最大値の場合の効果（例: "SQゲージが最大時"、"SQゲージ最大時"など）があれば抽出してください。

5. **SQUAD RUSH効果**: パイロットスキルの説明文で、以下のSQUAD RUSH関連の記述があれば、その効果を抽出してください：
   - 「SQUAD RUSH中」で始まる効果
   - 「SQUADRUSH中」で始まる効果
   - 「スクワッドラッシュ中」で始まる効果
   - 「SQUAD RUSH発動中」で始まる効果
   - 「SQUADRUSH発動中」で始まる効果
   - 「SQUAD RUSHが発動」で始まる効果
   - 「SQUADRUSHが発動」で始まる効果

6. **効果の分離**: 説明文が複数の効果を含む場合は、適切に分離して各フィールドに格納してください。特に「SQUAD RUSH発動中」の効果は、その直後に続く効果文を正確に抽出してください。

7. **該当なしの場合**: 各効果が存在しない場合は `null` または空文字列を使用してください。

**重要**: 
- SQ関連スキルを持つPLカードは、多くの場合「SQUAD RUSH発動中」に発動する効果を持ちます。この効果を正確に識別し、`squad_rush_effect`フィールドに格納してください。
- **pilot_skill.effectフィールドには、SQ関連の条件や効果を必ず含めてください。これが最も重要です。**

**rawフィールドについて**:
- 出力するJSONには必ず "raw" フィールドを含めてください。
- rawにはOCRで読み取った生のテキストやレスポンス全体をそのまま格納してください。
"""

    # 画像がローカルファイルパスかURLかを判定
    if os.path.exists(image_path_or_url):
        # ローカルファイルの場合
        with open(image_path_or_url, "rb") as image_file:
            image_bytes = image_file.read()
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            data_url = f"data:image/jpeg;base64,{image_b64}"
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "あなたは画像からカード情報を抽出してJSONに変換するOCRアシスタントです。"},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]}
                ],
                max_tokens=4096,
                temperature=0.0,
            )
    elif len(image_path_or_url) > 1000:
        # base64文字列が直接渡された場合
        data_url = f"data:image/jpeg;base64,{image_path_or_url}"
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたは画像からカード情報を抽出してJSONに変換するOCRアシスタントです。"},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]}
            ],
            max_tokens=4096,
            temperature=0.0,
        )
    else:
        # URLの場合
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたは画像からカード情報を抽出してJSONに変換するOCRアシスタントです。"},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_path_or_url}}
                ]}
            ],
            max_tokens=4096,
            temperature=0.0,
        )

    return response.choices[0].message.content

def save_result_to_file(card_number, card_name, result_json, series_name="", results_dir='ocr_results', suffix=""):
    # ファイル名に使えない文字をアンダースコアに変換
    safe_number = sanitize_filename(card_number)
    safe_name = sanitize_filename(card_name)
    safe_series = sanitize_filename(series_name)
    
    # 収録パック+カードナンバー+カード名.jsonの形式
    if safe_series:
        filename = f"{safe_series}_{safe_number}_{safe_name}{suffix}.json"
    else:
        filename = f"{safe_number}_{safe_name}{suffix}.json"
    
    os.makedirs(results_dir, exist_ok=True)
    file_path = os.path.join(results_dir, filename)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)

def sanitize_filename(s):
    return s.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_').replace(' ', '_')

def normalize_ocr_data(data):
    """OCR結果のデータを正規化する"""
    if not isinstance(data, dict):
        return data
    
    normalized = {}
    
    for key, value in data.items():
        if isinstance(value, dict):
            normalized[key] = normalize_ocr_data(value)
        elif isinstance(value, list):
            normalized[key] = [normalize_ocr_data(item) if isinstance(item, dict) else item for item in value]
        elif isinstance(value, str):
            # 文字列の正規化
            normalized_value = value.strip()
            # 数値として解釈できる場合は数値に変換
            if normalized_value.isdigit():
                normalized[key] = int(normalized_value)
            else:
                normalized[key] = normalized_value
        elif isinstance(value, (int, float)):
            # 数値の正規化
            if key in ['mobility', 'ranged_attack', 'melee_attack', 'hp', 'cost', 'range', 'power']:
                normalized[key] = int(value) if isinstance(value, (int, float)) else value
            else:
                normalized[key] = value
        else:
            normalized[key] = value
    
    return normalized

def normalize_card_number(card_number):
    """カード番号を正規化する"""
    if not card_number:
        return card_number
    
    # カード番号の形式を統一（例: FQ01-001, UTB06-001）
    normalized = card_number.upper().strip()
    
    # ハイフンが含まれていない場合は適切な位置に挿入
    if '-' not in normalized:
        # アルファベット部分と数字部分を分離
        import re
        match = re.match(r'([A-Z]+)(\d+)', normalized)
        if match:
            letters, numbers = match.groups()
            normalized = f"{letters}-{numbers}"
    
    return normalized

def ocr_back_cards_from_all_cards_list(api_key_path, cards_dir='all_cards_list', results_dir='ocr_results'):
    """all_cards_listディレクトリのJSONファイルから裏面画像を読み込み、OCRを実行"""
    
    # 出力ディレクトリをクリーンアップ
    if os.path.exists(results_dir):
        print(f"出力ディレクトリ ({results_dir}) をクリーンアップしています...")
        shutil.rmtree(results_dir)
    os.makedirs(results_dir)
    print(f"出力ディレクトリ ({results_dir}) を作成しました。")
    
    # OCR結果保存ディレクトリ
    os.makedirs(results_dir, exist_ok=True)
    
    # カードリストディレクトリのJSONファイルを取得
    if not os.path.exists(cards_dir):
        print(f"エラー: {cards_dir}ディレクトリが見つかりません")
        return
    
    json_files = glob.glob(os.path.join(cards_dir, '*.json'))
    if not json_files:
        print(f"エラー: {cards_dir}ディレクトリにJSONファイルが見つかりません")
        return
    
    print(f"見つかったJSONファイル数: {len(json_files)}")
    print(f"カードリストディレクトリ: {cards_dir}")
    print(f"OCR結果保存ディレクトリ: {results_dir}")
    
    # APIキー読み込み
    api_key = read_api_key(api_key_path)
    
    processed_count = 0
    skipped_count = 0
    error_count = 0
    
    for idx, json_file in enumerate(json_files, 1):
        try:
            # JSONファイルを読み込み
            with open(json_file, 'r', encoding='utf-8') as f:
                card_data = json.load(f)
            
            card_number = card_data.get('number', '')
            card_name = card_data.get('name', '')
            series_name = card_data.get('series', '')
            
            # 画像URLを取得（image_urlとurlの両方に対応）
            front_image_url = ''
            back_image_url = ''
            
            # 表面画像URL取得
            if 'front' in card_data:
                front_data = card_data['front']
                front_image_url = front_data.get('image_url', front_data.get('url', ''))
                # カード番号と名前も取得
                if not card_number:
                    card_number = front_data.get('number', '')
                if not card_name:
                    card_name = front_data.get('name', '')
                if not series_name:
                    series_name = front_data.get('series', '')
            
            # 裏面画像URL取得
            if 'back' in card_data:
                back_data = card_data['back']
                back_image_url = back_data.get('image_url', back_data.get('url', ''))
                # カード番号と名前も取得（表面で取得できていない場合）
                if not card_number:
                    card_number = back_data.get('number', '')
                if not card_name:
                    card_name = back_data.get('name', '')
                if not series_name:
                    series_name = back_data.get('series', '')
            
            # カード番号から_bを除去（裏面の場合）
            if card_number and card_number.endswith('_b'):
                card_number = card_number[:-2]
            
            # 裏面画像URLがない場合はスキップ
            if not back_image_url:
                print(f"[{idx}/{len(json_files)}] スキップ: 裏面画像なし - {card_number} {card_name}")
                skipped_count += 1
                continue
            
            # 既にOCR結果が存在し、かつ内容が有効な場合はスキップ
            safe_number = sanitize_filename(card_number)
            safe_name = sanitize_filename(card_name)
            safe_series = sanitize_filename(series_name)
            if safe_series:
                ocr_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}.json")
            else:
                ocr_result_file = os.path.join(results_dir, f"{safe_number}_{safe_name}.json")

            if os.path.exists(ocr_result_file):
                try:
                    with open(ocr_result_file, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                    # データが空の辞書やリストでないことを確認
                    if existing_data and (isinstance(existing_data, dict) and existing_data):
                        # 統合マージ形式のデータかどうかチェック
                        if 'card_info' in existing_data and 'sp_data' in existing_data:
                            print(f"[{idx}/{len(json_files)}] スキップ: 有効な既存のOCR結果 - {card_number} {card_name}")
                            skipped_count += 1
                            continue
                        else:
                            print(f"[{idx}/{len(json_files)}] 再処理: 既存のOCR結果は統合マージ形式ではありません - {card_number} {card_name}")
                    else:
                        print(f"[{idx}/{len(json_files)}] 再処理: 既存のOCR結果は空または無効 - {card_number} {card_name}")
                except (json.JSONDecodeError, IOError) as e:
                    print(f"[{idx}/{len(json_files)}] 再処理: 既存のOCR結果が破損 ({e}) - {card_number} {card_name}")
            
            print(f"[{idx}/{len(json_files)}] OCR開始: {card_number} {card_name}")
            print(f"   表面URL: {front_image_url}")
            print(f"   裏面URL: {back_image_url}")
            
            try:
                # 1. カード全体のOCR
                sp_image_b64 = crop_sp_section(back_image_url, save_dir=results_dir, card_number=card_number, card_name=card_name)
                if sp_image_b64:
                    data_url = f"data:image/jpeg;base64,{sp_image_b64}"
                    sp_result = extract_sp_details_from_image(data_url, api_key)
                    # --- SP生データを必ずJSONで保存（連番で上書き防止） ---
                    def get_unique_path(base_path):
                        if not os.path.exists(base_path):
                            return base_path
                        base, ext = os.path.splitext(base_path)
                        i = 1
                        while True:
                            new_path = f"{base}_{i}{ext}"
                            if not os.path.exists(new_path):
                                return new_path
                            i += 1
                    safe_number = sanitize_filename(card_number)
                    safe_name = sanitize_filename(card_name)
                    safe_series = sanitize_filename(series_name)
                    if safe_series:
                        sp_raw_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sp_raw.json")
                        sp_parsed_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sp.json")
                    else:
                        sp_raw_result_file = os.path.join(results_dir, f"{safe_number}_{safe_name}_sp_raw.json")
                        sp_parsed_result_file = os.path.join(results_dir, f"{safe_number}_{safe_name}_sp.json")
                    sp_raw_result_file = get_unique_path(sp_raw_result_file)
                    sp_parsed_result_file = get_unique_path(sp_parsed_result_file)
                    sp_json_str = sp_result
                    if "```json" in sp_result:
                        sp_json_str = sp_result.split("```json")[1].split("```", 1)[0].strip()
                    elif "```" in sp_result:
                        sp_json_str = sp_result.split("```", 1)[1].strip()
                    print(f"    → SP生データ保存先: {sp_raw_result_file}")
                    print(f"    → SP生データ内容: {sp_result[:200]} ...")
                    with open(sp_raw_result_file, 'w', encoding='utf-8') as f:
                        f.write(sp_result)
                    print(f"    ✓ SP生データ保存: {sp_raw_result_file}")
                    try:
                        sp_details = json.loads(sp_json_str)
                        print(f"    → SPパース済みデータ保存先: {sp_parsed_result_file}")
                        print(f"    → SPパース済みデータ内容: {json.dumps(sp_details, ensure_ascii=False)[:200]} ...")
                        with open(sp_parsed_result_file, 'w', encoding='utf-8') as f:
                            json.dump(sp_details, f, ensure_ascii=False, indent=2)
                        print(f"    ✓ SP詳細OCRパース済みデータ保存: {sp_parsed_result_file}")
                    except Exception as sp_parse_error:
                        print(f"    ⚠ SP詳細OCR結果のパース失敗: {str(sp_parse_error)}")
                else:
                    print(f"    ⚠ SP部分の切り取りに失敗")
            except Exception as e:
                error_message = str(e)
                print(f"  ✗ API呼び出し失敗: {card_number} {card_name} {error_message}")
                
                # APIクォータエラーの場合は特別な処理
                if "429" in error_message or "insufficient_quota" in error_message:
                    print(f"    ⚠ APIクォータの上限に達しました。処理を停止します。")
                    print(f"    対処法:")
                    print(f"    1. OpenAIのダッシュボードでクォータを確認: https://platform.openai.com/usage")
                    print(f"    2. 新しいAPIキーを使用")
                    print(f"    3. しばらく待ってから再実行")
                    
                    # エラー情報を保存
                    merged_result = {
                        'card_info': {
                            'card_number': card_number,
                            'card_name': card_name,
                            'series': series_name,
                            'type': '',
                            'name': '',
                            'cost': '',
                            'power': '',
                            'attribute': '',
                            'rarity': '',
                            'effect': '',
                            'front_image_url': front_image_url,
                            'back_image_url': back_image_url
                        },
                        'sp_data': {
                            'has_sp_data': False,
                            'sp_detail': None,
                            'sp_raw': None
                        },
                        'source_data': card_data,
                        'merge_info': {
                            'merge_timestamp': datetime.now().isoformat(),
                            'merge_version': '1.0',
                            'card_error': f"APIクォータエラー: {error_message}",
                            'card_warning': "APIクォータの上限に達しました"
                        }
                    }
                    save_result_to_file(card_number, card_name, merged_result, series_name, results_dir)
                    error_count += 1
                    
                    # 処理を停止するかどうか確認
                    print(f"\n=== APIクォータエラーにより処理を停止 ===")
                    print(f"処理済み: {processed_count}件")
                    print(f"スキップ: {skipped_count}件")
                    print(f"エラー: {error_count}件")
                    print(f"合計: {len(json_files)}件")
                    return
                else:
                    # 通常のエラー処理
                    merged_result = {
                        'card_info': {
                            'card_number': card_number,
                            'card_name': card_name,
                            'series': series_name,
                            'type': '',
                            'name': '',
                            'cost': '',
                            'power': '',
                            'attribute': '',
                            'rarity': '',
                            'effect': '',
                            'front_image_url': front_image_url,
                            'back_image_url': back_image_url
                        },
                        'sp_data': {
                            'has_sp_data': False,
                            'sp_detail': None,
                            'sp_raw': None
                        },
                        'source_data': card_data,
                        'merge_info': {
                            'merge_timestamp': datetime.now().isoformat(),
                            'merge_version': '1.0',
                            'card_error': error_message,
                            'card_warning': None
                        }
                    }
                    save_result_to_file(card_number, card_name, merged_result, series_name, results_dir)
                    error_count += 1
            
        except Exception as e:
            print(f"  ✗ ファイル処理エラー: {json_file} {str(e)}")
            error_count += 1
    
    print(f"\n=== OCR処理完了 ===")
    print(f"処理済み: {processed_count}件")
    print(f"スキップ: {skipped_count}件")
    print(f"エラー: {error_count}件")
    print(f"合計: {len(json_files)}件")
    print(f"すべての結果は統合マージ形式で保存されました")

def extract_sp_details_from_image(image_path_or_url, api_key):
    """SP部分の詳細OCR処理を行う関数"""
    client = OpenAI(api_key=api_key)

    sp_prompt = """
これは「アーセナルベース（ARMS）」というカードゲームのMSカードのSP（スペシャルアタック）部分の画像です。
SPの詳細情報を正確に抽出して、構造化されたJSON形式で出力してください。

以下の形式でJSONを出力してください：

```json
{
  "sp_info": {
    "type": "string",                    // 種類（"normal", "SQUAD SP", "UNITED SP"）
    "name": "string",                    // SP名（例: "バズーカ連射"）
    "partner": ["string", "null"],       // 連携相手（UNITED のみ、それ以外は null）
    "target": "string",                  // 攻撃対象（例: "単体（敵）"）
    "attack_type": "string",             // 攻撃種別（例: "貫通（敵）"）
    "range": "number",                   // 射程
    "squad_sp": "boolean",               // SQUAD SP の場合 true
    "united_sp": "boolean"               // 連携相手がいる場合 true
  },
  "power": {
    "normal": "number",                  // 通常SP威力
    "squad": ["number", "null"],         // SQUAD SP威力（SQUADのみ、それ以外は null）
    "united": ["number", "null"]         // UNITED SP威力（UNITEDのみ、それ以外は null）
  },
  "descriptions": {
    "all_description": "string",         // SPにかかれている全ての説明文、推論を混ぜずにできるだけそのままにする
    "normal_description": "string",      // 通常SPの効果説明
    "squad_description": ["string", "null"],   // SQUAD効果の説明（なければ null）
    "united_description": ["string", "null"]   // UNITED効果の説明（なければ null）
  },
  "metadata": {
    "note": ["string", "null"],          // 任意の補足（例: "／ー"）
    "ocr_confidence": "number",          // OCR信頼度（0-1）
    "processing_notes": ["string", "null"] // 処理時の注意事項
  }
}
```

**重要な処理ルール**:

1. **説明文の処理**: まず全文をOCRしてください。その後、その説明文に/があれば/で分割してください。
   - /がない場合: squad_spとunited_spをfalseにし、説明文をnormal_descriptionに格納
   - /がある場合: 前半部分をnormal_description、後半部分をsquad_descriptionまたはunited_descriptionに格納

2. **「／ー」記号の処理**: 説明文に「／ー」（全角スラッシュ＋長音符）が含まれている場合：
   - squad_spとunited_spをfalseにする
   - normal_descriptionに「／ー」を含む説明文をそのまま格納
   - squad_descriptionとunited_descriptionはnullにする
   - metadata.noteに「／ー」を記録

3. **typeフィールドの設定**:
   - partnerが存在する場合: type = "UNITED SP", united_sp = true
   - partnerが存在しない場合: type = "normal", united_sp = false
   - SQUAD SPの場合: type = "SQUAD SP", squad_sp = true

4. **複数の/が含まれる場合**: 最初の/で分割し、前半をnormal_description、後半全体をsquad_descriptionまたはunited_descriptionに格納

5. **記号のみの場合**: -などの記号のみで日本語の文章が書かれていない場合は、squad_spとunited_spをfalseにし、normal_descriptionにそのままの説明文を格納

6. **数値の処理**: 
   - 射程や威力は数値として出力（文字列ではなく）
   - 不明な場合はnullを使用

7. **信頼度の設定**:
   - テキストが明確に読み取れる場合: ocr_confidence = 0.9-1.0
   - 一部不明瞭な場合: ocr_confidence = 0.7-0.8
   - 読み取り困難な場合: ocr_confidence = 0.5-0.6

8. **処理注意事項**:
   - 推論は避け、実際に画像に書かれている内容のみを抽出
   - 不明な部分はnullを使用
   - 処理時の判断や注意点があればprocessing_notesに記録
"""

    # 画像がローカルファイルパスかURLかを判定
    if os.path.exists(image_path_or_url):
        # ローカルファイルの場合
        with open(image_path_or_url, "rb") as image_file:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "user", "content": sp_prompt},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_file.read()}"}}
                    ]}
                ],
                max_tokens=2000,
                temperature=0.1
            )
    else:
        # URLの場合
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": sp_prompt},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": image_path_or_url}}
                ]}
            ],
            max_tokens=2000,
            temperature=0.1
        )
    
    return response.choices[0].message.content

def crop_sp_section(image_path_or_url, crop_coords=None, save_dir=None, card_number="", card_name=""):
    """カード画像からSP部分を切り取る関数"""
    try:
        # 画像を読み込み
        if os.path.exists(image_path_or_url):
            # ローカルファイルの場合
            image = Image.open(image_path_or_url)
        elif len(image_path_or_url) > 1000:
            # base64文字列の場合
            image_data = base64.b64decode(image_path_or_url)
            image = Image.open(io.BytesIO(image_data))
        else:
            # URLの場合
            response = requests.get(image_path_or_url)
            image = Image.open(io.BytesIO(response.content))
        
        # デフォルトの切り取り座標（ユーザーの指定に基づき、SPが記載されている範囲）
        if crop_coords is None:
            width, height = image.size
            
            # カードの左下を切り抜く
            left = 15
            upper = height // 1.6
            right = width // 1.8
            lower = height - 55
            
            crop_coords = (left, upper, right, lower)
          
        # SP部分を切り取り
        sp_image = image.crop(crop_coords)
        
        # 切り取った画像を保存（指定された場合）
        if save_dir and card_number and card_name:
            sp_images_dir = os.path.join(save_dir, 'sp_images')
            os.makedirs(sp_images_dir, exist_ok=True)
            
            safe_number = sanitize_filename(card_number)
            safe_name = sanitize_filename(card_name)
            sp_image_filename = f"{safe_number}_{safe_name}_sp.jpg"
            sp_image_path = os.path.join(sp_images_dir, sp_image_filename)
            
            sp_image.save(sp_image_path, format='JPEG', quality=95)
            print(f"    ✓ SP画像保存: {sp_image_path}")
        
        # 切り取った画像をbase64エンコード
        buffer = io.BytesIO()
        sp_image.save(buffer, format='JPEG')
        sp_image_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return sp_image_b64
        
    except Exception as e:
        print(f"SP部分の切り取りに失敗: {str(e)}")
        return None

def merge_sp_data_to_card_results(results_dir='ocr_results'):
    """SPデータをカードのOCR結果にマージする関数"""
    print("SPデータのマージ処理を開始します...")
    
    # SP詳細OCR結果ファイルを検索
    sp_files = glob.glob(os.path.join(results_dir, '*_sp.json'))
    print(f"見つかったSPファイル数: {len(sp_files)}")
    
    # カードのOCR結果ファイルを検索
    card_files = glob.glob(os.path.join(results_dir, '*.json'))
    card_files = [f for f in card_files if not f.endswith(('_sp.json', '_sp_raw.json'))]
    print(f"見つかったカードファイル数: {len(card_files)}")
    
    merged_count = 0
    error_count = 0
    skipped_count = 0
    
    # SPファイルからマージ処理
    for sp_file in sp_files:
        try:
            # SPファイルを読み込み
            with open(sp_file, 'r', encoding='utf-8') as f:
                sp_data = json.load(f)
            
            card_number = sp_data.get('card_number', '')
            card_name = sp_data.get('card_name', '')
            series_name = sp_data.get('series', '')
            special_attack = sp_data.get('special_attack', {})
            
            if not card_number or not card_name:
                print(f"  ⚠ カード情報が不完全: {sp_file}")
                continue
            
            # 対応するカードのOCR結果ファイルを検索
            safe_number = sanitize_filename(card_number)
            safe_name = sanitize_filename(card_name)
            safe_series = sanitize_filename(series_name)
            
            if safe_series:
                card_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}.json")
            else:
                card_result_file = os.path.join(results_dir, f"{safe_number}_{safe_name}.json")
            
            if not os.path.exists(card_result_file):
                print(f"  ⚠ 対応するカードファイルが見つかりません: {card_result_file}")
                continue
            
            # カードのOCR結果ファイルを読み込み
            with open(card_result_file, 'r', encoding='utf-8') as f:
                card_data = json.load(f)
            
            # SPデータをマージ
            card_data['special_attack'] = special_attack
            card_data['sp_ocr_type'] = 'detailed'
            card_data['sp_image_path'] = sp_data.get('sp_image_path', '')
            
            # マージしたデータを保存
            with open(card_result_file, 'w', encoding='utf-8') as f:
                json.dump(card_data, f, ensure_ascii=False, indent=2)
            
            print(f"  ✓ SPデータをマージ: {card_number} {card_name}")
            merged_count += 1
            
        except Exception as e:
            print(f"  ✗ SPデータマージエラー: {sp_file} - {str(e)}")
            error_count += 1
    
    # SPデータが存在しないMSカードにフラグを追加
    for card_file in card_files:
        try:
            # カードファイルを読み込み
            with open(card_file, 'r', encoding='utf-8') as f:
                card_data = json.load(f)
            
            # MSカードでSPデータが存在しない場合のみフラグを追加
            if card_data.get('type') == 'MS' and 'special_attack' not in card_data:
                card_data['sp_ocr_type'] = 'not_available'
                card_data['sp_image_path'] = ''
                
                # 更新したデータを保存
                with open(card_file, 'w', encoding='utf-8') as f:
                    json.dump(card_data, f, ensure_ascii=False, indent=2)
                
                card_number = card_data.get('card_number', '')
                card_name = card_data.get('card_name', '')
                print(f"  ✓ SPデータなしフラグ追加: {card_number} {card_name}")
                skipped_count += 1
            elif card_data.get('type') == 'PL':
                # PLカードの場合はSP関連フィールドを追加しない
                card_number = card_data.get('card_number', '')
                card_name = card_data.get('card_name', '')
                print(f"  ✓ PLカード（SP不要）: {card_number} {card_name}")
                skipped_count += 1
                
        except Exception as e:
            print(f"  ✗ カードファイル処理エラー: {card_file} - {str(e)}")
            error_count += 1
    
    print(f"\n=== SPデータマージ完了 ===")
    print(f"マージ成功: {merged_count}件")
    print(f"SPデータなしフラグ追加: {skipped_count}件")
    print(f"エラー: {error_count}件")
    print(f"合計処理: {len(sp_files) + len(card_files)}件")

def merge_all_card_data_with_all_suffix(results_dir='ocr_results'):
    """すべてのJSONデータを統一的にマージし、_allサフィックス付きで保存"""
    print("統合マージ処理を開始します...")
    
    # 結果ディレクトリ内のすべてのJSONファイルを取得
    json_files = glob.glob(os.path.join(results_dir, '*.json'))
    
    # 基本カードデータ、SP詳細、SP生データを分類
    card_data_files = []
    sp_detail_files = []
    sp_raw_files = []
    
    for json_file in json_files:
        filename = os.path.basename(json_file)
        if filename.endswith('_sp.json'):
            sp_detail_files.append(json_file)
        elif filename.endswith('_sp_raw.json'):
            sp_raw_files.append(json_file)
        elif not filename.endswith('_all.json'):  # _allファイルは除外
            card_data_files.append(json_file)
    
    print(f"基本カードデータ: {len(card_data_files)}件")
    print(f"SP詳細データ: {len(sp_detail_files)}件")
    print(f"SP生データ: {len(sp_raw_files)}件")
    
    # カード番号ベースでマージ
    merged_data = {}
    
    # 基本カードデータを読み込み
    for card_file in card_data_files:
        try:
            with open(card_file, 'r', encoding='utf-8') as f:
                card_data = json.load(f)
            
            card_number = card_data.get('card_number', '')
            if card_number:
                merged_data[card_number] = {
                    'card_data': card_data,
                    'sp_detail': None,
                    'sp_raw': None
                }
        except Exception as e:
            print(f"基本カードデータ読み込みエラー {card_file}: {e}")
    
    # SP詳細データをマージ
    for sp_file in sp_detail_files:
        try:
            with open(sp_file, 'r', encoding='utf-8') as f:
                sp_data = json.load(f)
            
            card_number = sp_data.get('card_number', '')
            if card_number and card_number in merged_data:
                merged_data[card_number]['sp_detail'] = sp_data
        except Exception as e:
            print(f"SP詳細データ読み込みエラー {sp_file}: {e}")
    
    # SP生データをマージ
    for sp_raw_file in sp_raw_files:
        try:
            with open(sp_raw_file, 'r', encoding='utf-8') as f:
                sp_raw_data = json.load(f)
            
            card_number = sp_raw_data.get('card_number', '')
            if card_number and card_number in merged_data:
                merged_data[card_number]['sp_raw'] = sp_raw_data
        except Exception as e:
            print(f"SP生データ読み込みエラー {sp_raw_file}: {e}")
    
    # 統合データを作成して保存
    for card_number, data in merged_data.items():
        try:
            card_data = data['card_data']
            sp_detail = data['sp_detail']
            sp_raw = data['sp_raw']
            
            # 統合データ構造
            merged_result = {
                'card_info': {
                    'card_number': card_number,
                    'card_name': card_data.get('card_name', ''),
                    'series': card_data.get('series', ''),
                    'type': card_data.get('type', ''),
                    'name': card_data.get('name', ''),
                    'cost': card_data.get('cost', ''),
                    'power': card_data.get('power', ''),
                    'attribute': card_data.get('attribute', ''),
                    'rarity': card_data.get('rarity', ''),
                    'effect': card_data.get('effect', ''),
                    'front_image_url': card_data.get('front', {}).get('image_url', ''),
                    'back_image_url': card_data.get('back', {}).get('image_url', '')
                },
                'sp_data': {
                    'has_sp_data': sp_detail is not None or sp_raw is not None,
                    'sp_detail': sp_detail.get('sp_data', {}) if sp_detail else None,
                    'sp_raw': sp_raw.get('ocr_info', {}) if sp_raw else None
                },
                'source_data': card_data.get('source_data', {}),
                'merge_info': {
                    'merge_timestamp': datetime.now().isoformat(),
                    'merge_version': '1.0',
                    'card_error': card_data.get('error', None),
                    'card_warning': card_data.get('warning', None)
                }
            }
            
            # ファイル名生成
            safe_number = sanitize_filename(card_number)
            safe_name = sanitize_filename(card_data.get('card_name', ''))
            safe_series = sanitize_filename(card_data.get('series', ''))
            
            if safe_series:
                merged_filename = f"{safe_series}_{safe_number}_{safe_name}_all.json"
            else:
                merged_filename = f"{safe_number}_{safe_name}_all.json"
            
            merged_filepath = os.path.join(results_dir, merged_filename)
            
            # 統合データを保存
            with open(merged_filepath, 'w', encoding='utf-8') as f:
                json.dump(merged_result, f, ensure_ascii=False, indent=2)
            
            print(f"✓ 統合マージ完了: {merged_filename}")
            
        except Exception as e:
            print(f"✗ 統合マージエラー {card_number}: {e}")
    
    print(f"\n=== 統合マージ処理完了 ===")
    print(f"統合マージ済みファイル数: {len(merged_data)}件")
    print(f"すべての統合データは '_all.json' サフィックス付きで保存されました")

def generate_consolidated_cards_json(results_dir='ocr_results', output_file='consolidated_cards.json'):
    """すべてのOCR結果をカードごとにまとめて1つのJSONファイルに保存"""
    print("カードごとの統合JSONファイル生成を開始します...")
    
    # 結果ディレクトリ内のすべてのJSONファイルを取得
    json_files = glob.glob(os.path.join(results_dir, '*.json'))
    
    # 基本カードデータ、SP詳細、SP生データを分類
    card_data_files = []
    sp_detail_files = []
    sp_raw_files = []
    
    for json_file in json_files:
        filename = os.path.basename(json_file)
        if filename.endswith('_sp.json'):
            sp_detail_files.append(json_file)
        elif filename.endswith('_sp_raw.json'):
            sp_raw_files.append(json_file)
        elif not filename.endswith('_all.json') and not filename.endswith('consolidated_cards.json'):  # _allファイルと統合ファイルは除外
            card_data_files.append(json_file)
    
    print(f"基本カードデータ: {len(card_data_files)}件")
    print(f"SP詳細データ: {len(sp_detail_files)}件")
    print(f"SP生データ: {len(sp_raw_files)}件")
    
    # カード番号ベースでデータを整理
    consolidated_data = {}
    
    # 基本カードデータを読み込み
    for card_file in card_data_files:
        try:
            with open(card_file, 'r', encoding='utf-8') as f:
                card_data = json.load(f)
            
            # 実際のJSONファイル構造に合わせてカード番号を取得
            card_number = None
            if 'card_info' in card_data:
                card_number = card_data['card_info'].get('card_number', '')
            elif 'card_id' in card_data:
                card_number = card_data['card_id']
            elif 'card_number' in card_data:
                card_number = card_data['card_number']
            
            if card_number:
                consolidated_data[card_number] = {
                    'card_data': card_data,
                    'sp_detail': None,
                    'sp_raw': None
                }
        except Exception as e:
            print(f"基本カードデータ読み込みエラー {card_file}: {e}")
    
    # SP詳細データをマージ
    for sp_file in sp_detail_files:
        try:
            with open(sp_file, 'r', encoding='utf-8') as f:
                sp_data = json.load(f)
            
            # SPファイルからカード番号を取得
            card_number = None
            if 'card_number' in sp_data:
                card_number = sp_data['card_number']
            elif 'card_id' in sp_data:
                card_number = sp_data['card_id']
            
            if card_number and card_number in consolidated_data:
                consolidated_data[card_number]['sp_detail'] = sp_data
        except Exception as e:
            print(f"SP詳細データ読み込みエラー {sp_file}: {e}")
    
    # SP生データをマージ
    for sp_raw_file in sp_raw_files:
        try:
            with open(sp_raw_file, 'r', encoding='utf-8') as f:
                sp_raw_data = json.load(f)
            
            # SP生ファイルからカード番号を取得
            card_number = None
            if 'card_number' in sp_raw_data:
                card_number = sp_raw_data['card_number']
            elif 'card_id' in sp_raw_data:
                card_number = sp_raw_data['card_id']
            
            if card_number and card_number in consolidated_data:
                consolidated_data[card_number]['sp_raw'] = sp_raw_data
        except Exception as e:
            print(f"SP生データ読み込みエラー {sp_raw_file}: {e}")
    
    # 統合データを作成
    final_consolidated_data = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'total_cards': len(consolidated_data),
            'version': '1.0',
            'description': 'アーセナルベース（ARMS）カードゲームのOCR結果統合データ'
        },
        'cards': {}
    }
    
    # 各カードのデータを整理して追加
    for card_number, data in consolidated_data.items():
        try:
            card_data = data['card_data']
            sp_detail = data['sp_detail']
            sp_raw = data['sp_raw']
            
            # 実際のJSONファイル構造に合わせてデータを抽出
            card_info = card_data.get('card_info', {})
            source_data = card_data.get('source_data', {})
            merge_info = card_data.get('merge_info', {})
            
            # カード情報を整理
            card_entry = {
                'card_id': card_number,
                'type': card_info.get('type', ''),
                'name': card_info.get('name', ''),
                'cost': card_info.get('cost', ''),
                'category': card_info.get('category', ''),
                'card_label': card_info.get('card_label', {}),
                'illustrator': card_info.get('illustrator', ''),
                'has_sp_data': sp_detail is not None or sp_raw is not None,
                'front_image_url': card_info.get('front_image_url', ''),
                'back_image_url': card_info.get('back_image_url', ''),
                'series': card_info.get('series', ''),
                'power': card_info.get('power', ''),
                'attribute': card_info.get('attribute', ''),
                'rarity': card_info.get('rarity', ''),
                'effect': card_info.get('effect', '')
            }
            
            # MSカード固有の情報
            if card_info.get('type') == 'MS':
                card_entry.update({
                    'model': card_info.get('model', ''),
                    'pilot': card_info.get('pilot', ''),
                    'stats': card_info.get('stats', {}),
                    'terrain_compatibility': card_info.get('terrain_compatibility', {}),
                    'weapon': card_info.get('weapon', {}),
                    'ms_ability': card_info.get('ms_ability', {}),
                    'impact_area': card_info.get('impact_area', {})
                })
            
            # PLカード固有の情報
            elif card_info.get('type') == 'PL':
                card_entry.update({
                    'pilot_skill': card_info.get('pilot_skill', {})
                })
            
            # 共通のリンクアビリティ
            card_entry['link_ability'] = card_info.get('link_ability', [])
            
            # SPデータがある場合は追加
            if sp_detail or sp_raw:
                card_entry['sp_data'] = {
                    'detail': sp_detail,
                    'raw': sp_raw
                }
            
            # ソースデータとマージ情報も追加
            card_entry['source_data'] = source_data
            card_entry['merge_info'] = merge_info
            
            final_consolidated_data['cards'][card_number] = card_entry
            
        except Exception as e:
            print(f"カードデータ整理エラー {card_number}: {e}")
    
    # 統合JSONファイルを保存
    output_path = os.path.join(results_dir, output_file)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_consolidated_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== 統合JSONファイル生成完了 ===")
    print(f"生成ファイル: {output_path}")
    print(f"含まれるカード数: {len(final_consolidated_data['cards'])}件")
    print(f"SPデータあり: {sum(1 for card in final_consolidated_data['cards'].values() if card.get('has_sp_data', False))}件")

def re_ocr_all_sp_sections(results_dir, api_key):
    print("\n=== 全カードに対してSP部分の再OCRを実施します ===")
    card_files = [f for f in glob.glob(os.path.join(results_dir, '*.json')) if not (f.endswith('_sp.json') or f.endswith('_sp_raw.json'))]
    for card_file in card_files:
        try:
            with open(card_file, 'r', encoding='utf-8') as f:
                card_data = json.load(f)
            card_info = card_data.get('card_info', {})
            card_number = card_info.get('card_number', '')
            card_name = card_info.get('card_name', '')
            series_name = card_info.get('series', '')
            back_image_url = card_info.get('back_image_url', '')
            if card_info.get('type') != 'MS' or not back_image_url:
                continue
            print(f"SP再OCR: {card_number} {card_name}")
            sp_image_b64 = crop_sp_section(back_image_url, save_dir=results_dir, card_number=card_number, card_name=card_name)
            if sp_image_b64:
                data_url = f"data:image/jpeg;base64,{sp_image_b64}"
                sp_result = extract_sp_details_from_image(data_url, api_key)
                # --- SP生データを必ずJSONで保存（連番で上書き防止） ---
                def get_unique_path(base_path):
                    if not os.path.exists(base_path):
                        return base_path
                    base, ext = os.path.splitext(base_path)
                    i = 1
                    while True:
                        new_path = f"{base}_{i}{ext}"
                        if not os.path.exists(new_path):
                            return new_path
                        i += 1
                safe_number = sanitize_filename(card_number)
                safe_name = sanitize_filename(card_name)
                safe_series = sanitize_filename(series_name)
                if safe_series:
                    sp_raw_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sp_raw.json")
                    sp_parsed_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sp.json")
                else:
                    sp_raw_result_file = os.path.join(results_dir, f"{safe_number}_{safe_name}_sp_raw.json")
                    sp_parsed_result_file = os.path.join(results_dir, f"{safe_number}_{safe_name}_sp.json")
                sp_raw_result_file = get_unique_path(sp_raw_result_file)
                sp_parsed_result_file = get_unique_path(sp_parsed_result_file)
                sp_json_str = sp_result
                if "```json" in sp_result:
                    sp_json_str = sp_result.split("```json")[1].split("```", 1)[0].strip()
                elif "```" in sp_result:
                    sp_json_str = sp_result.split("```", 1)[1].strip()
                print(f"    → SP生データ保存先: {sp_raw_result_file}")
                print(f"    → SP生データ内容: {sp_result[:200]} ...")
                with open(sp_raw_result_file, 'w', encoding='utf-8') as f:
                    f.write(sp_result)
                print(f"    ✓ SP生データ保存: {sp_raw_result_file}")
                try:
                    sp_details = json.loads(sp_json_str)
                    print(f"    → SPパース済みデータ保存先: {sp_parsed_result_file}")
                    print(f"    → SPパース済みデータ内容: {json.dumps(sp_details, ensure_ascii=False)[:200]} ...")
                    with open(sp_parsed_result_file, 'w', encoding='utf-8') as f:
                        json.dump(sp_details, f, ensure_ascii=False, indent=2)
                    print(f"    ✓ SP詳細OCRパース済みデータ保存: {sp_parsed_result_file}")
                except Exception as sp_parse_error:
                    print(f"    ⚠ SP詳細OCR結果のパース失敗: {str(sp_parse_error)}")
            else:
                print(f"    ⚠ SP部分の切り取りに失敗")
        except Exception as e:
            print(f"  ✗ SP再OCR処理エラー: {card_file} {str(e)}")

def ocr_all_cards_basic(api_key_path, cards_dir='all_cards_list', results_dir='ocr_results'):
    """すべてのカードの基本OCRを実行し、SP以外のOCR結果をJsonで保存"""
    
    # 出力ディレクトリをクリーンアップ
    if os.path.exists(results_dir):
        print(f"出力ディレクトリ ({results_dir}) をクリーンアップしています...")
        shutil.rmtree(results_dir)
    os.makedirs(results_dir)
    print(f"出力ディレクトリ ({results_dir}) を作成しました。")
    
    # カードリストディレクトリのJSONファイルを取得
    if not os.path.exists(cards_dir):
        print(f"エラー: {cards_dir}ディレクトリが見つかりません")
        return
    
    json_files = glob.glob(os.path.join(cards_dir, '*.json'))
    if not json_files:
        print(f"エラー: {cards_dir}ディレクトリにJSONファイルが見つかりません")
        return
    
    print(f"見つかったJSONファイル数: {len(json_files)}")
    print(f"カードリストディレクトリ: {cards_dir}")
    print(f"OCR結果保存ディレクトリ: {results_dir}")
    
    # APIキー読み込み
    api_key = read_api_key(api_key_path)
    
    processed_count = 0
    skipped_count = 0
    error_count = 0
    
    for idx, json_file in enumerate(json_files, 1):
        try:
            # JSONファイルを読み込み
            with open(json_file, 'r', encoding='utf-8') as f:
                card_data = json.load(f)
            
            card_number = card_data.get('number', '')
            card_name = card_data.get('name', '')
            series_name = card_data.get('series', '')
            
            # 画像URLを取得（image_urlとurlの両方に対応）
            front_image_url = ''
            back_image_url = ''
            
            # 表面画像URL取得
            if 'front' in card_data:
                front_data = card_data['front']
                front_image_url = front_data.get('image_url', front_data.get('url', ''))
                # カード番号と名前も取得
                if not card_number:
                    card_number = front_data.get('number', '')
                if not card_name:
                    card_name = front_data.get('name', '')
                if not series_name:
                    series_name = front_data.get('series', '')
            
            # 裏面画像URL取得
            if 'back' in card_data:
                back_data = card_data['back']
                back_image_url = back_data.get('image_url', back_data.get('url', ''))
                # カード番号と名前も取得（表面で取得できていない場合）
                if not card_number:
                    card_number = back_data.get('number', '')
                if not card_name:
                    card_name = back_data.get('name', '')
                if not series_name:
                    series_name = back_data.get('series', '')
            
            # カード番号から_bを除去（裏面の場合）
            if card_number and card_number.endswith('_b'):
                card_number = card_number[:-2]
            
            # 裏面画像URLがない場合はスキップ
            if not back_image_url:
                print(f"[{idx}/{len(json_files)}] スキップ: 裏面画像なし - {card_number} {card_name}")
                skipped_count += 1
                continue
            
            print(f"[{idx}/{len(json_files)}] 基本OCR開始: {card_number} {card_name}")
            print(f"   表面URL: {front_image_url}")
            print(f"   裏面URL: {back_image_url}")
            
            try:
                # カード全体の基本OCR（SP部分は含まない）
                ocr_result = extract_structured_data_from_url(back_image_url, api_key)
                
                # OCR結果をパース
                ocr_json_str = ocr_result
                if "```json" in ocr_result:
                    ocr_json_str = ocr_result.split("```json")[1].split("```", 1)[0].strip()
                elif "```" in ocr_result:
                    ocr_json_str = ocr_result.split("```", 1)[1].strip()
                
                try:
                    ocr_data = json.loads(ocr_json_str)
                    
                    # 基本カード情報を構築
                    basic_card_info = {
                        'card_number': card_number,
                        'card_name': card_name,
                        'series': series_name,
                        'front_image_url': front_image_url,
                        'back_image_url': back_image_url,
                        'ocr_data': ocr_data,
                        'ocr_timestamp': datetime.now().isoformat(),
                        'ocr_type': 'basic'
                    }
                    
                    # ファイル名を生成
                    safe_number = sanitize_filename(card_number)
                    safe_name = sanitize_filename(card_name)
                    safe_series = sanitize_filename(series_name)
                    
                    if safe_series:
                        basic_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_basic.json")
                    else:
                        basic_result_file = os.path.join(results_dir, f"{safe_number}_{safe_name}_basic.json")
                    
                    # 基本OCR結果を保存
                    with open(basic_result_file, 'w', encoding='utf-8') as f:
                        json.dump(basic_card_info, f, ensure_ascii=False, indent=2)
                    
                    print(f"  ✓ 基本OCR成功: {card_number} {card_name}")
                    print(f"    カードタイプ: {ocr_data.get('type', 'Unknown')}")
                    processed_count += 1
                    
                except Exception as parse_error:
                    print(f"  ⚠ OCR結果のパース失敗: {str(parse_error)}")
                    error_count += 1
                    
            except Exception as e:
                error_message = str(e)
                print(f"  ✗ API呼び出し失敗: {card_number} {card_name} {error_message}")
                
                # APIクォータエラーの場合は特別な処理
                if "429" in error_message or "insufficient_quota" in error_message:
                    print(f"    ⚠ APIクォータの上限に達しました。処理を停止します。")
                    print(f"    対処法:")
                    print(f"    1. OpenAIのダッシュボードでクォータを確認: https://platform.openai.com/usage")
                    print(f"    2. 新しいAPIキーを使用")
                    print(f"    3. しばらく待ってから再実行")
                    break
                
                error_count += 1
            
        except Exception as e:
            print(f"  ✗ ファイル処理エラー: {json_file} - {str(e)}")
            error_count += 1
    
    print(f"\n=== 基本OCR処理完了 ===")
    print(f"処理成功: {processed_count}件")
    print(f"スキップ: {skipped_count}件")
    print(f"エラー: {error_count}件")
    
    return processed_count, error_count

def extract_ms_cards_from_basic_results(results_dir='ocr_results'):
    """基本OCR結果からMSカードを抽出"""
    print("\n=== MSカード抽出処理を開始します ===")
    
    # 基本OCR結果ファイルを検索
    basic_files = glob.glob(os.path.join(results_dir, '*_basic.json'))
    print(f"見つかった基本OCRファイル数: {len(basic_files)}")
    
    ms_cards = []
    other_cards = []
    
    for basic_file in basic_files:
        try:
            with open(basic_file, 'r', encoding='utf-8') as f:
                basic_data = json.load(f)
            
            ocr_data = basic_data.get('ocr_data', {})
            card_type = ocr_data.get('type', '')
            
            if card_type == 'MS':
                ms_cards.append({
                    'file_path': basic_file,
                    'card_number': basic_data.get('card_number', ''),
                    'card_name': basic_data.get('card_name', ''),
                    'series': basic_data.get('series', ''),
                    'back_image_url': basic_data.get('back_image_url', ''),
                    'ocr_data': ocr_data
                })
                print(f"  ✓ MSカード検出: {basic_data.get('card_number', '')} {basic_data.get('card_name', '')}")
            else:
                other_cards.append({
                    'file_path': basic_file,
                    'card_number': basic_data.get('card_number', ''),
                    'card_name': basic_data.get('card_name', ''),
                    'series': basic_data.get('series', ''),
                    'card_type': card_type
                })
                print(f"  - その他カード: {basic_data.get('card_number', '')} {basic_data.get('card_name', '')} ({card_type})")
                
        except Exception as e:
            print(f"  ✗ ファイル読み込みエラー: {basic_file} - {str(e)}")
    
    print(f"\n=== MSカード抽出完了 ===")
    print(f"MSカード数: {len(ms_cards)}件")
    print(f"その他カード数: {len(other_cards)}件")
    
    return ms_cards, other_cards

def apply_sp_ocr_to_ms_cards(ms_cards, api_key_path, results_dir='ocr_results'):
    """抽出したMSカードにSPのOCRフローを適用"""
    print("\n=== MSカードへのSP OCR処理を開始します ===")
    
    # APIキー読み込み
    api_key = read_api_key(api_key_path)
    
    processed_count = 0
    error_count = 0
    
    for idx, ms_card in enumerate(ms_cards, 1):
        card_number = ms_card['card_number']
        card_name = ms_card['card_name']
        series_name = ms_card['series']
        back_image_url = ms_card['back_image_url']
        
        print(f"[{idx}/{len(ms_cards)}] SP OCR開始: {card_number} {card_name}")
        
        try:
            # SP部分の切り取り
            sp_image_b64 = crop_sp_section(back_image_url, save_dir=results_dir, card_number=card_number, card_name=card_name)
            
            if sp_image_b64:
                # SP詳細OCR処理
                data_url = f"data:image/jpeg;base64,{sp_image_b64}"
                sp_result = extract_sp_details_from_image(data_url, api_key)
                
                # SP生データを保存
                safe_number = sanitize_filename(card_number)
                safe_name = sanitize_filename(card_name)
                safe_series = sanitize_filename(series_name)
                
                if safe_series:
                    sp_raw_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sp_raw.json")
                    sp_parsed_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sp.json")
                else:
                    sp_raw_result_file = os.path.join(results_dir, f"{safe_number}_{safe_name}_sp_raw.json")
                    sp_parsed_result_file = os.path.join(results_dir, f"{safe_number}_{safe_name}_sp.json")
                
                # 連番で上書き防止
                def get_unique_path(base_path):
                    if not os.path.exists(base_path):
                        return base_path
                    base, ext = os.path.splitext(base_path)
                    i = 1
                    while True:
                        new_path = f"{base}_{i}{ext}"
                        if not os.path.exists(new_path):
                            return new_path
                        i += 1
                
                sp_raw_result_file = get_unique_path(sp_raw_result_file)
                sp_parsed_result_file = get_unique_path(sp_parsed_result_file)
                
                # SP生データを保存
                print(f"    → SP生データ保存先: {sp_raw_result_file}")
                with open(sp_raw_result_file, 'w', encoding='utf-8') as f:
                    f.write(sp_result)
                print(f"    ✓ SP生データ保存: {sp_raw_result_file}")
                
                # SPパース済みデータを保存
                sp_json_str = sp_result
                if "```json" in sp_result:
                    sp_json_str = sp_result.split("```json")[1].split("```", 1)[0].strip()
                elif "```" in sp_result:
                    sp_json_str = sp_result.split("```", 1)[1].strip()
                
                try:
                    sp_details = json.loads(sp_json_str)
                    
                    # SP詳細データにカード情報を追加
                    sp_details.update({
                        'card_number': card_number,
                        'card_name': card_name,
                        'series': series_name,
                        'sp_ocr_timestamp': datetime.now().isoformat(),
                        'sp_ocr_type': 'detailed'
                    })
                    
                    print(f"    → SPパース済みデータ保存先: {sp_parsed_result_file}")
                    with open(sp_parsed_result_file, 'w', encoding='utf-8') as f:
                        json.dump(sp_details, f, ensure_ascii=False, indent=2)
                    print(f"    ✓ SP詳細OCRパース済みデータ保存: {sp_parsed_result_file}")
                    
                    processed_count += 1
                    
                except Exception as sp_parse_error:
                    print(f"    ⚠ SP詳細OCR結果のパース失敗: {str(sp_parse_error)}")
                    error_count += 1
            else:
                print(f"    ⚠ SP部分の切り取りに失敗")
                error_count += 1
                
        except Exception as e:
            error_message = str(e)
            print(f"  ✗ SP OCR処理エラー: {card_number} {card_name} {error_message}")
            
            # APIクォータエラーの場合は特別な処理
            if "429" in error_message or "insufficient_quota" in error_message:
                print(f"    ⚠ APIクォータの上限に達しました。処理を停止します。")
                break
            
            error_count += 1
    
    print(f"\n=== SP OCR処理完了 ===")
    print(f"処理成功: {processed_count}件")
    print(f"エラー: {error_count}件")
    
    return processed_count, error_count

def ocr_all_cards_new_workflow(api_key_path, cards_dir='all_cards_list', results_dir='ocr_results'):
    """新しい4段階OCRワークフローを実行"""
    print("=== 新しい4段階OCRワークフローを開始します ===")
    print("1. すべてのカードの基本OCRを実行")
    print("2. MSカードを抽出")
    print("3. MSカードにSP OCRを適用")
    print("4. PLカードのSQ関連スキルを分析")
    print()
    
    # 段階1: すべてのカードの基本OCR
    print("=== 段階1: すべてのカードの基本OCR ===")
    basic_processed, basic_errors = ocr_all_cards_basic(api_key_path, cards_dir, results_dir)
    
    if basic_processed == 0:
        print("基本OCRで処理されたカードがありません。処理を終了します。")
        return
    
    # 段階2: MSカードの抽出
    print("\n=== 段階2: MSカードの抽出 ===")
    ms_cards, other_cards = extract_ms_cards_from_basic_results(results_dir)
    
    # 段階3: MSカードへのSP OCR適用
    if len(ms_cards) > 0:
        print("\n=== 段階3: MSカードへのSP OCR適用 ===")
        sp_processed, sp_errors = apply_sp_ocr_to_ms_cards(ms_cards, api_key_path, results_dir)
    else:
        print("\n=== 段階3: MSカードへのSP OCR適用 ===")
        print("MSカードが見つかりませんでした。SP OCR処理をスキップします。")
        sp_processed, sp_errors = 0, 0
    
    # 段階4: PLカードのSQ関連スキル分析
    print("\n=== 段階4: PLカードのSQ関連スキル分析 ===")
    pl_cards = extract_pl_sq_skills_from_basic_results(results_dir)
    
    # SQ分析結果の保存
    if len(pl_cards) > 0:
        sq_saved = save_pl_sq_analysis_results(pl_cards, results_dir)
    else:
        sq_saved = 0
    
    print(f"\n=== 新しいOCRワークフロー完了 ===")
    print(f"基本OCR処理: {basic_processed}件")
    print(f"MSカード抽出: {len(ms_cards)}件")
    print(f"SP OCR処理: {sp_processed}件")
    print(f"PLカード分析: {len(pl_cards)}件")
    print(f"SQ分析結果保存: {sq_saved}件")
    print(f"基本OCRエラー: {basic_errors}件")
    print(f"SP OCRエラー: {sp_errors}件")

def analyze_pl_sq_skills(pl_card_data):
    """PLカードのSQ関連スキルを詳細分析"""
    pilot_skill = pl_card_data.get('pilot_skill', {})
    skill_effect = pilot_skill.get('effect', '')

    # SQ関連スキルの判定
    sq_keywords = ['SQゲージ', 'SQガージ', 'ゲージ', 'ガージ', 'SQUAD RUSH', 'SQUADRUSH', 'スクワッドラッシュ']
    has_sq_skill = any(keyword in skill_effect for keyword in sq_keywords)

    # --- 必ずhas_sq_skill, sq_skill_detailsを埋める ---
    sq_gauge_effect = None
    sq_max_effect = None
    squad_rush_effect = None
    sq_conditions = {
        'gauge_condition': None,
        'max_condition': None,
        'rush_condition': None,
        'other_conditions': []
    }
    sq_effects = {
        'gauge_effects': [],
        'max_effects': [],
        'rush_effects': [],
        'other_effects': []
    }
    # SQゲージ効果の抽出
    gauge_patterns = [
        r'SQゲージ[^。]*',
        r'SQガージ[^。]*',
        r'ゲージ[^。]*',
        r'ガージ[^。]*'
    ]
    for pattern in gauge_patterns:
        match = re.search(pattern, skill_effect)
        if match:
            sq_gauge_effect = match.group()
            break
    # SQゲージ最大値効果の抽出
    max_patterns = [
        r'SQゲージが最大時[^。]*',
        r'SQガージが最大時[^。]*',
        r'ゲージが最大時[^。]*',
        r'ガージが最大時[^。]*',
        r'SQゲージ最大時[^。]*',
        r'SQガージ最大時[^。]*',
        r'ゲージ最大時[^。]*',
        r'ガージ最大時[^。]*',
        r'SQゲージが最大値の時[^。]*',
        r'SQガージが最大値の時[^。]*',
        r'ゲージが最大値の時[^。]*',
        r'ガージが最大値の時[^。]*',
        r'SQゲージ最大値の時[^。]*',
        r'SQガージ最大値の時[^。]*',
        r'ゲージ最大値の時[^。]*',
        r'ガージ最大値の時[^。]*'
    ]
    for pattern in max_patterns:
        match = re.search(pattern, skill_effect)
        if match:
            sq_max_effect = match.group().strip()
            if '最大' in sq_max_effect:
                sq_gauge_effect = None
            break
    # SQUAD RUSH効果の抽出
    rush_patterns = [
        r'SQUAD RUSH中[^。]*',
        r'SQUAD RUSH時[^。]*',
        r'SQUADRUSH中[^。]*',
        r'SQUADRUSH時[^。]*',
        r'スクワッドラッシュ中[^。]*',
        r'スクワッドラッシュ時[^。]*',
        r'SQUAD RUSHが発動[^。]*',
        r'SQUADRUSHが発動[^。]*',
        r'SQUAD RUSH発動[^。]*',
        r'SQUADRUSH発動[^。]*'
    ]
    for pattern in rush_patterns:
        match = re.search(pattern, skill_effect)
        if match:
            squad_rush_effect = match.group().strip()
            break
    # SQゲージ最大値条件の詳細分析
    if sq_max_effect:
        sq_conditions['max_condition'] = 'SQゲージが最大時'
        max_effect_patterns = [
            r'SQゲージが最大時[^。]*?、([^。]*?をアップする?[^。]*)',
            r'SQガージが最大時[^。]*?、([^。]*?をアップする?[^。]*)',
            r'ゲージが最大時[^。]*?、([^。]*?をアップする?[^。]*)',
            r'ガージが最大時[^。]*?、([^。]*?をアップする?[^。]*)',
            r'SQゲージ最大時[^。]*?、([^。]*?をアップする?[^。]*)',
            r'SQガージ最大時[^。]*?、([^。]*?をアップする?[^。]*)',
            r'ゲージ最大時[^。]*?、([^。]*?をアップする?[^。]*)',
            r'ガージ最大時[^。]*?、([^。]*?をアップする?[^。]*)'
        ]
        for pattern in max_effect_patterns:
            match = re.search(pattern, skill_effect)
            if match:
                effect_text = match.group(1).strip()
                if effect_text and effect_text not in sq_effects['max_effects']:
                    sq_effects['max_effects'].append(effect_text)
                break
    # SQUAD RUSH条件の詳細分析
    if squad_rush_effect:
        rush_condition_patterns = [
            r'(SQUAD RUSH中)',
            r'(SQUAD RUSH時)',
            r'(SQUADRUSH中)',
            r'(SQUADRUSH時)',
            r'(スクワッドラッシュ中)',
            r'(スクワッドラッシュ時)'
        ]
        for pattern in rush_condition_patterns:
            match = re.search(pattern, squad_rush_effect)
            if match:
                sq_conditions['rush_condition'] = match.group(1)
                break
        rush_effect_patterns = [
            r'SQUAD RUSH中[^。]*?、([^。]*?をアップする?[^。]*)',
            r'SQUAD RUSH時[^。]*?、([^。]*?をアップする?[^。]*)',
            r'SQUADRUSH中[^。]*?、([^。]*?をアップする?[^。]*)',
            r'SQUADRUSH時[^。]*?、([^。]*?をアップする?[^。]*)'
        ]
        for pattern in rush_effect_patterns:
            match = re.search(pattern, skill_effect)
            if match:
                effect_text = match.group(1).strip()
                if effect_text and effect_text not in sq_effects['rush_effects']:
                    sq_effects['rush_effects'].append(effect_text)
                break
    # SQゲージ一般条件の詳細分析
    if sq_gauge_effect and not sq_max_effect:
        gauge_condition_patterns = [
            r'(SQゲージ[^時]*時)',
            r'(SQガージ[^時]*時)',
            r'(ゲージ[^時]*時)',
            r'(ガージ[^時]*時)'
        ]
        for pattern in gauge_condition_patterns:
            match = re.search(pattern, sq_gauge_effect)
            if match:
                sq_conditions['gauge_condition'] = match.group(1)
                break
    # その他の条件を抽出（SQ関連を除外）
    other_condition_patterns = [
        r'([^。]*?時[^。]*)',
        r'([^。]*?中[^。]*)',
        r'([^。]*?の時[^。]*)'
    ]
    for pattern in other_condition_patterns:
        matches = re.findall(pattern, skill_effect)
        for match in matches:
            match = match.strip()
            if (match and 
                'SQ' not in match and 
                'ゲージ' not in match and 
                'ガージ' not in match and
                match not in sq_conditions['other_conditions']):
                sq_conditions['other_conditions'].append(match)
    # その他の効果を抽出（SQ関連を除外）
    effect_patterns = [
        r'([^。]*?をアップする?[^。]*)',
        r'([^。]*?アップ[^。]*)',
        r'([^。]*?強化[^。]*)'
    ]
    for pattern in effect_patterns:
        matches = re.findall(pattern, skill_effect)
        for match in matches:
            match = match.strip()
            if (match and 
                match not in sq_effects['max_effects'] and 
                match not in sq_effects['rush_effects'] and
                match not in sq_effects['other_effects'] and
                'SQ' not in match and
                'ゲージ' not in match and
                'ガージ' not in match):
                sq_effects['other_effects'].append(match)
    # SQUAD RUSH発動時条件・効果の抽出
    rush_trigger_condition = None
    rush_trigger_effects = []
    rush_trigger_patterns_direct = [
        r'SQUAD RUSH発動中[、:：]?(.*?)(。|\n|$)',
        r'SQUADRUSH発動中[、:：]?(.*?)(。|\n|$)',
        r'スクワッドラッシュ発動中[、:：]?(.*?)(。|\n|$)'
    ]
    for pattern in rush_trigger_patterns_direct:
        match = re.search(pattern, skill_effect)
        if match:
            rush_trigger_condition = 'SQUAD RUSH発動中'
            effect_text = match.group(1).strip()
            if effect_text and effect_text not in rush_trigger_effects:
                rush_trigger_effects.append(effect_text)
            break
    if not rush_trigger_condition:
        rush_trigger_patterns = [
            r'(SQUAD RUSHが発動[^。]*)',
            r'(SQUADRUSHが発動[^。]*)',
            r'(SQUAD RUSH発動[^。]*)',
            r'(SQUADRUSH発動[^。]*)',
            r'(スクワッドラッシュが発動[^。]*)',
            r'(スクワッドラッシュ発動[^。]*)'
        ]
        for pattern in rush_trigger_patterns:
            match = re.search(pattern, skill_effect)
            if match:
                rush_trigger_condition = match.group(1)
                break
        if rush_trigger_condition:
            effect_patterns = [
                r'、([^。]*?をアップする?[^。]*)',
                r'、([^。]*?アップ[^。]*)',
                r'、([^。]*?強化[^。]*)'
            ]
            for pattern in effect_patterns:
                match = re.search(pattern, rush_trigger_condition)
                if match:
                    effect_text = match.group(1).strip()
                    if effect_text and effect_text not in rush_trigger_effects:
                        rush_trigger_effects.append(effect_text)
                    break
    sq_conditions['rush_trigger_condition'] = rush_trigger_condition
    sq_effects['rush_trigger_effects'] = rush_trigger_effects
    # --- ここまで詳細分析 ---
    pilot_skill.update({
        'has_sq_skill': has_sq_skill,
        'sq_skill_details': {
            'sq_gauge_effect': sq_gauge_effect,
            'sq_max_effect': sq_max_effect,
            'squad_rush_effect': squad_rush_effect,
            'sq_conditions': sq_conditions,
            'sq_effects': sq_effects
        }
    })
    return pl_card_data

def extract_pl_sq_skills_from_basic_results(results_dir='ocr_results'):
    """基本OCR結果からPLカードを抽出し、SQ関連スキルを詳細分析"""
    print("\n=== PLカードのSQ関連スキル分析を開始します ===")
    
    # 基本OCR結果ファイルを検索
    basic_files = glob.glob(os.path.join(results_dir, '*_basic.json'))
    print(f"見つかった基本OCRファイル数: {len(basic_files)}")
    
    pl_cards = []
    analyzed_count = 0
    
    for basic_file in basic_files:
        try:
            with open(basic_file, 'r', encoding='utf-8') as f:
                basic_data = json.load(f)
            
            ocr_data = basic_data.get('ocr_data', {})
            card_type = ocr_data.get('type', '')
            
            if card_type == 'PL':
                # PLカードのSQ関連スキルを分析
                analyzed_data = analyze_pl_sq_skills(ocr_data)
                
                pl_card_info = {
                    'file_path': basic_file,
                    'card_number': basic_data.get('card_number', ''),
                    'card_name': basic_data.get('card_name', ''),
                    'series': basic_data.get('series', ''),
                    'ocr_data': analyzed_data,
                    'raw': basic_data.get('raw', None)  # rawデータを追加
                }
                
                pl_cards.append(pl_card_info)
                
                # 分析結果を表示
                pilot_skill = analyzed_data.get('pilot_skill', {})
                has_sq_skill = pilot_skill.get('has_sq_skill', False)
                sq_details = pilot_skill.get('sq_skill_details', {})
                
                print(f"  ✓ PLカード分析: {basic_data.get('card_number', '')} {basic_data.get('card_name', '')}")
                print(f"    SQ関連スキル: {'あり' if has_sq_skill else 'なし'}")
                
                if has_sq_skill:
                    print(f"    SQゲージ効果: {sq_details.get('sq_gauge_effect', 'なし')}")
                    print(f"    SQ最大値効果: {sq_details.get('sq_max_effect', 'なし')}")
                    print(f"    SQUAD RUSH効果: {sq_details.get('squad_rush_effect', 'なし')}")
                
                analyzed_count += 1
                
        except Exception as e:
            print(f"  ✗ ファイル読み込みエラー: {basic_file} - {str(e)}")
    
    print(f"\n=== PLカードSQ関連スキル分析完了 ===")
    print(f"分析対象PLカード数: {analyzed_count}件")
    print(f"SQ関連スキルあり: {sum(1 for card in pl_cards if card['ocr_data'].get('pilot_skill', {}).get('has_sq_skill', False))}件")
    
    return pl_cards

def save_pl_sq_analysis_results(pl_cards, results_dir='ocr_results'):
    """PLカードのSQ関連スキル分析結果を保存"""
    print("\n=== PLカードSQ関連スキル分析結果の保存 ===")
    
    saved_count = 0
    
    for pl_card in pl_cards:
        try:
            card_number = pl_card['card_number']
            card_name = pl_card['card_name']
            series_name = pl_card['series']
            analyzed_data = pl_card['ocr_data']
            raw_ocr = pl_card.get('raw', None)
            # ファイル名を生成
            safe_number = sanitize_filename(card_number)
            safe_name = sanitize_filename(card_name)
            safe_series = sanitize_filename(series_name)
            if safe_series:
                sq_analysis_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sq_analysis.json")
            else:
                sq_analysis_file = os.path.join(results_dir, f"{safe_number}_{safe_name}_sq_analysis.json")
            # 分析結果を保存
            sq_analysis_data = {
                'card_number': card_number,
                'card_name': card_name,
                'series': series_name,
                'sq_analysis_timestamp': datetime.now().isoformat(),
                'sq_analysis_type': 'detailed',
                'pilot_skill': analyzed_data.get('pilot_skill', {}),
                'full_ocr_data': analyzed_data
            }
            if raw_ocr is not None:
                sq_analysis_data['raw'] = raw_ocr
            with open(sq_analysis_file, 'w', encoding='utf-8') as f:
                json.dump(sq_analysis_data, f, ensure_ascii=False, indent=2)
            saved_count += 1
            
        except Exception as e:
            print(f"  ✗ SQ分析結果保存エラー: {card_number} {card_name} - {str(e)}")
    
    print(f"\n=== SQ分析結果保存完了 ===")
    print(f"保存成功: {saved_count}件")
    
    return saved_count

def main():
    parser = argparse.ArgumentParser(description='カード画像のOCR処理とデータ統合')
    parser.add_argument('--inputdir', default='all_cards_list', help='入力カードリストディレクトリ (デフォルト: all_cards_list)')
    parser.add_argument('--outputdir', default='ocr_results', help='OCR結果保存ディレクトリ (デフォルト: ocr_results)')
    
    args = parser.parse_args()
    
    # APIキーをデフォルトファイルから読み込み
    api_key_path = 'APIkey.txt'
    try:
        api_key = read_api_key(api_key_path)
        print(f"APIキーを読み込みました: {api_key_path}")
    except FileNotFoundError:
        print(f"エラー: APIキーファイル '{api_key_path}' が見つかりません")
        return
    except Exception as e:
        print(f"エラー: APIキーの読み込みに失敗しました: {e}")
        return
    
    print("=== 新しい4段階OCRワークフローを開始します ===")
    print("1. すべてのカードの基本OCRを実行")
    print("2. MSカードを抽出")
    print("3. MSカードにSP OCRを適用")
    print("4. PLカードのSQ関連スキルを分析")
    print()
    
    # 新しい4段階OCRワークフローを実行
    ocr_all_cards_new_workflow(api_key_path, args.inputdir, args.outputdir)
    
    print("\n=== すべての処理が完了しました ===")
    print(f"結果は {args.outputdir} ディレクトリに保存されています")

if __name__ == "__main__":
    main()