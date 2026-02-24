#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
test_ocr_compatibility.py — 既存の _sp.json / _sq_analysis.json と
generate_derivatives.py で生成した結果の互換性を検証するスクリプト

Usage:
  python test_ocr_compatibility.py                         # フル検証
  python test_ocr_compatibility.py --results-dir ocr_results_debug  # ディレクトリ指定
  python test_ocr_compatibility.py --verbose               # 詳細出力
"""

import os
import sys
import json
import glob
import argparse
import re
from typing import Dict, List, Optional, Tuple

# generate_derivatives のロジックをインポート
from generate_derivatives import (
    generate_sp_from_basic,
    generate_sq_analysis_from_basic,
)


DEFAULT_RESULTS_DIR = "ocr_results_debug"


def find_matched_pairs(results_dir: str) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """
    _basic.json と既存の _sp.json / _sq_analysis.json のペアを検出する。
    戻り値: (sp_pairs, sq_pairs) - 各ペアは (basic_path, existing_path)
    """
    basic_files = sorted(glob.glob(os.path.join(results_dir, "*_basic.json")))

    sp_pairs = []
    sq_pairs = []

    for basic_path in basic_files:
        prefix = basic_path.replace("_basic.json", "")

        sp_path = prefix + "_sp.json"
        if os.path.exists(sp_path):
            sp_pairs.append((basic_path, sp_path))

        sq_path = prefix + "_sq_analysis.json"
        if os.path.exists(sq_path):
            sq_pairs.append((basic_path, sq_path))

    return sp_pairs, sq_pairs


def compare_sp(basic_path: str, existing_sp_path: str, verbose: bool = False) -> Dict:
    """
    既存の _sp.json と generate_derivatives で生成した結果を比較する。
    """
    result = {
        "card": os.path.basename(basic_path),
        "match": True,
        "fields_compared": 0,
        "fields_matched": 0,
        "mismatches": [],
    }

    try:
        with open(basic_path, "r", encoding="utf-8") as f:
            basic_data = json.load(f)
        with open(existing_sp_path, "r", encoding="utf-8") as f:
            existing_sp = json.load(f)
    except Exception as e:
        result["match"] = False
        result["mismatches"].append(f"ファイル読み込みエラー: {e}")
        return result

    ocr_data = basic_data.get("ocr_data", {})
    card_number = basic_data.get("card_number", "")
    card_name = basic_data.get("card_name", "")
    series = basic_data.get("series", "")

    # 新しいSPデータを生成
    generated_sp = generate_sp_from_basic(ocr_data, card_number, card_name, series)

    if generated_sp is None:
        result["match"] = False
        result["mismatches"].append("SP生成失敗 (MSカードではない or special_attackなし)")
        return result

    # 主要フィールドの比較
    check_fields = [
        ("sp_info.name", _get_nested(existing_sp, "sp_info", "name"),
         _get_nested(generated_sp, "sp_info", "name")),
        ("sp_info.target", _get_nested(existing_sp, "sp_info", "target"),
         _get_nested(generated_sp, "sp_info", "target")),
        ("sp_info.range", _get_nested(existing_sp, "sp_info", "range"),
         _get_nested(generated_sp, "sp_info", "range")),
        ("power.normal", _get_nested(existing_sp, "power", "normal"),
         _get_nested(generated_sp, "power", "normal")),
        ("power.squad", _get_nested(existing_sp, "power", "squad"),
         _get_nested(generated_sp, "power", "squad")),
        ("power.united", _get_nested(existing_sp, "power", "united"),
         _get_nested(generated_sp, "power", "united")),
    ]

    for field_name, existing_val, generated_val in check_fields:
        result["fields_compared"] += 1
        if _values_match(existing_val, generated_val):
            result["fields_matched"] += 1
        else:
            result["match"] = False
            result["mismatches"].append(
                f"{field_name}: existing={existing_val!r} vs generated={generated_val!r}"
            )

    if verbose and result["mismatches"]:
        print(f"  SP不一致: {result['card']}")
        for m in result["mismatches"]:
            print(f"    - {m}")

    return result


def compare_sq(basic_path: str, existing_sq_path: str, verbose: bool = False) -> Dict:
    """
    既存の _sq_analysis.json と generate_derivatives で生成した結果を比較する。
    """
    result = {
        "card": os.path.basename(basic_path),
        "match": True,
        "fields_compared": 0,
        "fields_matched": 0,
        "mismatches": [],
    }

    try:
        with open(basic_path, "r", encoding="utf-8") as f:
            basic_data = json.load(f)
        with open(existing_sq_path, "r", encoding="utf-8") as f:
            existing_sq = json.load(f)
    except Exception as e:
        result["match"] = False
        result["mismatches"].append(f"ファイル読み込みエラー: {e}")
        return result

    ocr_data = basic_data.get("ocr_data", {})
    card_number = basic_data.get("card_number", "")
    card_name = basic_data.get("card_name", "")
    series = basic_data.get("series", "")
    raw = ocr_data.get("raw", "")

    generated_sq = generate_sq_analysis_from_basic(ocr_data, card_number, card_name, series, raw)

    if generated_sq is None:
        result["match"] = False
        result["mismatches"].append("SQ生成失敗 (PLカードではない)")
        return result

    # 主要フィールドの比較
    check_fields = [
        ("pilot_skill.name",
         _get_nested(existing_sq, "pilot_skill", "name"),
         _get_nested(generated_sq, "pilot_skill", "name")),
        ("pilot_skill.has_sq_skill",
         _get_nested(existing_sq, "pilot_skill", "has_sq_skill"),
         _get_nested(generated_sq, "pilot_skill", "has_sq_skill")),
        ("pilot_skill.effect",
         _get_nested(existing_sq, "pilot_skill", "effect"),
         _get_nested(generated_sq, "pilot_skill", "effect")),
        ("sq_skill_details.trigger",
         _get_nested(existing_sq, "pilot_skill", "sq_skill_details", "trigger"),
         _get_nested(generated_sq, "pilot_skill", "sq_skill_details", "trigger")),
        ("sq_skill_details.sq_gauge_effect",
         _get_nested(existing_sq, "pilot_skill", "sq_skill_details", "sq_gauge_effect"),
         _get_nested(generated_sq, "pilot_skill", "sq_skill_details", "sq_gauge_effect")),
        ("sq_skill_details.squad_rush_effect",
         _get_nested(existing_sq, "pilot_skill", "sq_skill_details", "squad_rush_effect"),
         _get_nested(generated_sq, "pilot_skill", "sq_skill_details", "squad_rush_effect")),
    ]

    for field_name, existing_val, generated_val in check_fields:
        result["fields_compared"] += 1
        if _values_match(existing_val, generated_val):
            result["fields_matched"] += 1
        else:
            result["match"] = False
            result["mismatches"].append(
                f"{field_name}: existing={existing_val!r} vs generated={generated_val!r}"
            )

    if verbose and result["mismatches"]:
        print(f"  SQ不一致: {result['card']}")
        for m in result["mismatches"]:
            print(f"    - {m}")

    return result


def _get_nested(d: dict, *keys):
    """ネストされた辞書から安全に値を取得"""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _values_match(a, b) -> bool:
    """値の比較（None と 空文字列は同等扱い、数値の型違いも許容）"""
    if a == b:
        return True
    # None, "", 0 の同等扱い
    if a in (None, "", 0) and b in (None, "", 0):
        # 数値の 0 は有意な値の可能性があるため、両方とも 0 or 両方とも falsy の場合のみ
        if isinstance(a, (int, float)) or isinstance(b, (int, float)):
            return a == b
        return True
    # 数値型の比較（int vs float）
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    # 文字列の正規化比較（全角半角括弧の違いを吸収）
    if isinstance(a, str) and isinstance(b, str):
        na = _normalize_str(a)
        nb = _normalize_str(b)
        return na == nb
    return False


def _normalize_str(s: str) -> str:
    """文字列の正規化（全角半角括弧・スペースの違いを吸収）"""
    s = s.strip()
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("　", " ")
    return s


def test_app_compatibility(results_dir: str) -> Dict:
    """
    app.py がデータを正常に読み込めるかの簡易検証。
    _sp.json / _sq_analysis.json が app.py の期待するフィールドを持つか確認。
    """
    result = {"sp_valid": 0, "sp_invalid": 0, "sq_valid": 0, "sq_invalid": 0, "errors": []}

    # SP ファイルの検証
    sp_files = sorted(glob.glob(os.path.join(results_dir, "*_sp.json")))
    for sp_path in sp_files:
        try:
            with open(sp_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # app.py (L111-142) が期待するフィールド
            has_sp_info = "sp_info" in data or "power" in data or "descriptions" in data
            if has_sp_info:
                result["sp_valid"] += 1
            else:
                result["sp_invalid"] += 1
                result["errors"].append(f"SP形式不正: {os.path.basename(sp_path)}")
        except Exception as e:
            result["sp_invalid"] += 1
            result["errors"].append(f"SP読み込みエラー: {os.path.basename(sp_path)} - {e}")

    # SQ ファイルの検証
    sq_files = sorted(glob.glob(os.path.join(results_dir, "*_sq_analysis.json")))
    for sq_path in sq_files:
        try:
            with open(sq_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # app.py (L144-157) が期待するフィールド
            has_sq_type = data.get("sq_analysis_type") is not None
            has_pilot_skill = "pilot_skill" in data and "ocr_data" not in data
            if has_sq_type or has_pilot_skill:
                result["sq_valid"] += 1
            else:
                result["sq_invalid"] += 1
                result["errors"].append(f"SQ形式不正: {os.path.basename(sq_path)}")
        except Exception as e:
            result["sq_invalid"] += 1
            result["errors"].append(f"SQ読み込みエラー: {os.path.basename(sq_path)} - {e}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="既存の _sp.json / _sq_analysis.json と generate_derivatives.py の出力を比較検証"
    )
    parser.add_argument("--results-dir", type=str, default=DEFAULT_RESULTS_DIR,
                        help=f"OCR結果ディレクトリ (default: {DEFAULT_RESULTS_DIR})")
    parser.add_argument("--verbose", action="store_true", help="詳細出力")
    args = parser.parse_args()

    results_dir = args.results_dir
    if not os.path.exists(results_dir):
        print(f"ERROR: ディレクトリが見つかりません: {results_dir}")
        sys.exit(1)

    print(f"=== OCR互換性検証 ===")
    print(f"対象ディレクトリ: {results_dir}")
    print()

    # 1. 既存ファイルのペアを検出
    sp_pairs, sq_pairs = find_matched_pairs(results_dir)
    print(f"検出された SP ペア数: {len(sp_pairs)}")
    print(f"検出された SQ ペア数: {len(sq_pairs)}")
    print()

    # 2. SP互換性検証
    print(f"--- SP互換性検証 ({len(sp_pairs)} 件) ---")
    sp_match_count = 0
    sp_field_total = 0
    sp_field_match = 0

    for basic_path, existing_sp_path in sp_pairs:
        result = compare_sp(basic_path, existing_sp_path, verbose=args.verbose)
        if result["match"]:
            sp_match_count += 1
        sp_field_total += result["fields_compared"]
        sp_field_match += result["fields_matched"]

    if sp_pairs:
        sp_rate = sp_match_count / len(sp_pairs) * 100
        sp_field_rate = sp_field_match / sp_field_total * 100 if sp_field_total > 0 else 0
        print(f"  完全一致: {sp_match_count}/{len(sp_pairs)} ({sp_rate:.1f}%)")
        print(f"  フィールド一致率: {sp_field_match}/{sp_field_total} ({sp_field_rate:.1f}%)")
    else:
        print("  (SPペアが見つかりません)")
    print()

    # 3. SQ互換性検証
    print(f"--- SQ互換性検証 ({len(sq_pairs)} 件) ---")
    sq_match_count = 0
    sq_field_total = 0
    sq_field_match = 0

    for basic_path, existing_sq_path in sq_pairs:
        result = compare_sq(basic_path, existing_sq_path, verbose=args.verbose)
        if result["match"]:
            sq_match_count += 1
        sq_field_total += result["fields_compared"]
        sq_field_match += result["fields_matched"]

    if sq_pairs:
        sq_rate = sq_match_count / len(sq_pairs) * 100
        sq_field_rate = sq_field_match / sq_field_total * 100 if sq_field_total > 0 else 0
        print(f"  完全一致: {sq_match_count}/{len(sq_pairs)} ({sq_rate:.1f}%)")
        print(f"  フィールド一致率: {sq_field_match}/{sq_field_total} ({sq_field_rate:.1f}%)")
    else:
        print("  (SQペアが見つかりません)")
    print()

    # 4. app.py 互換性検証
    print("--- app.py 互換性検証 ---")
    app_result = test_app_compatibility(results_dir)
    print(f"  SP有効: {app_result['sp_valid']}  無効: {app_result['sp_invalid']}")
    print(f"  SQ有効: {app_result['sq_valid']}  無効: {app_result['sq_invalid']}")

    if app_result["errors"]:
        print(f"  エラー ({len(app_result['errors'])} 件):")
        for err in app_result["errors"][:10]:  # 最大10件表示
            print(f"    - {err}")
        if len(app_result["errors"]) > 10:
            print(f"    ... 他 {len(app_result['errors']) - 10} 件")
    print()

    # 5. サマリー
    print("=== 検証結果サマリー ===")
    all_ok = True
    if sp_pairs:
        if sp_match_count == len(sp_pairs):
            print(f"  SP: ALL PASS ({sp_match_count}/{len(sp_pairs)})")
        else:
            print(f"  SP: {sp_match_count}/{len(sp_pairs)} PASS (フィールド一致率: {sp_field_rate:.1f}%)")
            all_ok = False
    if sq_pairs:
        if sq_match_count == len(sq_pairs):
            print(f"  SQ: ALL PASS ({sq_match_count}/{len(sq_pairs)})")
        else:
            print(f"  SQ: {sq_match_count}/{len(sq_pairs)} PASS (フィールド一致率: {sq_field_rate:.1f}%)")
            all_ok = False
    if app_result["sp_invalid"] > 0 or app_result["sq_invalid"] > 0:
        print(f"  app.py互換: ISSUES FOUND")
        all_ok = False
    else:
        print(f"  app.py互換: OK")

    if all_ok:
        print("\n  RESULT: ALL TESTS PASSED")
    else:
        print("\n  RESULT: SOME ISSUES FOUND (see details above)")


if __name__ == "__main__":
    main()
