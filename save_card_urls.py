import requests
from bs4 import BeautifulSoup
import json
import os

def fetch_card_urls():
    # 各弾のシリーズID
    series_ids = {
        # FQシリーズ
        'FQ01': '529015',
        'FQ02': '529016',
        'FQ03': '529017',
        'FQ04': '529018',
        # UTシリーズ
        'UT01': '529019',
        'UT02': '529020',
        'UT03': '529021',
        'UT04': '529022',
        'UT05': '529023',
        'UT06': '529024',
        # その他の弾
        'AB01': '529001',
        'AB02': '529002',
        'AB03': '529003',
        'AB04': '529004',
        'AB05': '529005',
        'AB06': '529006',
        'AB07': '529007',
        'AB08': '529008',
        'AB09': '529009',
        'AB10': '529010',
        'AB11': '529011',
        'AB12': '529012',
        'AB13': '529013',
        'AB14': '529014'
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    front_cards = []
    back_cards = []
    
    try:
        # 各弾のカードを取得
        for series_name, series_id in series_ids.items():
            print(f"処理中: {series_name}")
            url = f'https://www.gundam-ab.com/cardlist/?series={series_id}'
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            processed_cards = set()
            
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if src and ('card' in src.lower() or 'gundam' in src.lower()):
                    if not src.startswith('http'):
                        src = 'https://www.gundam-ab.com' + src
                    
                    # カード番号を抽出
                    card_number = src.split('/')[-1].split('.')[0]
                    
                    if card_number not in processed_cards:
                        processed_cards.add(card_number)
                        
                        # カード名を取得
                        card_name = ''
                        parent_div = img.find_parent('div', class_='card-name')
                        if parent_div:
                            card_name = parent_div.get_text(strip=True)
                        else:
                            # 代替方法：alt属性から取得
                            card_name = img.get('alt', '').strip()
                        
                        card_info = {
                            'url': src,
                            'number': card_number,
                            'name': card_name,
                            'series': series_name
                        }
                        
                        # 裏面かどうかを判定して適切なリストに追加
                        if card_number.endswith('_b'):
                            back_cards.append(card_info)
                            print(f"裏面カード追加: {card_name} ({card_number})")
                        else:
                            front_cards.append(card_info)
                            print(f"表面カード追加: {card_name} ({card_number})")
        
        # 結果をJSONファイルに保存
        # 表面カード
        front_output_file = 'front_cards.json'
        with open(front_output_file, 'w', encoding='utf-8') as f:
            json.dump({'cards': front_cards}, f, ensure_ascii=False, indent=2)
        
        # 裏面カード
        back_output_file = 'back_cards.json'
        with open(back_output_file, 'w', encoding='utf-8') as f:
            json.dump({'cards': back_cards}, f, ensure_ascii=False, indent=2)
        
        print(f"\n表面カード {len(front_cards)} 枚を {front_output_file} に保存しました。")
        print(f"裏面カード {len(back_cards)} 枚を {back_output_file} に保存しました。")
        return True
        
    except Exception as e:
        print(f"エラー: {str(e)}")
        return False

if __name__ == '__main__':
    fetch_card_urls() 