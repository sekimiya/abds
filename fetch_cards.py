import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
from urllib.parse import urljoin, urlparse

def fetch_cards_for_series(series_url, series_id, series_label):
    """シリーズページからカード情報を取得（表面・裏面両方）"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        print(f"シリーズ {series_label} のページを取得中...")
        res = requests.get(series_url, headers=headers)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        # カード情報を格納する辞書（カード番号をキーとする）
        cards_dict = {}
        
        # カード画像を探す（より具体的な検索）
        card_images = soup.find_all("img", src=re.compile(r'/images/cardlist/card/.*\.(jpg|jpeg|png|gif)', re.I))
        
        for img in card_images:
            alt = img.get("alt", "")
            src = img.get("src", "")
            
            if not alt or not src:
                continue
                
            # srcからカード番号を抽出
            # 例: /images/cardlist/card/AB01-001.jpg?v8 -> AB01-001
            # 例: /images/cardlist/card/AB01-001_b.jpg?v8 -> AB01-001
            card_number_match = re.search(r'/([A-Za-z0-9\-]+)(?:_b)?\.(jpg|jpeg|png|gif)', src)
            if not card_number_match:
                continue
                
            number = card_number_match.group(1)
            name = alt  # alt属性がカード名
            
            # 完全なURLに変換
            full_url = urljoin(series_url, src)
            
            img_class = img.get("class", [])
            if "back" in img_class:
                is_back = True
            elif "front" in img_class:
                is_back = False
            else:
                is_back = "_b" in src.lower()
            
            # カード番号が既に存在する場合は更新、存在しない場合は新規作成
            if number not in cards_dict:
                cards_dict[number] = {
                    "number": number,
                    "name": name,
                    "series": series_label,
                    "front": {
                        "image_url": ""
                    },
                    "back": {
                        "image_url": ""
                    }
                }
            else:
                # 既存のカードの場合、nameが空の場合は設定
                if not cards_dict[number]["name"]:
                    cards_dict[number]["name"] = name
            
            # 表面か裏面のURLを設定（上書きではなく、空の場合のみ設定）
            if is_back:
                if not cards_dict[number]["back"]["image_url"]:
                    cards_dict[number]["back"]["image_url"] = full_url
            else:
                if not cards_dict[number]["front"]["image_url"]:
                    cards_dict[number]["front"]["image_url"] = full_url
        
        return list(cards_dict.values())
        
    except Exception as e:
        print(f"Error fetching cards for series {series_label}: {str(e)}")
        return []

def save_card_data(card_data, all_cards_list_dir):
    """カード情報を個別のJSONファイルとして保存"""
    try:
        # 裏面画像URLが空の場合は自動で推定
        if not card_data.get('back', {}).get('image_url', ''):
            front_url = card_data.get('front', {}).get('image_url', '')
            if front_url:
                # 表面URLから裏面URLを推定
                # 例: .../AB01-001.jpg?v8 -> .../AB01-001_b.jpg?v8
                back_url = front_url.replace('.jpg', '_b.jpg').replace('.jpeg', '_b.jpeg').replace('.png', '_b.png').replace('.gif', '_b.gif')
                card_data['back']['image_url'] = back_url
        
        # ファイル名に使用できない文字を置換
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', card_data['name'])
        safe_series = re.sub(r'[<>:"/\\|?*]', '_', card_data['series'])
        filename = f"{card_data['number']}_{safe_series}_{safe_name}.json"
        filepath = os.path.join(all_cards_list_dir, filename)
        
        # ファイルを保存
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(card_data, f, ensure_ascii=False, indent=2)
            
        return True
    except Exception as e:
        print(f"Error saving card data for {card_data['number']}: {str(e)}")
        return False

def main():
    # シリーズ情報を読み込む
    try:
        with open('series_data/series_list.json', 'r', encoding='utf-8') as f:
            series_list = json.load(f)
        print(f"シリーズリストを読み込みました: {len(series_list)}個のシリーズ")
    except Exception as e:
        print(f"シリーズリストの読み込みに失敗しました: {str(e)}")
        return
    
    # all_cards_listディレクトリを作成
    all_cards_list_dir = 'all_cards_list'
    os.makedirs(all_cards_list_dir, exist_ok=True)
    
    total_cards = 0
    total_series = len(series_list)
    
    print(f"\n=== カード収集開始 ===")
    
    # 各シリーズのカードを収集
    for i, series in enumerate(series_list, 1):
        print(f"\n[{i}/{total_series}] シリーズ {series['label']} のカードを収集中...")
        
        try:
            # カード情報を取得（表面・裏面両方）
            cards = fetch_cards_for_series(series['url'], series['id'], series['label'])
            
            if cards:
                print(f"  {len(cards)}枚のカードを収集しました。")
                saved_count = 0
                
                for card in cards:
                    if save_card_data(card, all_cards_list_dir):
                        saved_count += 1
                
                total_cards += saved_count
                
                print(f"  ✓ {saved_count}枚のカードデータを保存しました。")
            else:
                print(f"  ⚠ カードが見つかりませんでした。")
                
        except Exception as e:
            print(f"  ✗ エラーが発生しました: {str(e)}")
        
        # サーバーに負荷をかけないように少し待機
        if i < total_series:
            time.sleep(1)
    
    print(f"\n=== カード収集完了 ===")
    print(f"合計 {total_cards} 枚のカードデータを {all_cards_list_dir} ディレクトリに保存しました。")
    print(f"処理したシリーズ数: {total_series}")

if __name__ == "__main__":
    main() 