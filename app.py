from flask import Flask, render_template, request, jsonify, send_from_directory
import requests
from bs4 import BeautifulSoup
import os
import re
import json
import threading

app = Flask(__name__)

decks_file = 'decks.json'
decks_lock = threading.Lock()

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
    # カードデータを読み込む
    all_cards = []
    all_cards_dir = 'all_cards_list'
    if os.path.exists(all_cards_dir):
        card_files = [f for f in os.listdir(all_cards_dir) if f.endswith('.json')]
        print(f"カードファイル数: {len(card_files)}")
        for filename in card_files:
            try:
                with open(os.path.join(all_cards_dir, filename), 'r', encoding='utf-8') as f:
                    card_data = json.load(f)
                    all_cards.append(card_data)
            except Exception as e:
                print(f"カードファイル読み込みエラー {filename}: {str(e)}")
    else:
        print(f"ディレクトリが存在しません: {all_cards_dir}")
    
    print(f"読み込まれたカード数: {len(all_cards)}")
    
    # OCR結果を読み込む
    ocr_results = {}
    ocr_dir = 'ocr_results'
    if os.path.exists(ocr_dir):
        ocr_files = [f for f in os.listdir(ocr_dir) if f.endswith('.json')]
        print(f"OCRファイル数: {len(ocr_files)}")
        for filename in ocr_files:
            try:
                with open(os.path.join(ocr_dir, filename), 'r', encoding='utf-8') as f:
                    ocr_data = json.load(f)
                    base = filename.replace('.json', '')
                    
                    # カード番号を抽出
                    number_match = re.search(r'([A-Z0-9\-]{4,}-\d{2,4})', base)
                    if number_match:
                        number = number_match.group(1)
                        ocr_results[number] = ocr_data
            except Exception as e:
                print(f"OCRファイル読み込みエラー {filename}: {str(e)}")
    else:
        print(f"OCRディレクトリが存在しません: {ocr_dir}")
    
    print(f"OCR結果数: {len(ocr_results)}")
    
    # カードデータとOCRデータを突合
    result_cards = []
    for card in all_cards:
        card_number = card.get('number', '')
        ocr_data = ocr_results.get(card_number, {})
        
        # 表面画像URL生成
        front_image_url = ''
        # 1. カードデータのfront.image_urlを優先
        if 'front' in card and 'image_url' in card['front']:
            front_image_url = card['front']['image_url']
        # 2. OCRデータのfront.image_url
        elif 'front' in ocr_data and 'image_url' in ocr_data['front']:
            front_image_url = ocr_data['front']['image_url']
        # 3. OCRデータのimage_url（表面用）
        elif 'image_url' in ocr_data:
            front_image_url = ocr_data['image_url']
        # 4. カード番号から画像URLを生成
        if not front_image_url and card_number:
            front_image_url = f"https://www.gundam-ab.com/images/cardlist/card/{card_number}.jpg?v8"
        # 5. 裏面画像URLから表面画像URLを生成（_bを除去）
        if front_image_url and '_b' in front_image_url:
            front_image_url = front_image_url.replace('_b', '')
        
        # 裏面画像URL生成
        back_image_url = ''
        # 1. カードデータのback.image_urlを優先
        if 'back' in card and 'image_url' in card['back']:
            back_image_url = card['back']['image_url']
        # 2. OCRデータのback.image_url
        elif 'back' in ocr_data and 'image_url' in ocr_data['back']:
            back_image_url = ocr_data['back']['image_url']
        # 3. OCRデータのback_image_url
        elif 'back_image_url' in ocr_data:
            back_image_url = ocr_data['back_image_url']
        # 4. カード番号から裏面画像URLを生成
        if not back_image_url and card_number:
            back_image_url = f"https://www.gundam-ab.com/images/cardlist/card/{card_number}_b.jpg?v8"
        
        # frontとbackオブジェクトを構築
        front_obj = {}
        if front_image_url:
            front_obj['image_url'] = front_image_url
        
        back_obj = {}
        if back_image_url:
            back_obj['image_url'] = back_image_url
        
        card_info = {
            'url': front_image_url,  # デフォルトURL（表面）
            'number': card_number,
            'name': card.get('name', ''),
            'category': card.get('category', 'MS'),
            'ocr_data': ocr_data,
            'front': front_obj,
            'back': back_obj,
            'series': card.get('series', '')
        }
        
        # カード番号からシリーズコードを生成（SQリンク用）
        if card_number:
            series_match = re.match(r'([A-Z]{2}\d{2})', card_number)
            if series_match:
                card_info['series'] = series_match.group(1)
        
        result_cards.append(card_info)
    
    print(f"結果カード数: {len(result_cards)}")
    result_cards.sort(key=lambda x: x['number'])
    return jsonify({'success': True, 'images': result_cards})

@app.route('/ocr_results/<path:filename>')
def serve_ocr_results(filename):
    return send_from_directory('ocr_results', filename)

# --- デッキ投稿API ---
@app.route('/post_deck', methods=['POST'])
def post_deck():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data received'}), 400
    deck_name = data.get('deck_name', '').strip()
    comment = data.get('comment', '').strip()
    cards = data.get('cards', [])
    if not deck_name or not cards:
        return jsonify({'success': False, 'error': 'デッキ名とカード構成は必須です'}), 400
    deck_entry = {
        'deck_name': deck_name,
        'comment': comment,
        'cards': cards,
        'timestamp': data.get('timestamp')
    }
    with decks_lock:
        if os.path.exists(decks_file):
            with open(decks_file, 'r', encoding='utf-8') as f:
                try:
                    decks = json.load(f)
                except Exception:
                    decks = []
        else:
            decks = []
        decks.append(deck_entry)
        with open(decks_file, 'w', encoding='utf-8') as f:
            json.dump(decks, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True, 'message': 'デッキを投稿しました'})

# --- デッキ一覧API ---
@app.route('/decks', methods=['GET'])
def get_decks():
    if not os.path.exists(decks_file):
        return jsonify({'success': True, 'decks': []})
    with open(decks_file, 'r', encoding='utf-8') as f:
        try:
            decks = json.load(f)
        except Exception:
            decks = []
    return jsonify({'success': True, 'decks': decks})

@app.route('/decks.html')
def decks_html():
    return render_template('decks.html')

@app.route('/search')
def search():
    return render_template('search.html')

@app.route('/mobile')
def mobile():
    return render_template('mobile.html')

@app.route('/summary')
def summary():
    return render_template('summary.html')

@app.route('/series_list')
def series_list():
    try:
        with open('series_data/series_list.json', 'r', encoding='utf-8') as f:
            series_data = json.load(f)
        return jsonify(series_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001) 