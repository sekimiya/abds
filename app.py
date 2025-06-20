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
    # all_cards_listディレクトリから個別のJSONファイルを読み込み
    all_cards = []
    all_cards_dir = 'all_cards_list'
    
    try:
        if not os.path.exists(all_cards_dir):
            print(f"Error: {all_cards_dir} directory not found")
            return jsonify({'success': False, 'error': f'{all_cards_dir}ディレクトリが見つかりません'})
        
        # 個別のJSONファイルを読み込み
        json_files = [f for f in os.listdir(all_cards_dir) if f.endswith('.json')]
        print(f"Found {len(json_files)} card files in {all_cards_dir}")
        
        for filename in json_files:
            try:
                with open(os.path.join(all_cards_dir, filename), 'r', encoding='utf-8') as f:
                    card_data = json.load(f)
                    all_cards.append(card_data)
            except Exception as e:
                print(f"Error loading {filename}: {str(e)}")
                continue
        
        print(f"Loaded {len(all_cards)} cards from individual files")
        
    except Exception as e:
        print(f"Error loading card data: {str(e)}")
        return jsonify({'success': False, 'error': f'カードデータの読み込みエラー: {str(e)}'})

    # OCR結果も読み込む
    ocr_results = {}
    ocr_dir = 'ocr_results'
    if os.path.exists(ocr_dir):
        ocr_files = [f for f in os.listdir(ocr_dir) if f.endswith('.json')]
        print(f"Found {len(ocr_files)} OCR files")
        for filename in ocr_files:
            try:
                with open(os.path.join(ocr_dir, filename), 'r', encoding='utf-8') as f:
                    ocr_data = json.load(f)
                    # ファイル名からカード番号とカード名を抽出
                    base = filename.replace('.json', '')
                    ocr_results[base] = ocr_data
            except Exception as e:
                print(f"OCRファイル読み込みエラー {filename}: {str(e)}")
    else:
        print(f"OCR directory {ocr_dir} not found")

    print(f"Loaded {len(ocr_results)} OCR results")

    # カードデータとOCRデータを統合
    card_images = []
    for card in all_cards:
        card_number = card.get('number', '')
        card_name = card.get('name', '')
        series_name = card.get('series', '')
        
        # OCRデータのキーを生成（収録パック+カードナンバー+カード名の形式）
        if series_name:
            ocr_key = f"{series_name}_{card_number}_{card_name}"
        else:
            ocr_key = f"{card_number}_{card_name}"
        
        ocr_data = ocr_results.get(ocr_key)
        
        # 画像URLを取得（front.image_urlを優先）
        image_url = card.get('front', {}).get('image_url', '')
        if not image_url:
            # 後方互換性のため、直接のurlフィールドも確認
            image_url = card.get('url', '')
        
        card_info = {
            'url': image_url,  # 画像URL
            'number': card_number,
            'name': card_name,
            'category': ocr_data.get('type', 'MS') if ocr_data else 'MS',
            'ocr_data': ocr_data,
            'front': card.get('front', {}),  # 表面データを追加
            'back': card.get('back', {}),     # 裏面データを追加
            'series': series_name  # 収録弾数情報を追加
        }
        card_images.append(card_info)
        
        # デバッグ: 最初の数枚のカードの情報を出力
        if len(card_images) <= 3:
            print(f"Debug - Card {len(card_images)}: {card_number} {card_name}")
            print(f"  Image URL: {image_url}")
            print(f"  Front data: {card.get('front', {})}")
            print(f"  OCR key: {ocr_key}")

    card_images.sort(key=lambda x: x['number'])
    print(f"Returning {len(card_images)} cards with OCR data")
    if card_images:
        print(f"First card example: {card_images[0]['number']} - {card_images[0]['name']}")
        print(f"First card URL: {card_images[0]['url']}")
        print(f"First card OCR data: {card_images[0]['ocr_data'] is not None}")
    
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