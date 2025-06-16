import json
from ocr_module import CardOCR
import os
import time

def print_card_info(card_info):
    """カード情報を整形して出力"""
    print("\n=== カード情報 ===")
    print(f"カード名: {card_info['name']}")
    if card_info['cost']:
        print(f"コスト: {card_info['cost']}")
    if card_info['power']:
        print(f"パワー: {card_info['power']}")
    print("\n=== カードテキスト ===")
    print(card_info['text'])
    print("==================\n")

def process_cards():
    # OCRインスタンスの作成
    ocr = CardOCR('APIKey.txt')
    
    # カードURL
    card_url = "https://www.gundam-ab.com/images/cardlist/card/FQ01-001_b.jpg?v8"
    
    # 結果を保存するディレクトリの作成
    results_dir = 'ocr_results'
    os.makedirs(results_dir, exist_ok=True)
    
    print("カード情報の読み取りを開始します...")
    try:
        # カード情報の読み取り
        result = ocr.read_card_info(card_url)
        
        if result:
            # 結果をJSONファイルとして保存
            output_file = os.path.join(results_dir, "card_info.json")
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"保存完了: {output_file}")
            
            # ターミナルに情報を出力
            print_card_info(result)
        else:
            print("読み取り失敗")
        
    except Exception as e:
        print(f"エラー: {str(e)}")

if __name__ == "__main__":
    process_cards() 