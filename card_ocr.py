import openai
import sys
import os
import json
import re
import argparse
import glob

from openai import OpenAI

def read_api_key(file_path):
    with open(file_path, 'r') as f:
        return f.read().strip()

def extract_structured_data_from_url(image_url, api_key):
    client = OpenAI(api_key=api_key)

    prompt = """
この画像は「アーセナルベース」というカードゲームのカードです。
以下のいずれかの形式で構造化されたJSONを出力してください。

カードには「MS（モビルスーツ）」と「PL（パイロット）」の2種類があります。
読み取った情報に応じて、対応する形式を選んでください。

---

【MSカードのJSON構造】
{
  "type": "MS",
  "name": "string",
  "model": "string",
  "cost": integer,
  "category": "string",
  "pilot": "string",
  "stats": {
    "height": "string",
    "weight": "string",
    "mobility": integer,
    "ranged_attack": integer,
    "melee_attack": integer,
    "hp": integer
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
      "range": integer,
      "type": "string"
    },
    "sub": {
      "name": "string",
      "range": integer,
      "type": "string"
    }
  },
  "ms_ability": {
    "name": "string",
    "cost": integer,
    "description": "string"
  },
  "special_attack": {
    "name": "string",
    "target": "string",
    "range": integer,
    "power": integer,
    "description": "string"
  },
  "link_abilities": [
    {
      "name": "string",
      "condition": "string",
      "effect": "string"
    }
  ],
  "illust": "string"
}

---

【PLカードのJSON構造】
{
  "type": "PL",
  "name": "string",
  "english_name": "string",
  "cost": integer,
  "category": "string",
  "age": integer,
  "height": "string",
  "units": ["string"],
  "pl_skill": {
    "name": "string",
    "trigger": "string",
    "effect": "string"
  },
  "link_abilities": [
    {
      "name": "string",
      "condition": "string",
      "effect": "string"
    }
  ],
  "stats": {
    "mobility": integer,
    "ranged_attack": integer,
    "melee_attack": integer,
    "hp": integer
  },
  "illust": "string"
}

出力は必ずこのJSON形式に従ってください。
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "あなたは画像からカード情報を抽出してJSONに変換するOCRアシスタントです。"},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]}
        ],
        max_tokens=4096,
        temperature=0.0,
    )

    return response.choices[0].message.content

def save_result_to_file(card_number, card_name, result_json, series_name=""):
    # ファイル名に使えない文字をアンダースコアに変換
    safe_number = sanitize_filename(card_number)
    safe_name = sanitize_filename(card_name)
    safe_series = sanitize_filename(series_name)
    
    # 収録パック+カードナンバー+カード名.jsonの形式
    if safe_series:
        filename = f"{safe_series}_{safe_number}_{safe_name}.json"
    else:
        filename = f"{safe_number}_{safe_name}.json"
    
    os.makedirs('ocr_results', exist_ok=True)
    file_path = os.path.join('ocr_results', filename)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)

def sanitize_filename(s):
    return s.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_').replace(' ', '_')

def ocr_back_cards_from_all_cards_list(api_key_path):
    """all_cards_listディレクトリのJSONファイルから裏面画像を読み込み、OCRを実行"""
    import time
    
    # OCR結果保存ディレクトリ
    results_dir = 'ocr_results'
    os.makedirs(results_dir, exist_ok=True)
    
    # all_cards_listディレクトリのJSONファイルを取得
    all_cards_list_dir = 'all_cards_list'
    if not os.path.exists(all_cards_list_dir):
        print(f"エラー: {all_cards_list_dir}ディレクトリが見つかりません")
        return
    
    json_files = glob.glob(os.path.join(all_cards_list_dir, '*.json'))
    if not json_files:
        print(f"エラー: {all_cards_list_dir}ディレクトリにJSONファイルが見つかりません")
        return
    
    print(f"見つかったJSONファイル数: {len(json_files)}")
    
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
            back_image_url = card_data.get('back', {}).get('image_url', '')
            
            # 裏面画像URLがない場合はスキップ
            if not back_image_url:
                print(f"[{idx}/{len(json_files)}] スキップ: 裏面画像なし - {card_number} {card_name}")
                skipped_count += 1
                continue
            
            # 既にOCR結果が存在する場合はスキップ
            safe_number = sanitize_filename(card_number)
            safe_name = sanitize_filename(card_name)
            safe_series = sanitize_filename(series_name)
            if safe_series:
                ocr_result_file = os.path.join('ocr_results', f"{safe_series}_{safe_number}_{safe_name}.json")
            else:
                ocr_result_file = os.path.join('ocr_results', f"{safe_number}_{safe_name}.json")
            if os.path.exists(ocr_result_file):
                print(f"[{idx}/{len(json_files)}] スキップ: 既存のOCR結果 - {card_number} {card_name}")
                skipped_count += 1
                continue
            
            print(f"[{idx}/{len(json_files)}] OCR開始: {card_number} {card_name}")
            print(f"   URL: {back_image_url}")
            
            try:
                result = extract_structured_data_from_url(back_image_url, api_key)
                
                # コードブロックを除去
                json_str = result
                if "```json" in result:
                    json_str = result.split("```json")[1].split("```")[0].strip()
                elif "```" in result:
                    json_str = result.split("```")[1].strip()
                
                # JSONとしてパース
                try:
                    result_json = json.loads(json_str)
                    # 必要なフィールドが存在するか確認
                    if 'type' in result_json and 'name' in result_json:
                        print(f"  ✓ OCR成功: {card_number} {card_name}")
                        result_json['card_number'] = card_number
                        result_json['card_name'] = card_name
                        result_json['image_url'] = back_image_url
                    else:
                        print(f"  ⚠ 不完全なデータ: {card_number} {card_name}")
                        result_json = {
                            "warning": "不完全なデータ", 
                            "card_number": card_number, 
                            "card_name": card_name, 
                            "image_url": back_image_url, 
                            "raw": json_str
                        }
                except Exception as e2:
                    print(f"  ✗ JSONパース失敗: {card_number} {card_name} {str(e2)}")
                    result_json = {
                        "error": str(e2), 
                        "card_number": card_number, 
                        "card_name": card_name, 
                        "image_url": back_image_url, 
                        "raw": json_str
                    }
                
                # 結果を保存
                save_result_to_file(card_number, card_name, result_json, series_name)
                processed_count += 1
                
            except Exception as e:
                print(f"  ✗ API呼び出し失敗: {card_number} {card_name} {str(e)}")
                error_result = {
                    "error": str(e), 
                    "card_number": card_number, 
                    "card_name": card_name, 
                    "image_url": back_image_url
                }
                save_result_to_file(card_number, card_name, error_result, series_name)
                error_count += 1
            
            # API制限対策
            time.sleep(1.2)
            
        except Exception as e:
            print(f"  ✗ ファイル処理エラー: {json_file} {str(e)}")
            error_count += 1
    
    print(f"\n=== OCR処理完了 ===")
    print(f"処理済み: {processed_count}件")
    print(f"スキップ: {skipped_count}件")
    print(f"エラー: {error_count}件")
    print(f"合計: {len(json_files)}件")

def main():
    parser = argparse.ArgumentParser(description='カードの裏面画像からOCRを実行')
    parser.add_argument('--api-key', default='APIkey.txt', help='APIキーファイルのパス')
    parser.add_argument('--mode', choices=['back'], default='back', help='OCRモード')
    
    args = parser.parse_args()
    
    if args.mode == 'back':
        ocr_back_cards_from_all_cards_list(args.api_key)
    else:
        print("サポートされていないモードです")

if __name__ == "__main__":
    main()