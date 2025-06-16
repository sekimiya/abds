import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re

def fetch_cards_for_series(series_url, series_id, series_label):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        res = requests.get(series_url, headers=headers)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        cards = []
        # ページ全体からimgタグを抽出
        for img in soup.find_all("img"):
            alt = img.get("alt", "")
            src = img.get("src", "")
            # カード番号とカード名が半角スペースで区切られているもののみ対象
            parts = alt.split(" ", 1)
            if len(parts) == 2 and src:
                number, name = parts
                # カード番号が英数字とハイフンで構成されているか簡易チェック
                if re.match(r'^[A-Z0-9\-]+$', number):
                    card_info = {
                        "url": src,
                        "number": number,
                        "name": name,
                        "series": series_label
                    }
                    cards.append(card_info)
        
        return cards
    except Exception as e:
        print(f"Error fetching cards for series {series_label}: {str(e)}")
        return []

def main():
    # シリーズ情報を読み込む
    with open('series_data/series_list.json', 'r', encoding='utf-8') as f:
        series_list = json.load(f)
    
    all_cards = []
    
    # 各シリーズのカードを収集
    for series in series_list:
        print(f"シリーズ {series['label']} のカードを収集中...")
        cards = fetch_cards_for_series(series['url'], series['id'], series['label'])
        if cards:
            print(f"  {len(cards)}枚のカードを収集しました。")
        all_cards.extend(cards)
        time.sleep(1)  # サーバーに負荷をかけないように少し待機
    
    # カードデータを保存
    os.makedirs('series_data', exist_ok=True)
    with open('series_data/cards.json', 'w', encoding='utf-8') as f:
        json.dump({"cards": all_cards}, f, ensure_ascii=False, indent=2)
    
    print(f"\n合計 {len(all_cards)} 枚のカードデータを収集しました。")
    print("series_data/cards.json に保存しました。")

if __name__ == "__main__":
    main() 