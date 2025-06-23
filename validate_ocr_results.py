#!/usr/bin/env python3
"""
OCR結果のロジック的な整合性を検証するスクリプト
"""

import json
import os
import glob
import argparse
from typing import Dict, List, Any

def validate_special_attack(data: Dict[str, Any], card_info: str) -> List[str]:
    """SPの整合性を検証"""
    errors = []
    
    if 'special_attack' not in data:
        return errors
    
    sp = data['special_attack']
    
    # 1. partnerとunited_spの整合性チェック
    partner = sp.get('partner', None)
    united_sp = sp.get('united_sp', False)
    
    if partner and partner != [None] and partner != [""]:
        # partnerが存在する場合、united_spはtrueであるべき
        if not united_sp:
            errors.append(f"partnerが存在するのにunited_spがfalse: {partner}")
    else:
        # partnerが存在しない場合、united_spはfalseであるべき
        if united_sp:
            errors.append(f"partnerが存在しないのにunited_spがtrue")
    
    # 2. squad_spとunited_spの両方がtrueの場合のチェック
    squad_sp = sp.get('squad_sp', False)
    if squad_sp and united_sp:
        errors.append(f"squad_spとunited_spが両方true（通常は片方のみ）")
    
    # 3. all_descriptionと分割された説明文の整合性チェック
    all_desc = sp.get('all_description', '')
    normal_desc = sp.get('normal_description', '')
    squad_desc = sp.get('squad_description', None)
    united_desc = sp.get('united_description', None)
    
    if all_desc:
        # ／ー（全角スラッシュ＋長音符）のチェック
        if '／ー' in all_desc:
            if squad_sp or united_sp:
                errors.append(f"all_descriptionに「／ー」があるのにsquad_spまたはunited_spがtrue: '{all_desc}'")
        elif '/' in all_desc:
            # /で分割される場合（最初の/で分割）
            parts = all_desc.split('/', 1)
            if len(parts) == 2:
                expected_normal = parts[0].strip()
                expected_second = parts[1].strip()
                
                if squad_sp and squad_desc != expected_second:
                    errors.append(f"squad_descriptionがall_descriptionの後半と一致しない: '{squad_desc}' vs '{expected_second}'")
                
                if united_sp and united_desc != expected_second:
                    errors.append(f"united_descriptionがall_descriptionの後半と一致しない: '{united_desc}' vs '{expected_second}'")
        else:
            # /がない場合
            if squad_sp or united_sp:
                errors.append(f"all_descriptionに/がないのにsquad_spまたはunited_spがtrue")
    
    return errors

def validate_link_abilities(data: Dict[str, Any], card_info: str) -> List[str]:
    """リンクアビリティの整合性を検証"""
    errors = []
    
    # MSカードのlink_ability
    if 'link_ability' in data:
        link_abilities = data['link_ability']
        if not isinstance(link_abilities, list):
            errors.append(f"link_abilityがリストではない: {type(link_abilities)}")
        else:
            for i, link in enumerate(link_abilities):
                if not isinstance(link, dict):
                    errors.append(f"link_ability[{i}]が辞書ではない: {type(link)}")
                else:
                    required_fields = ['name', 'condition', 'effect']
                    for field in required_fields:
                        if field not in link:
                            errors.append(f"link_ability[{i}]に{field}フィールドがない")
    
    # PLカードのlink_abilities
    if 'link_abilities' in data:
        link_abilities = data['link_abilities']
        if not isinstance(link_abilities, list):
            errors.append(f"link_abilitiesがリストではない: {type(link_abilities)}")
        else:
            for i, link in enumerate(link_abilities):
                if not isinstance(link, dict):
                    errors.append(f"link_abilities[{i}]が辞書ではない: {type(link)}")
                else:
                    required_fields = ['name', 'condition', 'effect']
                    for field in required_fields:
                        if field not in link:
                            errors.append(f"link_abilities[{i}]に{field}フィールドがない")
    
    return errors

