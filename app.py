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
    # all_cards_list/all_cards.jsonからカードデータを取得
    try:
        with open('all_cards_list/all_cards.json', 'r', encoding='utf-8') as f:
            all_cards = json.load(f)
        print(f"Loaded {len(all_cards)} cards from all_cards.json")
    except Exception as e:
        print(f"Error loading all_cards.json: {str(e)}")
        return jsonify({'success': False, 'error': f'all_cards.jsonの読み込みエラー: {str(e)}'})

    # OCR結果も読み込む
    ocr_results = {}
    ocr_dir = 'ocr_results'
    if os.path.exists(ocr_dir):
        ocr_files = [f for f in os.listdir(ocr_dir) if f.endswith('_ocr.json')]
        print(f"Found {len(ocr_files)} OCR files")
        for filename in ocr_files:
            try:
                with open(os.path.join(ocr_dir, filename), 'r', encoding='utf-8') as f:
                    ocr_data = json.load(f)
                    # ファイル名からカード番号とカード名を抽出
                    base = filename.replace('_ocr.json', '')
                    ocr_results[base] = ocr_data
            except Exception as e:
                print(f"OCRファイル読み込みエラー {filename}: {str(e)}")
    else:
        print(f"OCR directory {ocr_dir} not found")

    print(f"Loaded {len(ocr_results)} OCR results")

    # カードデータとOCRデータを統合
    card_images = []
    for card in all_cards:
        card_number = card['front']['number']
        card_name = card['front']['name']
        key = f'{card_number}_{card_name}'
        ocr_data = ocr_results.get(key)
        
        card_info = {
            'url': card['front']['url'],  # 後方互換性のため残す
            'number': card_number,
            'name': card['front']['name'],
            'category': ocr_data.get('type', 'MS') if ocr_data else 'MS',
            'ocr_data': ocr_data,
            'front': card['front'],  # 表面データを追加
            'back': card['back']     # 裏面データを追加
        }
        card_images.append(card_info)

    card_images.sort(key=lambda x: x['number'])
    print(f"Returning {len(card_images)} cards with OCR data")
    if card_images:
        print(f"First card example: {card_images[0]['number']} - {card_images[0]['name']} - OCR data: {card_images[0]['ocr_data'] is not None}")
    
    return jsonify({'success': True, 'images': card_images})

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001) 