import json
import os
import card_ocr
import time

def load_back_cards():
    with open('back_cards.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data['cards']

def process_back_cards():
    # APIキーの読み込み
    api_key = card_ocr.read_api_key("APIKey.txt")
    
    # 裏面カードの読み込み
    back_cards = load_back_cards()
    
    # 結果を保存するリスト
    results = []
    
    # 出力ディレクトリの作成
    os.makedirs('ocr_results', exist_ok=True)
    
    print(f"裏面カード {len(back_cards)} 枚の処理を開始します...")
    
    # 各カードを処理
    for i, card in enumerate(back_cards, 1):
        print(f"\n[{i}/{len(back_cards)}] 処理中: {card['name']} ({card['number']})")
        
        try:
            # OCR処理の実行
            result = card_ocr.extract_structured_data_from_url(card['url'], api_key)
            
            if result:
                # カード情報を追加
                card_info = {
                    'card_number': card['number'],
                    'card_name': card['name'],
                    'series': card['series'],
                    'ocr_result': result
                }
                
                # 結果を表示
                print("\nOCR結果:")
                print(f"カード番号: {card_info['card_number']}")
                print(f"カード名: {card_info['card_name']}")
                print(f"シリーズ: {card_info['series']}")
                print("テキスト:")
                print(card_info['ocr_result'])
                
                # 個別のカード結果を保存
                card_output_file = f'ocr_results/{card["number"]}_ocr.json'
                with open(card_output_file, 'w', encoding='utf-8') as f:
                    json.dump(card_info, f, ensure_ascii=False, indent=2)
                
                # 結果をリストに追加
                results.append(card_info)
                
                # 進捗を表示
                print(f"\n進捗: {i}/{len(back_cards)} 完了")
                print(f"結果を {card_output_file} に保存しました")
                
                # API制限を考慮して少し待機
                time.sleep(1)
            else:
                print(f"警告: {card['number']} のOCR処理に失敗しました")
        
        except Exception as e:
            print(f"エラー: {card['number']} の処理中にエラーが発生しました - {str(e)}")
    
    # すべての結果をまとめて保存
    output_file = 'ocr_results/all_back_cards_ocr.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({'cards': results}, f, ensure_ascii=False, indent=2)
    
    print(f"\n処理完了: {len(results)} 枚のカード情報を {output_file} に保存しました")

if __name__ == '__main__':
    process_back_cards() 