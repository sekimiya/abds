import os
import json
import glob

def analyze_all_cards_list():
    """all_cards_listディレクトリの詳細分析"""
    all_cards_list_dir = 'all_cards_list'
    
    if not os.path.exists(all_cards_list_dir):
        print(f"エラー: {all_cards_list_dir}ディレクトリが見つかりません")
        return
    
    # 全JSONファイルを取得
    json_files = glob.glob(os.path.join(all_cards_list_dir, '*.json'))
    print(f"全JSONファイル数: {len(json_files)}")
    
    # 裏面画像URLの有無を調査
    with_back_image = 0
    without_back_image = 0
    error_files = 0
    
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                card_data = json.load(f)
            
            back_image_url = card_data.get('back', {}).get('image_url', '')
            
            if back_image_url:
                with_back_image += 1
            else:
                without_back_image += 1
                # 裏面画像がないカードの例を表示
                if without_back_image <= 5:
                    card_number = card_data.get('number', '')
                    card_name = card_data.get('name', '')
                    print(f"  裏面画像なし: {card_number} {card_name}")
                    
        except Exception as e:
            error_files += 1
            print(f"  エラーファイル: {json_file} - {str(e)}")
    
    print(f"\n=== 分析結果 ===")
    print(f"裏面画像あり: {with_back_image}件")
    print(f"裏面画像なし: {without_back_image}件")
    print(f"エラーファイル: {error_files}件")
    print(f"合計: {len(json_files)}件")
    
    # 裏面画像がないカードの詳細分析
    if without_back_image > 0:
        print(f"\n=== 裏面画像がないカードの詳細 ===")
        count = 0
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    card_data = json.load(f)
                
                back_image_url = card_data.get('back', {}).get('image_url', '')
                if not back_image_url:
                    card_number = card_data.get('number', '')
                    card_name = card_data.get('name', '')
                    series = card_data.get('series', '')
                    print(f"{count+1}. {card_number} {card_name} ({series})")
                    count += 1
                    if count >= 20:  # 最初の20件のみ表示
                        print(f"... 他 {without_back_image - 20} 件")
                        break
                        
            except Exception as e:
                continue

if __name__ == "__main__":
    analyze_all_cards_list() 