#!/usr/bin/env python3
"""
SPデータマージ機能のテストスクリプト
"""

import json
import os
import tempfile
import shutil
from card_ocr import merge_sp_data_to_card_results, merge_all_card_data_with_all_suffix

def create_test_data():
    """テスト用のデータを作成"""
    
    # テスト用のカードデータ（MSカード - SPあり）
    ms_card_with_sp = {
        "card_number": "MS-001",
        "card_name": "テストMSカード",
        "series": "テストシリーズ",
        "type": "MS",
        "name": "テストMSカード",
        "cost": "3",
        "power": "2000",
        "attribute": "光",
        "rarity": "R",
        "effect": "テスト効果",
        "front": {"image_url": "http://example.com/front.jpg"},
        "back": {"image_url": "http://example.com/back.jpg"},
        "source_data": {"original": "data"}
    }
    
    # テスト用のカードデータ（MSカード - SPなし）
    ms_card_without_sp = {
        "card_number": "MS-002",
        "card_name": "テストMSカード2",
        "series": "テストシリーズ",
        "type": "MS",
        "name": "テストMSカード2",
        "cost": "2",
        "power": "1500",
        "attribute": "闇",
        "rarity": "C",
        "effect": "テスト効果2",
        "front": {"image_url": "http://example.com/front2.jpg"},
        "back": {"image_url": "http://example.com/back2.jpg"},
        "source_data": {"original": "data2"}
    }
    
    # テスト用のカードデータ（PLカード）
    pl_card = {
        "card_number": "PL-001",
        "card_name": "テストPLカード",
        "series": "テストシリーズ",
        "type": "PL",
        "name": "テストPLカード",
        "cost": "1",
        "power": "1000",
        "attribute": "無",
        "rarity": "UC",
        "effect": "PLテスト効果",
        "front": {"image_url": "http://example.com/pl_front.jpg"},
        "back": {"image_url": "http://example.com/pl_back.jpg"},
        "source_data": {"original": "pl_data"}
    }
    
    # SP詳細OCR結果
    sp_detail_data = {
        "card_number": "MS-001",
        "card_name": "テストMSカード",
        "series": "テストシリーズ",
        "special_attack": {
            "name": "テストSP攻撃",
            "cost": "1",
            "power": "3000",
            "effect": "SPテスト効果"
        },
        "sp_ocr_type": "detailed",
        "sp_image_path": "sp_images/MS-001_テストMSカード_sp.jpg"
    }
    
    # SP生OCR結果
    sp_raw_data = {
        "card_number": "MS-001",
        "card_name": "テストMSカード",
        "series": "テストシリーズ",
        "sp_image_path": "sp_images/MS-001_テストMSカード_sp.jpg",
        "sp_ocr_type": "raw",
        "raw_ocr_result": "生のOCR結果テキスト",
        "parsed_sp_data": {
            "name": "テストSP攻撃",
            "cost": "1",
            "power": "3000"
        }
    }
    
    return {
        "ms_card_with_sp": ms_card_with_sp,
        "ms_card_without_sp": ms_card_without_sp,
        "pl_card": pl_card,
        "sp_detail_data": sp_detail_data,
        "sp_raw_data": sp_raw_data
    }

