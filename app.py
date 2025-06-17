from flask import Flask, render_template, request, jsonify, send_from_directory
import requests
from bs4 import BeautifulSoup
import os
import re
import json

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/index2.html')
def index2():
    return render_template('index2.html')

@app.route('/photo')
def photo():
    return render_template('photo.html')

@app.route('/illustrator')
def illustrator():
    return render_template('illustrator.html')

@app.route('/fetch_cards')
def fetch_cards():
    # series_data/series_list.jsonからURLリストを取得
    try:
        with open('series_data/series_list.json', 'r', encoding='utf-8') as f:
            series_list = json.load(f)
        urls = [s['url'] for s in series_list if 'url' in s]
    except Exception as e:
        return jsonify({'success': False, 'error': f'series_list.jsonの読み込みエラー: {str(e)}'})

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        card_images = []
        processed_cards = set()
        
        for url in urls:
            response = requests.get(url, headers=headers)
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
                            card_info = {
                                'url': src,
                                'number': card_number,
                                'name': card_name,
                                'category': 'MS'  # デフォルトでMSカテゴリ
                            }
                            card_images.append(card_info)
        card_images.sort(key=lambda x: x['number'])
        return jsonify({'success': True, 'images': card_images})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/ocr_results/<path:filename>')
def serve_ocr_results(filename):
    return send_from_directory('ocr_results', filename)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001) 