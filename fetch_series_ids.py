import requests
from bs4 import BeautifulSoup
import os
import json

def fetch_all_series_ids():
    base_url = "https://www.gundam-ab.com/cardlist/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        res = requests.get(base_url, headers=headers)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        # selectタグを探す
        select = soup.find("select", {"name": "series"})
        if not select:
            print("シリーズ選択用の<select>タグが見つかりませんでした。")
            return []

        series_list = []
        for option in select.find_all("option"):
            value = option.get("value")
            label = option.text.strip()
            if value and value.isdigit():
                full_url = f"{base_url}?series={value}"
                series_list.append({
                    "id": value,
                    "url": full_url,
                    "label": label
                })

        return sorted(series_list, key=lambda x: int(x["id"]))
    except Exception as e:
        print(f"Error: {str(e)}")
        return []

# 実行例
if __name__ == "__main__":
    print("カードパックのIDとパック名を取得中...")
    all_series = fetch_all_series_ids()
    
    if all_series:
        print("\n見つかったシリーズ:")
        for s in all_series:
            print(f"シリーズID: {s['id']} / パック名: {s['label']} → {s['url']}")
        # ディレクトリ作成
        os.makedirs('series_data', exist_ok=True)
        # JSONとして保存
        with open('series_data/series_list.json', 'w', encoding='utf-8') as f:
            json.dump(all_series, f, ensure_ascii=False, indent=2)
        print('\nseries_data/series_list.json に保存しました。')
    else:
        print("シリーズIDの取得に失敗しました。") 