def test_sp_merge():
    """SPデータマージ機能のテスト"""
    print("=== SPデータマージ機能テスト ===")
    
    # テスト用の一時ディレクトリを作成
    with tempfile.TemporaryDirectory() as temp_dir:
        test_data = create_test_data()
        
        # テストファイルを作成
        files_created = []
        
        # カードデータファイル
        card_files = [
            ("テストシリーズ_MS-001_テストMSカード.json", test_data["ms_card_with_sp"]),
            ("テストシリーズ_MS-002_テストMSカード2.json", test_data["ms_card_without_sp"]),
            ("PL-001_テストPLカード.json", test_data["pl_card"])
        ]
        
        for filename, data in card_files:
            filepath = os.path.join(temp_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            files_created.append(filepath)
        
        # SP詳細データファイル
        sp_detail_file = os.path.join(temp_dir, "テストシリーズ_MS-001_テストMSカード_sp.json")
        with open(sp_detail_file, 'w', encoding='utf-8') as f:
            json.dump(test_data["sp_detail_data"], f, ensure_ascii=False, indent=2)
        files_created.append(sp_detail_file)
        
        # SP生データファイル
        sp_raw_file = os.path.join(temp_dir, "テストシリーズ_MS-001_テストMSカード_sp_raw.json")
        with open(sp_raw_file, 'w', encoding='utf-8') as f:
            json.dump(test_data["sp_raw_data"], f, ensure_ascii=False, indent=2)
        files_created.append(sp_raw_file)
        
        print(f"テストファイルを作成しました: {len(files_created)}件")
        for filepath in files_created:
            print(f"  - {os.path.basename(filepath)}")
        
        # SPデータマージ機能をテスト
        print("\n--- SPデータマージ機能テスト ---")
        merge_sp_data_to_card_results(temp_dir)
        
        # マージ結果を確認
        print("\n--- マージ結果確認 ---")
        for filename, original_data in card_files:
            filepath = os.path.join(temp_dir, filename)
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    merged_data = json.load(f)
                
                card_number = original_data["card_number"]
                print(f"\nカード: {card_number}")
                
                if card_number == "MS-001":
                    # SPデータがあるMSカード
                    if "special_attack" in merged_data:
                        print(f"  ✓ SP詳細データがマージされました")
                        print(f"    SP名: {merged_data['special_attack'].get('name', 'N/A')}")
                    else:
                        print(f"  ✗ SP詳細データがマージされていません")
                    
                    if "sp_raw_ocr_result" in merged_data:
                        print(f"  ✓ SP生データがマージされました")
                    else:
                        print(f"  ✗ SP生データがマージされていません")
                
                elif card_number == "MS-002":
                    # SPデータがないMSカード
                    if "sp_ocr_type" in merged_data and merged_data["sp_ocr_type"] == "not_available":
                        print(f"  ✓ SPデータなしフラグが設定されました")
                    else:
                        print(f"  ✗ SPデータなしフラグが設定されていません")
                
                elif card_number == "PL-001":
                    # PLカード
                    if "special_attack" not in merged_data and "sp_ocr_type" not in merged_data:
                        print(f"  ✓ PLカードにSP関連フィールドが追加されていません")
                    else:
                        print(f"  ✗ PLカードにSP関連フィールドが追加されています")

def test_unified_merge():
    """統合マージ機能のテスト"""
    print("\n=== 統合マージ機能テスト ===")
    
    # テスト用の一時ディレクトリを作成
    with tempfile.TemporaryDirectory() as temp_dir:
        test_data = create_test_data()
        
        # テストファイルを作成
        files_created = []
        
        # カードデータファイル
        card_files = [
            ("テストシリーズ_MS-001_テストMSカード.json", test_data["ms_card_with_sp"]),
            ("テストシリーズ_MS-002_テストMSカード2.json", test_data["ms_card_without_sp"]),
            ("PL-001_テストPLカード.json", test_data["pl_card"])
        ]
        
        for filename, data in card_files:
            filepath = os.path.join(temp_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            files_created.append(filepath)
        
        # SP詳細データファイル
        sp_detail_file = os.path.join(temp_dir, "テストシリーズ_MS-001_テストMSカード_sp.json")
        with open(sp_detail_file, 'w', encoding='utf-8') as f:
            json.dump(test_data["sp_detail_data"], f, ensure_ascii=False, indent=2)
        files_created.append(sp_detail_file)
        
        # SP生データファイル
        sp_raw_file = os.path.join(temp_dir, "テストシリーズ_MS-001_テストMSカード_sp_raw.json")
        with open(sp_raw_file, 'w', encoding='utf-8') as f:
            json.dump(test_data["sp_raw_data"], f, ensure_ascii=False, indent=2)
        files_created.append(sp_raw_file)
        
        print(f"テストファイルを作成しました: {len(files_created)}件")
        
        # 統合マージ機能をテスト
        print("\n--- 統合マージ機能テスト ---")
        merge_all_card_data_with_all_suffix(temp_dir)
        
        # 統合マージ結果を確認
        print("\n--- 統合マージ結果確認 ---")
        all_files = glob.glob(os.path.join(temp_dir, "*_all.json"))
        print(f"統合マージファイル数: {len(all_files)}件")
        
        for all_file in all_files:
            filename = os.path.basename(all_file)
            print(f"\n統合ファイル: {filename}")
            
            with open(all_file, 'r', encoding='utf-8') as f:
                merged_data = json.load(f)
            
            card_number = merged_data.get('card_number', '')
            card_name = merged_data.get('card_name', '')
            has_sp_data = merged_data.get('has_sp_data', False)
            
            print(f"  カード番号: {card_number}")
            print(f"  カード名: {card_name}")
            print(f"  SPデータあり: {has_sp_data}")
            
            if has_sp_data:
                sp_detail = merged_data.get('sp_detail_data')
                sp_raw = merged_data.get('sp_raw_data')
                
                if sp_detail:
                    print(f"  ✓ SP詳細データが含まれています")
                    sp_name = sp_detail.get('special_attack', {}).get('name', 'N/A')
                    print(f"    SP名: {sp_name}")
                
                if sp_raw:
                    print(f"  ✓ SP生データが含まれています")
                    raw_type = sp_raw.get('sp_ocr_type', 'N/A')
                    print(f"    SP生OCRタイプ: {raw_type}")
            
            # マージタイムスタンプとバージョンを確認
            merge_timestamp = merged_data.get('merge_timestamp', 'N/A')
            merge_version = merged_data.get('merge_version', 'N/A')
            print(f"  マージタイムスタンプ: {merge_timestamp}")
            print(f"  マージバージョン: {merge_version}")

def test_error_handling():
    """エラーハンドリングのテスト"""
    print("\n=== エラーハンドリングテスト ===")
    
    # テスト用の一時ディレクトリを作成
    with tempfile.TemporaryDirectory() as temp_dir:
        # 破損したJSONファイルを作成
        corrupted_file = os.path.join(temp_dir, "破損ファイル.json")
        with open(corrupted_file, 'w', encoding='utf-8') as f:
            f.write("{ invalid json content")
        
        # 正常なカードデータファイル
        test_data = create_test_data()
        normal_file = os.path.join(temp_dir, "正常ファイル.json")
        with open(normal_file, 'w', encoding='utf-8') as f:
            json.dump(test_data["ms_card_with_sp"], f, ensure_ascii=False, indent=2)
        
        print("破損したJSONファイルと正常なファイルを作成しました")
        
        # 統合マージ機能をテスト（エラーハンドリング）
        print("\n--- エラーハンドリングテスト ---")
        merge_all_card_data_with_all_suffix(temp_dir)
        
        # 結果を確認
        all_files = glob.glob(os.path.join(temp_dir, "*_all.json"))
        print(f"正常に処理された統合ファイル数: {len(all_files)}件")
        
        if len(all_files) == 1:
            print("✓ エラーファイルを適切にスキップし、正常ファイルのみ処理されました")
        else:
            print("✗ エラーハンドリングが正常に動作していません")

if __name__ == "__main__":
    import glob
    
    print("SPデータマージ機能のテストを開始します...")
    
    try:
        test_sp_merge()
        test_unified_merge()
        test_error_handling()
        print("\n=== すべてのテストが完了しました ===")
    except Exception as e:
        print(f"\nテスト実行中にエラーが発生しました: {e}")
        import traceback
        traceback.print_exc() 