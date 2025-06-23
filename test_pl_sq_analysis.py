#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PLカードのSQ関連スキル分析をテストするスクリプト
実際のJSONファイルからカード情報を読み取ってOCR処理を実行
"""

import os
import json
from card_ocr import analyze_pl_sq_skills, extract_structured_data_from_url, save_pl_sq_analysis_results, read_api_key

def test_sq_skill_analysis():
    """all_cards_list_debugから指定カードの裏面画像URLを使ってOCRテスト"""
    print("=== PLカードSQ関連スキル分析テストを開始 ===")
    
    # 対象カードのファイル名
    card_files = [
        "all_cards_list_debug/FQ01-036_コウ・ウラキ.json",
        "all_cards_list_debug/FQ01-048_マスター・アジア＆風雲再起.json",
        "all_cards_list_debug/FQ01-042_ベルナルド・モンシア.json"
    ]
    
    # APIキー
    api_key = read_api_key('APIkey.txt')
    if not api_key:
        print("エラー: APIキーが見つかりません")
        return
    
    results_dir = "test_output"
    os.makedirs(results_dir, exist_ok=True)
    pl_cards = []
    
    for file_path in card_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            card_number = data['back']['number'].replace('_b','')
            card_name = data['back']['name']
            back_url = data['back']['url']
            print(f"OCR実行: {card_number} {card_name}")
            ocr_result = extract_structured_data_from_url(back_url, api_key)
            print(f"  [DEBUG] OCR APIレスポンス: {repr(ocr_result)[:500]}")
            raw_ocr_result = ocr_result  # 生レスポンスを保存
            
            if isinstance(ocr_result, str):
                # 先頭・末尾の```jsonや```を除去
                ocr_result_clean = ocr_result.strip()
                if ocr_result_clean.startswith('```json'):
                    ocr_result_clean = ocr_result_clean[len('```json'):].strip()
                if ocr_result_clean.startswith('```'):
                    ocr_result_clean = ocr_result_clean[len('```'):].strip()
                if ocr_result_clean.endswith('```'):
                    ocr_result_clean = ocr_result_clean[:-3].strip()
                try:
                    ocr_result = json.loads(ocr_result_clean)
                except Exception:
                    print(f"  ✗ OCR結果パースエラー: {card_number}")
                    continue
            
            if ocr_result and ocr_result.get('type') == 'PL':
                # SQ関連スキルを分析
                sq_analysis = analyze_pl_sq_skills(ocr_result)
                
                # pilot_skillデータを構築
                orig_pilot_skill = ocr_result.get('pilot_skill', {})
                pilot_skill = {
                    'name': orig_pilot_skill.get('name', ''),
                    'effect': orig_pilot_skill.get('effect', ''),
                    'has_sq_skill': sq_analysis['has_sq_skill']
                }
                
                if sq_analysis['has_sq_skill'] and sq_analysis['sq_skill_details']:
                    pilot_skill['sq_skill_details'] = sq_analysis['sq_skill_details']
                
                # link_abilityデータを取得
                link_ability = ocr_result.get('link_ability', [])
                
                # full_ocr_dataを構築
                full_ocr_data = dict(ocr_result)
                full_ocr_data['pilot_skill'] = pilot_skill
                
                pl_cards.append({
                    'card_number': card_number,
                    'card_name': card_name,
                    'series': data['back']['series'],
                    'sq_analysis_timestamp': None,  # save_pl_sq_analysis_resultsで自動設定
                    'sq_analysis_type': 'detailed',
                    'pilot_skill': pilot_skill,
                    'link_ability': link_ability,
                    'full_ocr_data': full_ocr_data,
                    'raw': raw_ocr_result
                })
                print(f"  ✓ OCR・分析成功: {card_name}")
            else:
                print(f"  ✗ PLカードではありません: {card_number}")
        except Exception as e:
            print(f"  ✗ 読込/処理エラー: {file_path} - {str(e)}")
    
    print(f"\n--- 分析結果保存テスト ---")
    saved_count = save_pl_sq_analysis_results(pl_cards, results_dir)
    
    print(f"\n--- 分析結果詳細確認 ---")
    for pl_card in pl_cards:
        card_number = pl_card['card_number']
        card_name = pl_card['card_name']
        pilot_skill = pl_card['pilot_skill']
        has_sq_skill = pilot_skill.get('has_sq_skill', False)
        sq_details = pilot_skill.get('sq_skill_details', {})
        
        print(f"\nカード: {card_number} {card_name}")
        print(f"パイロットスキル: {pilot_skill.get('name', 'なし')}")
        print(f"SQ関連スキル: {'あり' if has_sq_skill else 'なし'}")
        
        # すべてのパイロットスキルでtriggerとeffectを表示
        if sq_details:
            print(f"  発動条件: {sq_details.get('trigger', 'なし')}")
            print(f"  基本効果: {sq_details.get('effect', 'なし')}")
            
            # SQ関連スキルがある場合のみ追加情報を表示
            if has_sq_skill:
                print(f"  SQUAD RUSH効果: {sq_details.get('sq_rush_effect', 'なし')}")
                print(f"  SQゲージ効果: {sq_details.get('sq_gauge_effect', 'なし')}")
                print(f"  SQ最大値効果: {sq_details.get('sq_max_effect', 'なし')}")
                print(f"  SQUAD RUSH効果（旧）: {sq_details.get('squad_rush_effect', 'なし')}")
    
    print(f"\n=== テスト完了 ===")
    print(f"JSONファイルは '{results_dir}' フォルダに保存されました")

if __name__ == "__main__":
    test_sq_skill_analysis() 