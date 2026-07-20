import requests
from bs4 import BeautifulSoup
import os
import json
from ocr_module import CardOCR

def fetch_card_urls():
    """サイトからカード画像のURLを取得"""
    url = 'https://www.gundam-ab.com/cardlist/'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        card_urls = []
        processed_cards = set()
        
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src and ('card' in src.lower() or 'gundam' in src.lower()):
                if not src.startswith('http'):
                    src = 'https://www.gundam-ab.com' + src
                
                # カード番号と分類を抽出
                card_number = src.split('/')[-1].split('.')[0]
                
                if card_number not in processed_cards:
                    processed_cards.add(card_number)
                    card_urls.append({
                        'url': src,
                        'number': card_number
                    })
        
        return card_urls
    except Exception as e:
        print(f"Error fetching card URLs: {str(e)}")
        return []

def process_ocr_for_cards(force_regenerate=False):
    """カード画像に対してOCR処理を実行"""
    # APIキーファイルの存在チェック
    api_key_file = 'APIKey.txt'
    if not os.path.exists(api_key_file):
        print("警告: APIKey.txtが見つかりません。")
        print("APIKey.txtファイルを作成して、OpenAI APIキーを設定してください。")
        return
    
    # OCRインスタンスの作成
    ocr = CardOCR(api_key_file)
    
    # カードURLを取得
    print("カードURLを取得中...")
    card_urls = fetch_card_urls()
    print(f"取得したカード数: {len(card_urls)}")
    
    # OCR結果を保存するディレクトリ
    ocr_results_dir = 'ocr_results'
    os.makedirs(ocr_results_dir, exist_ok=True)
    
    # 既存のOCR結果ファイルをチェック
    existing_results = set()
    if os.path.exists(ocr_results_dir):
        for filename in os.listdir(ocr_results_dir):
            if filename.endswith('_ocr.json'):
                card_number = filename.replace('_ocr.json', '')
                existing_results.add(card_number)
    
    print(f"既存のOCR結果: {len(existing_results)}件")
    
    if force_regenerate:
        print("⚠️  強制再生成モード: 既存のOCR結果を上書きします")
    
    # 各カードに対してOCR処理を実行
    skipped_count = 0
    processed_count = 0
    failed_count = 0
    
    for i, card in enumerate(card_urls, 1):
        print(f"処理中 ({i}/{len(card_urls)}): {card['number']}")
        
        # 既存のOCR結果がある場合はスキップ（強制再生成モードでない場合）
        if not force_regenerate and card['number'] in existing_results:
            print(f"  ⏭ スキップ: {card['number']} (既存のOCR結果があります)")
            skipped_count += 1
            continue
        
        try:
            # OCR処理を実行
            card_analysis = ocr.analyze_card(card['url'])
            
            if card_analysis:
                # 結果をJSONファイルに保存
                result_file = os.path.join(ocr_results_dir, f"{card['number']}_ocr.json")
                with open(result_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'number': card['number'],
                        'url': card['url'],
                        'analysis': card_analysis
                    }, f, ensure_ascii=False, indent=2)
                print(f"  ✓ OCR完了: {card['number']}")
                processed_count += 1
            else:
                print(f"  ✗ OCR失敗: {card['number']}")
                failed_count += 1
                
        except Exception as e:
            print(f"  ✗ エラー: {card['number']} - {str(e)}")
            failed_count += 1
    
    print("\n=== OCR処理結果 ===")
    print(f"スキップ: {skipped_count}件")
    print(f"処理完了: {processed_count}件")
    print(f"処理失敗: {failed_count}件")
    print(f"合計: {len(card_urls)}件")
    print("OCR処理が完了しました。")

def generate_card_list():
    """カードリストを生成（OCR結果を含む）"""
    # カードURLを取得
    card_urls = fetch_card_urls()
    
    # OCR結果を読み込み
    ocr_results = {}
    ocr_results_dir = 'ocr_results'
    if os.path.exists(ocr_results_dir):
        for filename in os.listdir(ocr_results_dir):
            if filename.endswith('_ocr.json'):
                try:
                    with open(os.path.join(ocr_results_dir, filename), 'r', encoding='utf-8') as f:
                        ocr_data = json.load(f)
                        ocr_results[ocr_data['number']] = ocr_data['analysis']
                except Exception as e:
                    print(f"OCRファイル読み込みエラー {filename}: {str(e)}")
    
    # カード情報を統合
    card_images = []
    for card in card_urls:
        ocr_data = ocr_results.get(card['number'])
        
        if ocr_data:
            card_info = {
                'url': card['url'],
                'number': card['number'],
                'category': ocr_data['type'],
                'type': '',
                'cost': ocr_data['basic_info']['cost'],
                'power': ocr_data['basic_info']['power'],
                'rarity': ocr_data['rarity'],
                'effects': ocr_data['effects'],
                'name': ocr_data['basic_info']['name']
            }
        else:
            # OCRデータがない場合の基本情報
            card_info = {
                'url': card['url'],
                'number': card['number'],
                'category': '',
                'type': '',
                'cost': '',
                'power': '',
                'rarity': '',
                'effects': [],
                'name': ''
            }
        
        card_images.append(card_info)
    
    # 結果をJSONファイルに保存
    with open('card_list.json', 'w', encoding='utf-8') as f:
        json.dump(card_images, f, ensure_ascii=False, indent=2)
    
    print(f"カードリストを生成しました: {len(card_images)}枚")
    return card_images

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == 'ocr':
            print("OCR処理を開始します...")
            process_ocr_for_cards()
        elif command == 'ocr-force':
            print("OCR処理を強制再生成モードで開始します...")
            process_ocr_for_cards(force_regenerate=True)
        elif command == 'generate':
            print("カードリストを生成します...")
            generate_card_list()
        elif command == 'both':
            print("OCR処理とカードリスト生成を実行します...")
            process_ocr_for_cards()
            generate_card_list()
        elif command == 'both-force':
            print("OCR処理（強制再生成）とカードリスト生成を実行します...")
            process_ocr_for_cards(force_regenerate=True)
            generate_card_list()
        else:
            print("使用方法:")
            print("  python ocr_processor.py ocr          # OCR処理のみ")
            print("  python ocr_processor.py ocr-force    # OCR処理（強制再生成）")
            print("  python ocr_processor.py generate     # カードリスト生成のみ")
            print("  python ocr_processor.py both         # 両方実行")
            print("  python ocr_processor.py both-force   # 両方実行（強制再生成）")
    else:
        print("使用方法:")
        print("  python ocr_processor.py ocr          # OCR処理のみ")
        print("  python ocr_processor.py ocr-force    # OCR処理（強制再生成）")
        print("  python ocr_processor.py generate     # カードリスト生成のみ")
        print("  python ocr_processor.py both         # 両方実行")
        print("  python ocr_processor.py both-force   # 両方実行（強制再生成）") 