import openai
import sys

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
  ]
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
  }
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

def main():
    api_key_path = "APIKey.txt"
    default_url = "https://www.gundam-ab.com/images/cardlist/card/FQ01-001_b.jpg?v8"

    image_url = sys.argv[1] if len(sys.argv) > 1 else default_url

    try:
        api_key = read_api_key(api_key_path)
        result = extract_structured_data_from_url(image_url, api_key)
        print("✅ 構造化されたデータ:\n")
        print(result)
        with open("card_data.json", "w", encoding="utf-8") as f:
            f.write(result)
    except Exception as e:
        print(f"❌ エラーが発生しました: {str(e)}")

if __name__ == "__main__":
    main()