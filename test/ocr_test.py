import openai
import sys
import os
import json
import re
import argparse
import time

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

def sanitize_filename(s):
    return re.sub(r'[\\/:*?"<>|\s]+', '_', s)

def save_result_to_file(filename, result_json):
    os.makedirs('ocr_results', exist_ok=True)
    file_path = os.path.join('ocr_results', filename)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)

def ocr_all_cards(all_cards_path, api_key_path):
    results_dir = 'ocr_results'
    os.makedirs(results_dir, exist_ok=True)
    with open(all_cards_path, encoding='utf-8') as f:
        all_cards = json.load(f)
    api_key = read_api_key(api_key_path)
    all_ocr_results = []
    for idx, card in enumerate(all_cards):
        card_number = card.get('number', 'unknown')
        card_name = card.get('name', 'unknown')
        image_url = card.get('url', '')
        print(f"[{idx+1}/{len(all_cards)}] OCR開始: {card_number} {card_name}")
        try:
            result = extract_structured_data_from_url(image_url, api_key)
            match = re.search(r"```json\s*([\s\S]+?)```", result)
            json_str = match.group(1) if match else result
            try:
                result_json = json.loads(json_str)
                print(f"[成功] {card_number} {card_name}")
            except Exception as e2:
                print(f"[JSONエラー] {card_name}: {e2}")
                result_json = {"error": str(e2), "raw": json_str}
        except Exception as e:
            print(f"[APIエラー] {card_name}: {e}")
            result_json = {"error": str(e), "url": image_url}
        filename = f"{sanitize_filename(card_number)}_{sanitize_filename(card_name)}.json"
        save_result_to_file(filename, result_json)
        all_ocr_results.append(result_json)
        time.sleep(1.2)
    with open(os.path.join(results_dir, 'all_ocr_results.json'), 'w', encoding='utf-8') as f:
        json.dump(all_ocr_results, f, ensure_ascii=False, indent=2)

def main():
    api_key_path = "APIKey.txt"
    default_url = "https://www.gundam-ab.com/images/cardlist/card/FQ01-001_b.jpg?v8"
    image_url = sys.argv[1] if len(sys.argv) > 1 else default_url
    match = re.search(r"([A-Z0-9\-]+_b)", image_url)
    card_name_guess = match.group(1) if match else "unknown"
    try:
        api_key = read_api_key(api_key_path)
        result = extract_structured_data_from_url(image_url, api_key)
        match_json = re.search(r"```json\s*([\s\S]+?)```", result)
        json_str = match_json.group(1) if match_json else result
        result_json = json.loads(json_str)
        card_name = result_json.get('name', card_name_guess)
        card_number = result_json.get('number', 'unknown')
        filename = f"{sanitize_filename(card_number)}_{sanitize_filename(card_name)}.json"
        save_result_to_file(filename, result_json)
        print("[完了] 識別・保存が完了しました。")
    except Exception as e:
        print(f"[エラー] {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', action='store_true', help='全カード一括OCR')
    args = parser.parse_args()
    if args.all:
        ocr_all_cards('all_cards_list/all_cards.json', 'APIKey.txt')
    else:
        main()
