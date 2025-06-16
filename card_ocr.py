import openai
import sys
import os

from openai import OpenAI

def read_api_key(file_path):
    with open(file_path, 'r') as f:
        return f.read().strip()

def extract_structured_data_from_url(image_url, api_key):
    client = OpenAI(api_key=api_key)

    prompt = """
この画像はアーセナルベースというカードゲームのカード画像です。
画像内の情報を正確に読み取り、以下のようなJSON形式で出力してください：

{
  "機体情報": {
    "コスト": number,
    "モデル番号": string,
    "名称": string,
    "頭頂高": string,
    "本体重量": string,
    "所属": string,
    "パイロット": string
  },
  "環境対応": {
    "地上": string,
    "宇宙": string,
    "砂漠": string,
    "水中": string
  },
  "ステータス": {
    "機動力": number,
    "遠距離攻撃": number,
    "近距離攻撃": number,
    "HP": number
  },
  "武装": {
    "MAIN": {
      "名称": string,
      "射程": number,
      "タイプ": string
    },
    "SUB": {
      "名称": string,
      "射程": number,
      "タイプ": string
    }
  },
  "MSアビリティ": string,
  "リンクアビリティ": [ { "条件": string, "効果": string } ],
  "スペシャルアタック": {
    "名称": string,
    "使用": string,
    "性能": {
      "単体": {
        "射程": number,
        "貫通": string,
        "射撃": number
      },
      "SPコスト": number,
      "威力": string
    },
    "説明": string
  },
  "インパクトエリア": {
    "色": string,
    "範囲": string
  },
  "著者情報": {
    "イラストレータ": string,
    "©": string,
    "製造国": string,
    "カード番号": string,
    "レア度": string
  }
}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "あなたは画像内の文字を読み取り、整ったJSONデータとして返すOCRアシスタントです。"},
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