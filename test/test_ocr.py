from ocr_module import CardOCR

def test_single_card():
    # OCRインスタンスの作成
    ocr = CardOCR()
    
    # テスト用のカード画像URL（ガンダムアーセナルベースのカード画像）
    test_url = 'https://www.gundam-ab.com/images/cardlist/card/FQ01-001_b.jpg?v8'
    
    # カード情報の読み取り
    print("カード情報を読み取っています...")
    card_analysis = ocr.analyze_card(test_url)
    
    if card_analysis:
        print("\n=== カード情報 ===")
        print(f"名前: {card_analysis['basic_info']['name']}")
        print(f"コスト: {card_analysis['basic_info']['cost']}")
        print(f"パワー: {card_analysis['basic_info']['power']}")
        print(f"カードタイプ: {card_analysis['type']}")
        print(f"レアリティ: {card_analysis['rarity']}")
        print("\n=== 効果 ===")
        for effect in card_analysis['effects']:
            print(f"- {effect}")
    else:
        print("カード情報の読み取りに失敗しました。")

if __name__ == '__main__':
    test_single_card() 