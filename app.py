from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import os
import re

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/fetch_cards')
def fetch_cards():
    # 複数のURLを定義
    urls = [
        'https://www.gundam-ab.com/cardlist/',
        'https://www.gundam-ab.com/cardlist/?series=FQ01'
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        card_images = []
        processed_cards = set()
        
        for url in urls:
            print(f"Fetching cards from: {url}")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # デバッグ情報：ページのタイトルを表示
            print(f"Page title: {soup.title.string if soup.title else 'No title found'}")
            
            # カードリンクを探す
            links = soup.find_all('a', onclick='javascript:imgBack(this);')
            print(f"Found {len(links)} card links")
            
            for link in links:
                img = link.find('img', class_='front')
                if img:
                    src = img.get('src', '')
                    if src and ('card' in src.lower() or 'gundam' in src.lower()):
                        if not src.startswith('http'):
                            src = 'https://www.gundam-ab.com' + src
                        
                        # カード番号と分類を抽出
                        card_number = src.split('/')[-1].split('.')[0]
                        
                        if card_number not in processed_cards:
                            processed_cards.add(card_number)
                            
                            # カード名を取得
                            card_name = img.get('alt', card_number)
                            
                            card_info = {
                                'url': src,
                                'number': card_number,
                                'name': card_name,
                                'category': 'MS'  # デフォルトでMSカテゴリ
                            }
                            card_images.append(card_info)
                            print(f"Added card: {card_number} - {card_name}")
        
        # カード番号でソート
        card_images.sort(key=lambda x: x['number'])
        print(f"Total cards collected: {len(card_images)}")
        
        return jsonify({'success': True, 'images': card_images})
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True, port=5001) 