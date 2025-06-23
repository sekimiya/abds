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
                analyzed_data = analyze_pl_sq_skills(ocr_result)
                pl_cards.append({
                    'card_number': card_number,
                    'card_name': card_name,
                    'series': data['back']['series'],
                    'ocr_data': analyzed_data,
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
        pilot_skill = pl_card['ocr_data'].get('pilot_skill', {})
        has_sq_skill = pilot_skill.get('has_sq_skill', False)
        sq_details = pilot_skill.get('sq_skill_details', {})
        print(f"\nカード: {card_number} {card_name}")
        print(f"SQ関連スキル: {'あり' if has_sq_skill else 'なし'}")
        if has_sq_skill:
            print(f"  SQゲージ効果: {sq_details.get('sq_gauge_effect', 'なし')}")
            print(f"  SQ最大値効果: {sq_details.get('sq_max_effect', 'なし')}")
            print(f"  SQUAD RUSH効果: {sq_details.get('squad_rush_effect', 'なし')}")
            sq_conditions = sq_details.get('sq_conditions', {})
            sq_effects = sq_details.get('sq_effects', {})
            print(f"  --- 詳細条件分析 ---")
            print(f"    ゲージ条件: {sq_conditions.get('gauge_condition', 'なし')}")
            print(f"    最大値条件: {sq_conditions.get('max_condition', 'なし')}")
            print(f"    RUSH条件: {sq_conditions.get('rush_condition', 'なし')}")
            print(f"    RUSH発動条件: {sq_conditions.get('rush_trigger_condition', 'なし')}")
            if sq_conditions.get('other_conditions'):
                print(f"    その他条件: {', '.join(sq_conditions['other_conditions'])}")
            print(f"  --- 詳細効果分析 ---")
            if sq_effects.get('gauge_effects'):
                print(f"    ゲージ効果: {', '.join(sq_effects['gauge_effects'])}")
            if sq_effects.get('max_effects'):
                print(f"    最大値効果: {', '.join(sq_effects['max_effects'])}")
            if sq_effects.get('rush_effects'):
                print(f"    RUSH効果: {', '.join(sq_effects['rush_effects'])}")
            if sq_effects.get('rush_trigger_effects'):
                print(f"    RUSH発動効果: {', '.join(sq_effects['rush_trigger_effects'])}")
            if sq_effects.get('other_effects'):
                print(f"    その他効果: {', '.join(sq_effects['other_effects'])}")
    print(f"\n=== テスト完了 ===")
    print(f"JSONファイルは '{results_dir}' フォルダに保存されました")

if __name__ == "__main__":
    test_sq_skill_analysis() 