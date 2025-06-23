#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
新しい3段階OCRワークフローのテストスクリプト
"""

import os
import json
import tempfile
import shutil
from card_ocr import (
    ocr_all_cards_basic,
    extract_ms_cards_from_basic_results,
    apply_sp_ocr_to_ms_cards,
    ocr_all_cards_new_workflow
)

def create_test_card_data():
    """テスト用のカードデータを作成"""
    test_cards = [
        {
            "number": "MS-001",
            "name": "テストMSカード1",
            "series": "テストシリーズ",
            "front": {
                "image_url": "https://example.com/ms1_front.jpg",
                "url": "https://example.com/ms1_front.jpg"
            },
            "back": {
                "image_url": "https://example.com/ms1_back.jpg",
                "url": "https://example.com/ms1_back.jpg"
            }
        },
        {
            "number": "MS-002", 
            "name": "テストMSカード2",
            "series": "テストシリーズ",
            "front": {
                "image_url": "https://example.com/ms2_front.jpg",
                "url": "https://example.com/ms2_front.jpg"
            },
            "back": {
                "image_url": "https://example.com/ms2_back.jpg",
                "url": "https://example.com/ms2_back.jpg"
            }
        },
        {
            "number": "PL-001",
            "name": "テストPLカード",
            "series": "テストシリーズ", 
            "front": {
                "image_url": "https://example.com/pl1_front.jpg",
                "url": "https://example.com/pl1_front.jpg"
            },
            "back": {
                "image_url": "https://example.com/pl1_back.jpg",
                "url": "https://example.com/pl1_back.jpg"
            }
        }
    ]
    return test_cards

def create_mock_ocr_result(card_type="MS"):
    """モックOCR結果を作成"""
    if card_type == "MS":
        return {
            "type": "MS",
            "card_id": "MS-001",
            "name": "テストMSカード",
            "model": "テストモデル",
            "cost": 3,
            "category": "近距離",
            "pilot": "テストパイロット",
            "stats": {
                "height": "18.0m",
                "weight": "50.0t",
                "mobility": 200,
                "ranged_attack": 150,
                "melee_attack": 250,
                "hp": 300
            },
            "terrain_compatibility": {
                "ground": "A",
                "space": "B",
                "desert": "C",
                "water": "D"
            },
            "weapon": {
                "main": {
                    "name": "ビームソード",
                    "range": 1,
                    "type": "近距離"
                },
                "sub": {
                    "name": "ビームライフル",
                    "range": 3,
                    "type": "遠距離"
                }
            },
            "ms_ability": {
                "name": "テストアビリティ",
                "type": "常時",
                "range": 0,
                "cost": 0,
                "description": "テスト効果"
            },
            "link_ability": [
                {
                    "name": "テストリンク",
                    "condition": "テスト条件",
                    "effect": "テスト効果"
                }
            ],
            "impact_area": {
                "type": "circular",
                "radius": 1,
                "centered": True
            },
            "illustrator": "テストイラストレーター"
        }
    else:  # PL
        return {
            "type": "PL",
            "card_id": "PL-001",
            "name": "テストPLカード",
            "cost": 2,
            "category": "パイロット",
            "pilot_skill": {
                "name": "テストスキル",
                "effect": "テスト効果"
            },
            "link_ability": [
                {
                    "name": "テストリンク",
                    "condition": "テスト条件",
                    "effect": "テスト効果"
                }
            ],
            "illustrator": "テストイラストレーター"
        }

def test_new_workflow():
    """新しいワークフローのテスト"""
    print("=== 新しい3段階OCRワークフローのテストを開始 ===")
    
    # テスト用の一時ディレクトリを作成
    with tempfile.TemporaryDirectory() as temp_dir:
        cards_dir = os.path.join(temp_dir, "test_cards")
        results_dir = os.path.join(temp_dir, "test_results")
        
        os.makedirs(cards_dir, exist_ok=True)
        os.makedirs(results_dir, exist_ok=True)
        
        # テストカードデータを作成
        test_cards = create_test_card_data()
        
        # テストカードファイルを保存
        for i, card in enumerate(test_cards):
            card_file = os.path.join(cards_dir, f"card_{i+1}.json")
            with open(card_file, 'w', encoding='utf-8') as f:
                json.dump(card, f, ensure_ascii=False, indent=2)
        
        print(f"テストカードファイルを作成: {len(test_cards)}件")
        
        # 段階1: 基本OCRのテスト（モック）
        print("\n--- 段階1: 基本OCRテスト ---")
        
        # モックOCR結果を作成
        for i, card in enumerate(test_cards):
            card_type = "MS" if card["number"].startswith("MS") else "PL"
            mock_ocr_data = create_mock_ocr_result(card_type)
            
            basic_card_info = {
                'card_number': card['number'],
                'card_name': card['name'],
                'series': card['series'],
                'front_image_url': card['front']['image_url'],
                'back_image_url': card['back']['image_url'],
                'ocr_data': mock_ocr_data,
                'ocr_timestamp': '2024-01-01T00:00:00',
                'ocr_type': 'basic'
            }
            
            # ファイル名を生成
            safe_number = card['number'].replace('-', '_')
            safe_name = card['name'].replace(' ', '_')
            safe_series = card['series'].replace(' ', '_')
            
            basic_result_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_basic.json")
            
            with open(basic_result_file, 'w', encoding='utf-8') as f:
                json.dump(basic_card_info, f, ensure_ascii=False, indent=2)
            
            print(f"  ✓ 基本OCR結果作成: {card['number']} {card['name']} ({card_type})")
        
        # 段階2: MSカード抽出のテスト
        print("\n--- 段階2: MSカード抽出テスト ---")
        ms_cards, other_cards = extract_ms_cards_from_basic_results(results_dir)
        
        print(f"MSカード数: {len(ms_cards)}")
        print(f"その他カード数: {len(other_cards)}")
        
        for ms_card in ms_cards:
            print(f"  ✓ MSカード: {ms_card['card_number']} {ms_card['card_name']}")
        
        for other_card in other_cards:
            print(f"  - その他: {other_card['card_number']} {other_card['card_name']} ({other_card['card_type']})")
        
        # 段階3: SP OCRのテスト（モック）
        print("\n--- 段階3: SP OCRテスト ---")
        
        # モックSP結果を作成
        for ms_card in ms_cards:
            card_number = ms_card['card_number']
            card_name = ms_card['card_name']
            series_name = ms_card['series']
            
            # モックSP生データ
            mock_sp_raw = {
                "sp_info": {
                    "type": "normal",
                    "name": "テストSP攻撃",
                    "partner": None,
                    "target": "単体（敵）",
                    "attack_type": "貫通（敵）",
                    "range": 2,
                    "squad_sp": False,
                    "united_sp": False
                },
                "power": {
                    "normal": 3000,
                    "squad": None,
                    "united": None
                },
                "descriptions": {
                    "all_description": "敵単体に貫通攻撃でダメージを与える。",
                    "normal_description": "敵単体に貫通攻撃でダメージを与える。",
                    "squad_description": None,
                    "united_description": None
                },
                "metadata": {
                    "note": None,
                    "ocr_confidence": 0.9,
                    "processing_notes": None
                }
            }
            
            # SP生データを保存
            safe_number = card_number.replace('-', '_')
            safe_name = card_name.replace(' ', '_')
            safe_series = series_name.replace(' ', '_')
            
            sp_raw_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sp_raw.json")
            sp_parsed_file = os.path.join(results_dir, f"{safe_series}_{safe_number}_{safe_name}_sp.json")
            
            # SP生データを保存
            with open(sp_raw_file, 'w', encoding='utf-8') as f:
                json.dump(mock_sp_raw, f, ensure_ascii=False, indent=2)
            
            # SPパース済みデータを保存
            sp_details = mock_sp_raw.copy()
            sp_details.update({
                'card_number': card_number,
                'card_name': card_name,
                'series': series_name,
                'sp_ocr_timestamp': '2024-01-01T00:00:00',
                'sp_ocr_type': 'detailed'
            })
            
            with open(sp_parsed_file, 'w', encoding='utf-8') as f:
                json.dump(sp_details, f, ensure_ascii=False, indent=2)
            
            print(f"  ✓ SP OCR結果作成: {card_number} {card_name}")
        
        # 結果ファイルの確認
        print("\n--- 結果ファイル確認 ---")
        result_files = os.listdir(results_dir)
        
        basic_files = [f for f in result_files if f.endswith('_basic.json')]
        sp_raw_files = [f for f in result_files if f.endswith('_sp_raw.json')]
        sp_parsed_files = [f for f in result_files if f.endswith('_sp.json')]
        
        print(f"基本OCRファイル: {len(basic_files)}件")
        print(f"SP生データファイル: {len(sp_raw_files)}件")
        print(f"SPパース済みファイル: {len(sp_parsed_files)}件")
        
        for file in result_files:
            print(f"  - {file}")
    
    print("\n=== テスト完了 ===")

if __name__ == "__main__":
    test_new_workflow() 