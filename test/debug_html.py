import requests
from bs4 import BeautifulSoup
import re

def debug_series_html(series_url, series_label):
    """シリーズページのHTMLをデバッグ"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        print(f"=== {series_label} のデバッグ ===")
        res = requests.get(series_url, headers=headers)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        # カード画像を探す
        card_images = soup.find_all("img", src=re.compile(r'/images/cardlist/card/.*\.(jpg|jpeg|png|gif)', re.I))
        
        print(f"カード画像の総数: {len(card_images)}")
        
        # 最初の5枚の詳細を表示
        for i, img in enumerate(card_images[:5]):
            alt = img.get("alt", "")
            src = img.get("src", "")
            img_class = img.get("class", [])
            
            print(f"\n{i+1}. Alt: {alt}")
            print(f"   Src: {src}")
            print(f"   Class: {img_class}")
            
            # カード番号を抽出
            card_number_match = re.search(r'/([A-Z0-9\-]+)\.(jpg|jpeg|png|gif)', src)
            if card_number_match:
                number = card_number_match.group(1)
                print(f"   カード番号: {number}")
                
                # 表面・裏面判定
                if "back" in img_class:
                    print(f"   → 裏面 (class判定)")
                elif "front" in img_class:
                    print(f"   → 表面 (class判定)")
                elif "_b" in src.lower():
                    print(f"   → 裏面 (_b判定)")
                else:
                    print(f"   → 表面 (_b判定)")
        
        return True
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return False

# テスト実行
debug_series_html('https://www.gundam-ab.com/cardlist/?series=529001', 'SEASON:01') 