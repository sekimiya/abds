import requests
from bs4 import BeautifulSoup
import json
import re
import time
from urllib.parse import urljoin

def count_cards_in_series(series_url, series_label):
    """シリーズページのカード数をカウント"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        print(f"シリーズ {series_label} を解析中...")
        res = requests.get(series_url, headers=headers)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        # カード画像を探す
        card_images = soup.find_all("img", src=re.compile(r'/images/cardlist/card/.*\.(jpg|jpeg|png|gif)', re.I))
        
        # カード番号を抽出してユニークな数をカウント
        card_numbers = set()
        for img in card_images:
            src = img.get("src", "")
            if src:
                # カード番号を抽出（_bを含む場合も対応）
                card_number_match = re.search(r'/([A-Z0-9\-]+)(?:_b)?\.(jpg|jpeg|png|gif)', src)
                if card_number_match:
                    card_numbers.add(card_number_match.group(1))
        
        return len(card_numbers)
        
    except Exception as e:
        print(f"エラー: {series_label} - {str(e)}")
        return 0

def analyze_total_cards():
    """全シリーズのカード数を分析"""
    # シリーズ情報を読み込み
    try:
        with open('series_data/series_list.json', 'r', encoding='utf-8') as f:
            series_list = json.load(f)
        print(f"シリーズリストを読み込みました: {len(series_list)}個のシリーズ")
    except Exception as e:
        print(f"シリーズリストの読み込みに失敗しました: {str(e)}")
        return
    
    total_cards = 0
    series_results = []
    
    print(f"\n=== 全シリーズのカード数調査 ===")
    
    for i, series in enumerate(series_list, 1):
        series_label = series['label']
        series_url = series['url']
        
        card_count = count_cards_in_series(series_url, series_label)
        
        series_results.append({
            'label': series_label,
            'count': card_count,
            'url': series_url
        })
        
        total_cards += card_count
        
        print(f"[{i}/{len(series_list)}] {series_label}: {card_count}枚")
        
        # サーバーに負荷をかけないように少し待機
        if i < len(series_list):
            time.sleep(1)
    
    print(f"\n=== 調査結果 ===")
    print(f"合計カード数: {total_cards}枚")
    print(f"調査したシリーズ数: {len(series_list)}個")
    
    # カード数が多いシリーズTOP10を表示
    series_results.sort(key=lambda x: x['count'], reverse=True)
    print(f"\n=== カード数TOP10 ===")
    for i, result in enumerate(series_results[:10], 1):
        print(f"{i}. {result['label']}: {result['count']}枚")
    
    # カード数が0のシリーズを表示
    zero_cards = [s for s in series_results if s['count'] == 0]
    if zero_cards:
        print(f"\n=== カード数0のシリーズ ===")
        for series in zero_cards:
            print(f"- {series['label']}")
    
    # 結果をJSONファイルに保存
    analysis_result = {
        'total_cards': total_cards,
        'total_series': len(series_list),
        'series_details': series_results,
        'top_10': series_results[:10],
        'zero_cards': zero_cards
    }
    
    with open('test/total_cards_analysis.json', 'w', encoding='utf-8') as f:
        json.dump(analysis_result, f, ensure_ascii=False, indent=2)
    
    print(f"\n詳細結果を test/total_cards_analysis.json に保存しました。")

if __name__ == "__main__":
    analyze_total_cards() 