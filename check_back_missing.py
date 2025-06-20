import json
import os
import requests
from bs4 import BeautifulSoup
import re

def check_back_images_in_html(series_url, card_number):
    """HTMLから特定のカード番号の_b画像が存在するかチェック"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        res = requests.get(series_url, headers=headers)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        # そのカード番号の_b画像を探す
        back_images = soup.find_all("img", src=re.compile(f'{card_number}_b\\.(jpg|jpeg|png|gif)', re.I))
        
        return len(back_images) > 0, [img.get('src', '') for img in back_images]
    except Exception as e:
        print(f"Error checking HTML for {card_number}: {str(e)}")
        return False, []

def main():
    # all_cards_listディレクトリから裏面が空のカードを探す
    all_cards_list_dir = 'all_cards_list'
    
    if not os.path.exists(all_cards_list_dir):
        print("all_cards_listディレクトリが見つかりません")
        return
    
    # シリーズ情報を読み込む
    try:
        with open('series_data/series_list.json', 'r', encoding='utf-8') as f:
            series_list = json.load(f)
    except Exception as e:
        print(f"シリーズリストの読み込みに失敗しました: {str(e)}")
        return
    
    # シリーズURLの辞書を作成
    series_urls = {series['label']: series['url'] for series in series_list}
    
    missing_back_cards = []
    
    # 各JSONファイルをチェック
    for filename in os.listdir(all_cards_list_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(all_cards_list_dir, filename)
            
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    card_data = json.load(f)
                
                # 裏面URLが空かチェック
                if not card_data.get('back', {}).get('image_url', ''):
                    missing_back_cards.append({
                        'number': card_data['number'],
                        'name': card_data['name'],
                        'series': card_data['series'],
                        'filename': filename
                    })
                    
            except Exception as e:
                print(f"Error reading {filename}: {str(e)}")
    
    print(f"裏面画像が空のカード数: {len(missing_back_cards)}")
    print("\n=== 裏面画像が空のカード一覧 ===")
    
    # 最初の10件についてHTMLチェック
    for i, card in enumerate(missing_back_cards[:10]):
        print(f"\n{i+1}. {card['number']} - {card['name']} ({card['series']})")
        
        # そのシリーズのURLを取得
        series_url = series_urls.get(card['series'])
        if series_url:
            exists, src_list = check_back_images_in_html(series_url, card['number'])
            if exists:
                print(f"   ✓ HTMLに裏面画像が存在: {src_list}")
            else:
                print(f"   ✗ HTMLに裏面画像が存在しない")
        else:
            print(f"   ? シリーズURLが見つからない")
    
    if len(missing_back_cards) > 10:
        print(f"\n... 他 {len(missing_back_cards) - 10} 件のカードも裏面画像が空です")

if __name__ == "__main__":
    main() 