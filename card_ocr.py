import openai
import sys
import os
import json
import re
import argparse

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

def save_result_to_file(card_name, result_json):
    # ファイル名に使えない文字をアンダースコアに変換
    safe_name = card_name.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_').replace(' ', '_')
    os.makedirs('ocr_results', exist_ok=True)
    file_path = os.path.join('ocr_results', f"{safe_name}_ocr.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)

def sanitize_filename(s):
    return s.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_').replace(' ', '_')

def ocr_all_cards(all_cards_path, api_key_path):
    import time
    # OCR結果保存ディレクトリ
    results_dir = 'ocr_results'
    os.makedirs(results_dir, exist_ok=True)
    # 全カードリスト読み込み
    with open(all_cards_path, encoding='utf-8') as f:
        all_cards = json.load(f)
    # APIキー
    api_key = read_api_key(api_key_path)
    all_ocr_results = []
    for idx, card in enumerate(all_cards):
        card_number = card['front']['number']
        card_name = card['front']['name']
        # 裏面のURLを使用
        image_url = card['back']['url'] if card['back'] else None
        
        if not image_url:
            print(f"[スキップ] 裏面なし: {card_number} {card_name}")
            continue
            
        print(f"[{idx+1}/{len(all_cards)}] OCR開始: {card_number} {card_name} {image_url}")
        try:
            result = extract_structured_data_from_url(image_url, api_key)
            print(f"[APIレスポンス] {result}")
            # コードブロックを除去
            json_str = result
            if "```json" in result:
                # コードブロックからJSONを抽出
                json_str = result.split("```json")[1].split("```")[0].strip()
            elif "```" in result:
                # 通常のコードブロックからJSONを抽出
                json_str = result.split("```")[1].strip()
            
            # Jsonとしてパース
            try:
                result_json = json.loads(json_str)
                # 必要なフィールドが存在するか確認
                if 'type' in result_json and 'name' in result_json:
                    print(f"[成功] OCR成功: {card_number} {card_name}")
                else:
                    print(f"[警告] 不完全なデータ: {card_number} {card_name}")
                    result_json = {"warning": "不完全なデータ", "number": card_number, "name": card_name, "url": image_url, "raw": json_str}
            except Exception as e2:
                print(f"[エラー] JSONパース失敗: {card_number} {card_name} {str(e2)}")
                result_json = {"error": str(e2), "number": card_number, "name": card_name, "url": image_url, "raw": json_str}
        except Exception as e:
            print(f"[エラー] API呼び出し失敗: {card_number} {card_name} {str(e)}")
            result_json = {"error": str(e), "number": card_number, "name": card_name, "url": image_url}
        # ファイル名生成
        safe_number = sanitize_filename(card_number)
        safe_name = sanitize_filename(card_name)
        out_path = os.path.join(results_dir, f"{safe_number}_{safe_name}_ocr.json")
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(result_json, f, ensure_ascii=False, indent=2)
        all_ocr_results.append(result_json)
        time.sleep(1.2)  # API制限対策
    # 全OCRまとめjson
    with open(os.path.join(results_dir, 'all_ocr_results.json'), 'w', encoding='utf-8') as f:
        json.dump(all_ocr_results, f, ensure_ascii=False, indent=2)
    print(f"全{len(all_cards)}件のOCR処理が完了しました。")

def main():
    api_key_path = "APIKey.txt"
    default_url = "https://www.gundam-ab.com/images/cardlist/card/FQ01-001_b.jpg?v8"

    image_url = sys.argv[1] if len(sys.argv) > 1 else default_url

    # カード名（ファイル名候補）をURLから推測（例: AB01-001_b など）
    match = re.search(r"([A-Z0-9\-]+_b)", image_url)
    card_name_guess = match.group(1) if match else "unknown"
    print(f"--- 識別開始 ---\nカード名（推定）: {card_name_guess}\nカードURL: {image_url}\n")

    try:
        api_key = read_api_key(api_key_path)
        print("[進捗] OpenAI APIへリクエスト中...")
        result = extract_structured_data_from_url(image_url, api_key)
        print("[進捗] 構造化データ取得完了\n")
        print("✅ 構造化されたデータ:\n")
        print(result)
        # JSONとしてパース
        result_json = json.loads(result)
        # カード名取得
        card_name = result_json.get('name', card_name_guess)
        print(f"[進捗] ファイル保存: ocr_results/{card_name}_ocr.json\n")
        save_result_to_file(card_name, result_json)
        print("[完了] 識別・保存が完了しました。\n")
    except Exception as e:
        print(f"❌ エラーが発生しました: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', action='store_true', help='全カード一括OCR')
    args = parser.parse_args()
    if args.all:
        ocr_all_cards('all_cards_list/all_cards.json', 'APIKey.txt')
    else:
        main()