def validate_stats(data: Dict[str, Any], card_info: str) -> List[str]:
    """ステータスの整合性を検証"""
    errors = []
    
    if 'stats' in data:
        stats = data['stats']
        if not isinstance(stats, dict):
            errors.append(f"statsが辞書ではない: {type(stats)}")
        else:
            # 数値フィールドのチェック
            numeric_fields = ['mobility', 'ranged_attack', 'melee_attack', 'hp']
            for field in numeric_fields:
                if field in stats:
                    value = stats[field]
                    if not isinstance(value, (int, float)) or value < 0:
                        errors.append(f"stats.{field}が不正な値: {value}")
    
    return errors

def validate_card_type(data: Dict[str, Any], card_info: str) -> List[str]:
    """カードタイプの整合性を検証"""
    errors = []
    
    card_type = data.get('type', '')
    
    if card_type == 'MS':
        # MSカードに必要なフィールド
        required_fields = ['weapon', 'ms_ability']
        for field in required_fields:
            if field not in data:
                errors.append(f"MSカードに{field}フィールドがない")
        
        # MSカードにPLカード専用フィールドがないかチェック
        pl_only_fields = ['pl_skill', 'sq_skill', 'height', 'age', 'affiliation', 'suit']
        for field in pl_only_fields:
            if field in data:
                errors.append(f"MSカードにPLカード専用フィールド{field}がある")
    
    elif card_type == 'PL':
        # PLカードに必要なフィールド
        required_fields = ['pl_skill']
        for field in required_fields:
            if field not in data:
                errors.append(f"PLカードに{field}フィールドがない")
        
        # PLカードにMSカード専用フィールドがないかチェック
        ms_only_fields = ['weapon', 'ms_ability', 'model', 'pilot']
        for field in ms_only_fields:
            if field in data:
                errors.append(f"PLカードにMSカード専用フィールド{field}がある")
    
    else:
        errors.append(f"不正なカードタイプ: {card_type}")
    
    return errors

def validate_ocr_result(file_path: str) -> List[str]:
    """単一のOCR結果ファイルを検証"""
    errors = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # エラーファイルの場合はスキップ
        if 'error' in data:
            return [f"エラーファイル: {data.get('error', 'Unknown error')}"]
        
        card_info = f"{data.get('card_number', 'Unknown')} {data.get('card_name', 'Unknown')}"
        
        # 各検証を実行
        errors.extend(validate_special_attack(data, card_info))
        errors.extend(validate_link_abilities(data, card_info))
        errors.extend(validate_stats(data, card_info))
        errors.extend(validate_card_type(data, card_info))
        
        # 基本的なフィールドの存在チェック
        required_fields = ['type', 'name']
        for field in required_fields:
            if field not in data:
                errors.append(f"必須フィールド{field}がない")
        
    except Exception as e:
        errors.append(f"ファイル読み込みエラー: {str(e)}")
    
    return errors

def main():
    parser = argparse.ArgumentParser(description='OCR結果のロジック的な整合性を検証')
    parser.add_argument('--results-dir', default='ocr_results', help='OCR結果ディレクトリ')
    parser.add_argument('--output', help='検証結果を保存するファイル')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.results_dir):
        print(f"エラー: {args.results_dir}ディレクトリが見つかりません")
        return
    
    json_files = glob.glob(os.path.join(args.results_dir, '*.json'))
    if not json_files:
        print(f"エラー: {args.results_dir}ディレクトリにJSONファイルが見つかりません")
        return
    
    print(f"検証対象ファイル数: {len(json_files)}")
    
    all_errors = []
    error_files = 0
    
    for json_file in json_files:
        errors = validate_ocr_result(json_file)
        if errors:
            error_files += 1
            file_name = os.path.basename(json_file)
            all_errors.append(f"\n=== {file_name} ===")
            for error in errors:
                all_errors.append(f"  - {error}")
    
    # 結果を表示
    print(f"\n=== 検証結果 ===")
    print(f"エラーファイル数: {error_files}/{len(json_files)}")
    
    if all_errors:
        print("エラー詳細:")
        for error in all_errors:
            print(error)
    else:
        print("エラーは見つかりませんでした。")
    
    # 結果をファイルに保存
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(f"検証対象ファイル数: {len(json_files)}\n")
            f.write(f"エラーファイル数: {error_files}/{len(json_files)}\n")
            if all_errors:
                f.write("エラー詳細:\n")
                for error in all_errors:
                    f.write(error + "\n")
        print(f"\n検証結果を {args.output} に保存しました。")

if __name__ == "__main__":
    main() 