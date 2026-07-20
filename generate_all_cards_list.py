import os
import json
import requests
from bs4 import BeautifulSoup
import re

SERIES_LIST_PATH = 'series_data/series_list.json'
OUTPUT_DIR = 'all_cards_list'
ALL_CARDS_JSON = 'all_cards.json'
FRONT_CARDS_PATH = 'front_cards.json'
BACK_CARDS_PATH = 'back_cards.json'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def fetch_all_cards():
    series_list = load_json(SERIES_LIST_PATH)
    urls = [s['url'] for s in series_list if 'url' in s]
    card_images = []
    processed_cards = set()
    for url in urls:
        print(f"[シリーズ取得] {url}")
        try:
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            links = soup.find_all('a', onclick='javascript:imgBack(this);')
            for link in links:
                img = link.find('img', class_='front')
                if img:
                    src = img.get('src', '')
                    if src and ('card' in src.lower() or 'gundam' in src.lower()):
                        if not src.startswith('http'):
                            src = 'https://www.gundam-ab.com' + src
                        card_number = src.split('/')[-1].split('.')[0]
                        if card_number not in processed_cards:
                            processed_cards.add(card_number)
                            card_name = img.get('alt', card_number)
                            # 裏面のURLを取得
                            back_src = src.replace('front', 'back')
                            card_info = {
                                'front': {
                                    'url': src,
                                    'number': card_number,
                                    'name': card_name
                                },
                                'back': {
                                    'url': back_src,
                                    'number': card_number,
                                    'name': card_name
                                }
                            }
                            print(f"[LOG] name: {card_name} | number: {card_number} | front_url: {src} | back_url: {back_src}")
                            card_images.append(card_info)
        except Exception as e:
            print(f"[ERROR] {url}: {str(e)}")
    card_images.sort(key=lambda x: x['front']['number'])
    return card_images

def main():
    ensure_output_dir()
    # front_cards.jsonとback_cards.jsonの両方を読み込む
    with open(FRONT_CARDS_PATH, encoding='utf-8') as f:
        front_cards = json.load(f)["cards"]
    with open(BACK_CARDS_PATH, encoding='utf-8') as f:
        back_cards = json.load(f)["cards"]
    
    # カード情報を統合
    all_cards = []
    for front_card in front_cards:
        card_number = front_card['number']
        # 対応する裏面カードを探す（_bを除去して比較）
        back_card = next((card for card in back_cards if card['number'].replace('_b', '') == card_number), None)
        
        if back_card:
            card_info = {
                'front': front_card,
                'back': back_card
            }
        else:
            # 裏面カードが見つからない場合は、表面のみの情報を使用
            card_info = {
                'front': front_card,
                'back': None
            }
        
        all_cards.append(card_info)
    
    for card in all_cards:
        # ファイル名に使えない文字をアンダースコアに
        safe_name = card['front']['name'].replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_').replace(' ', '_')
        safe_number = card['front']['number'].replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_').replace(' ', '_')
        file_name = f"{safe_number}_{safe_name}.json"
        out_path = os.path.join(OUTPUT_DIR, file_name)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(card, f, ensure_ascii=False, indent=2)
    
    # 全カードまとめjson
    all_cards_path = os.path.join(OUTPUT_DIR, ALL_CARDS_JSON)
    with open(all_cards_path, 'w', encoding='utf-8') as f:
        json.dump(all_cards, f, ensure_ascii=False, indent=2)
    print(f"{len(all_cards)}件のカードデータ（表面＋裏面）を保存しました。")

if __name__ == '__main__':
    main() 