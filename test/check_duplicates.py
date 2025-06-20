#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from collections import defaultdict

def check_duplicate_card_numbers():
    """同じカード番号を持つカードを検出"""
    all_cards_list_dir = "all_cards_list"
    
    # カード番号ごとにカード情報を収集
    card_numbers = defaultdict(list)
    
    # 全JSONファイルを読み込み
    for filename in os.listdir(all_cards_list_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(all_cards_list_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    card_data = json.load(f)
                    card_number = card_data.get('number', '')
                    if card_number:
                        card_numbers[card_number].append({
                            'series': card_data.get('series', ''),
                            'name': card_data.get('name', ''),
                            'filename': filename
                        })
            except Exception as e:
                print(f"Error reading {filename}: {e}")
    
    # 重複するカード番号を検出
    duplicates = {}
    for card_number, cards in card_numbers.items():
        if len(cards) > 1:
            duplicates[card_number] = cards
    
    # 結果を表示
    print(f"=== 重複カード番号検出結果 ===")
    print(f"重複するカード番号数: {len(duplicates)}")
    print()
    
    if duplicates:
        print("重複カード一覧:")
        for card_number, cards in sorted(duplicates.items()):
            print(f"\nカード番号: {card_number}")
            for i, card in enumerate(cards, 1):
                print(f"  {i}. シリーズ: {card['series']}")
                print(f"     カード名: {card['name']}")
                print(f"     ファイル: {card['filename']}")
    else:
        print("重複するカード番号は見つかりませんでした。")
    
    # 統計情報
    total_cards = sum(len(cards) for cards in card_numbers.values())
    unique_cards = len(card_numbers)
    duplicate_cards = total_cards - unique_cards
    
    print(f"\n=== 統計情報 ===")
    print(f"総カード数: {total_cards}")
    print(f"ユニークカード番号数: {unique_cards}")
    print(f"重複カード数: {duplicate_cards}")
    
    return duplicates

if __name__ == "__main__":
    check_duplicate_card_numbers() 