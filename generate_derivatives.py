#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
generate_derivatives.py — _basic.json から _sp.json / _sq_analysis.json を生成

OCR済みの _basic.json に含まれる ocr_data から、追加API呼び出しなしで
SP情報（MSカード）とSQ分析情報（PLカード）を派生ファイルとして生成する。

Usage:
  python generate_derivatives.py --all                    # 全カード一括生成
  python generate_derivatives.py --card AB01-001          # カード番号指定
  python generate_derivatives.py --series AB01            # シリーズ絞り込み
  python generate_derivatives.py --all --force            # 既存ファイルを上書き
  python generate_derivatives.py --all --dry-run          # 対象一覧のみ表示
  python generate_derivatives.py --results-dir ocr_results_debug  # ディレクトリ指定
"""

import os
import sys
import json
import re
import argparse
import glob
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_RESULTS_DIR = "ocr_results_debug"


# ---------------------------------------------------------------------------
# SP derivative generation (MS cards)
# ---------------------------------------------------------------------------
def generate_sp_from_basic(ocr_data: dict, card_number: str, card_name: str,
                           series: str = "") -> Optional[dict]:
    """
    _basic.json の ocr_data から _sp.json 形式のデータを生成する。
    MSカードのみ対象。ocr_data.special_attack を sp_info/power/descriptions に変換。
    """
    if ocr_data.get("type") != "MS":
        return None

    sa = ocr_data.get("special_attack")
    if not sa and not isinstance(sa, dict):
        # special_attack がない場合、raw テキストからパースを試みる
        sa = _parse_sp_from_raw(ocr_data.get("raw", ""))
        if not sa:
            return None

    if not isinstance(sa, dict):
        return None

    # sp_info の構築
    sp_name = sa.get("name")
    target = sa.get("target")
    sp_range = sa.get("range")
    attack_type = sa.get("attack_type")
    united_sp_data = sa.get("united_sp")

    has_united = united_sp_data is not None and isinstance(united_sp_data, dict)
    has_squad = False  # basic.json では squad SP の明示フラグはないため

    if has_united:
        sp_type = "UNITED SP"
    else:
        sp_type = "normal"

    sp_info = {
        "type": sp_type,
        "name": sp_name,
        "partner": None,
        "target": target,
        "attack_type": attack_type,
        "range": sp_range,
        "squad_sp": has_squad,
        "united_sp": has_united,
    }

    if has_united:
        partners = []
        for key in ["partner1", "partner2"]:
            p = united_sp_data.get(key)
            if p:
                partners.append(p)
        sp_info["partner"] = partners if partners else None

    # power の構築
    power_val = sa.get("power")
    power = {"normal": None, "squad": None, "united": None}

    if isinstance(power_val, dict):
        power["normal"] = power_val.get("normal")
        power["squad"] = power_val.get("squad")
        power["united"] = power_val.get("united")
    elif isinstance(power_val, (int, float)):
        power["normal"] = int(power_val)

    if has_united:
        united_power = united_sp_data.get("power")
        if united_power is not None:
            power["united"] = int(united_power) if isinstance(united_power, (int, float)) else united_power

    # descriptions の構築
    desc = sa.get("description", "")
    descriptions = {
        "all_description": desc,
        "normal_description": desc,
        "squad_description": None,
        "united_description": None,
    }

    if has_united:
        united_desc = united_sp_data.get("description")
        if united_desc:
            descriptions["united_description"] = united_desc
            descriptions["all_description"] = f"{desc}／{united_desc}" if desc else united_desc

    # 説明文に「／」が含まれる場合の分割処理
    if desc and "／" in desc and not has_united:
        parts = desc.split("／", 1)
        normal_part = parts[0].strip()
        extra_part = parts[1].strip() if len(parts) > 1 else ""

        descriptions["normal_description"] = desc  # 「／ー」を含むそのまま保持
        if extra_part and extra_part != "ー":
            # 実質的な追加効果がある場合
            descriptions["squad_description"] = extra_part

    # metadata
    metadata = {
        "note": None,
        "ocr_confidence": 0.85,
        "processing_notes": "generated from _basic.json (no additional API call)",
    }

    # 「／ー」パターンの検出
    if desc and "／ー" in desc:
        metadata["note"] = "／ー"

    result = {
        "sp_info": sp_info,
        "power": power,
        "descriptions": descriptions,
        "metadata": metadata,
        "card_number": card_number,
        "card_name": card_name,
        "series": series,
        "sp_ocr_timestamp": datetime.now().isoformat(),
        "sp_ocr_type": "derived_from_basic",
    }

    return result


def _parse_sp_from_raw(raw_text: str) -> Optional[dict]:
    """raw テキストから SPECIAL ATTACK セクションをパースする（フォールバック用）"""
    if not raw_text:
        return None

    # SPECIAL ATTACK セクションを探す
    sa_match = re.search(
        r"SPECIAL\s*ATTACK\s*\n(.*?)(?:\n\s*(?:IMPACT|UNITED|illust|©|$))",
        raw_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not sa_match:
        return None

    sa_text = sa_match.group(1).strip()
    lines = [l.strip() for l in sa_text.split("\n") if l.strip()]

    if not lines:
        return None

    result = {"name": None, "target": None, "range": None, "power": None, "description": None}

    # 1行目: SP名
    result["name"] = lines[0]

    for line in lines[1:]:
        # 「単体(敵) 射程 2」のようなパターン
        target_match = re.search(r"(単体|範囲|全体)\s*[\(（]?\s*(敵|味方)\s*[\)）]?\s*射程\s*(\d+)", line)
        if target_match:
            result["target"] = f"{target_match.group(1)}({target_match.group(2)})"
            result["range"] = int(target_match.group(3))
            continue

        # 「威力 3400」のようなパターン
        power_match = re.search(r"威力\s*(\d+)", line)
        if power_match:
            result["power"] = int(power_match.group(1))
            continue

        # 残りは description
        if not result["description"] and not re.match(r"^SP\s*コスト", line):
            # SPコスト行以外を description として扱う
            if any(kw in line for kw in ["ダメージ", "攻撃", "回復", "アップ", "ダウン", "効果"]):
                result["description"] = line

    return result if result["name"] else None


# ---------------------------------------------------------------------------
# SQ analysis derivative generation (PL cards)
# ---------------------------------------------------------------------------
def analyze_pl_sq_skills(pl_card_data: dict) -> dict:
    """PLカードのSQ関連スキルを詳細分析（card_ocr.py の同名関数と同等ロジック）"""
    pilot_skill = pl_card_data.get("pilot_skill", {})
    if not isinstance(pilot_skill, dict):
        pilot_skill = {}

    skill_effect = pilot_skill.get("effect", "") or ""

    # EB（ECHOES BEAT）カードの判定 — EBカードはSQではない
    eb_keywords = ["ECHOES BEAT", "EBLv.", "EB Lv.", "戦術技"]
    raw_text = pl_card_data.get("raw", "") or ""
    link_abilities = pl_card_data.get("link_ability", []) or []
    link_text = " ".join(
        la.get("effect", "") for la in link_abilities if isinstance(la, dict)
    )
    combined_text = f"{skill_effect} {link_text} {raw_text}"
    is_eb_card = any(kw in combined_text for kw in eb_keywords)

    # SQ関連スキルの判定（"ゲージ" 単体は "SPゲージ" 等に誤マッチするため除外）
    sq_keywords = ["SQゲージ", "SQガージ", "SQUAD RUSH", "SQUADRUSH", "スクワッドラッシュ"]
    has_sq_skill = any(keyword in skill_effect for keyword in sq_keywords) and not is_eb_card

    # スキル効果を改行で分割
    lines = skill_effect.split("\n")

    # trigger（発動条件）の抽出
    trigger = None
    if lines:
        first_line = lines[0].strip()
        trigger_keywords = ["時", "場合", "時点", "発動", "ロックオン", "撃破", "ダメージ", "HP", "戦艦", "拠点"]
        if any(keyword in first_line for keyword in trigger_keywords):
            trigger = first_line

    # 基本効果の抽出（trigger以外の部分）
    effect_parts = []
    for line in lines:
        line = line.strip()
        if line and line != trigger:
            effect_parts.append(line)
    effect = "\n".join(effect_parts) if effect_parts else None

    if not has_sq_skill:
        return {
            "has_sq_skill": False,
            "sq_skill_details": {
                "trigger": trigger,
                "effect": effect,
                "sq_rush_effect": None,
                "sq_gauge_effect": None,
                "sq_max_effect": None,
                "squad_rush_effect": None,
            },
        }

    # SQスキルがある場合の詳細分析
    sq_rush_effect = None
    sq_gauge_effect = None
    sq_max_effect = None
    squad_rush_effect = None

    # SQUAD RUSH効果の抽出
    rush_patterns = [
        r"SQUAD RUSH中[^。]*",
        r"SQUADRUSH中[^。]*",
        r"スクワッドラッシュ中[^。]*",
        r"SQUAD RUSH発動中[^。]*",
        r"SQUADRUSH発動中[^。]*",
        r"SQUAD RUSHが発動[^。]*",
        r"SQUADRUSHが発動[^。]*",
    ]

    for pattern in rush_patterns:
        match = re.search(pattern, skill_effect)
        if match:
            squad_rush_effect = match.group()
            sq_rush_effect = match.group()
            break

    # 基本効果の再抽出（triggerとsq_rush_effect以外の部分）
    effect_parts = []
    for line in lines:
        line = line.strip()
        if line and line != trigger and line != sq_rush_effect:
            if any(keyword in line for keyword in ["SQゲージ", "SQガージ"]):
                effect_parts.append(line)

    if effect_parts:
        effect = "\n".join(effect_parts)

    # SQゲージ効果の抽出
    gauge_patterns = [
        r"SQゲージ[＋+]\d+",
        r"SQゲージ[ー-]\d+",
        r"SQゲージ(?:が|を)?(?:増加|減少|アップ|ダウン)",
        r"SQゲージ(?:大|中|小)?(?:アップ|ダウン)",
    ]

    for pattern in gauge_patterns:
        match = re.search(pattern, skill_effect)
        if match:
            sq_gauge_effect = match.group()
            break

    # SQゲージ最大値効果の抽出
    max_patterns = [
        r"SQゲージが最大時[^。]*",
        r"SQゲージ最大時[^。]*",
        r"SQゲージが最大[^。]*",
    ]

    for pattern in max_patterns:
        match = re.search(pattern, skill_effect)
        if match:
            sq_max_effect = match.group()
            break

    return {
        "has_sq_skill": True,
        "sq_skill_details": {
            "trigger": trigger,
            "effect": effect,
            "sq_rush_effect": sq_rush_effect,
            "sq_gauge_effect": sq_gauge_effect,
            "sq_max_effect": sq_max_effect,
            "squad_rush_effect": squad_rush_effect,
        },
    }


def generate_sq_analysis_from_basic(ocr_data: dict, card_number: str, card_name: str,
                                     series: str = "", raw: str = "") -> Optional[dict]:
    """
    _basic.json の ocr_data から _sq_analysis.json 形式のデータを生成する。
    PLカードのみ対象。
    """
    if ocr_data.get("type") != "PL":
        return None

    sq_analysis = analyze_pl_sq_skills(ocr_data)

    # pilot_skill データの構築
    orig_pilot_skill = ocr_data.get("pilot_skill", {})
    if not isinstance(orig_pilot_skill, dict):
        orig_pilot_skill = {}

    pilot_skill = {
        "name": orig_pilot_skill.get("name", ""),
        "effect": orig_pilot_skill.get("effect", ""),
        "has_sq_skill": sq_analysis["has_sq_skill"],
    }

    if sq_analysis["sq_skill_details"]:
        pilot_skill["sq_skill_details"] = sq_analysis["sq_skill_details"]

    # link_ability
    link_ability = ocr_data.get("link_ability", [])

    # full_ocr_data にも pilot_skill を含める
    full_ocr_data = dict(ocr_data)
    full_ocr_data["pilot_skill"] = pilot_skill

    result = {
        "card_number": ocr_data.get("card_id", card_number),
        "card_name": ocr_data.get("name", card_name),
        "series": series,
        "sq_analysis_timestamp": datetime.now().isoformat(),
        "sq_analysis_type": "detailed",
        "pilot_skill": pilot_skill,
        "link_ability": link_ability,
        "full_ocr_data": full_ocr_data,
        "raw": raw,
    }

    return result


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------
def sanitize_filename(s: str) -> str:
    return (
        s.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("*", "_")
        .replace("?", "_")
        .replace('"', "_")
        .replace("<", "_")
        .replace(">", "_")
        .replace("|", "_")
        .replace(" ", "_")
    )


def find_basic_files(results_dir: str, series_filter: str = "",
                     card_filter: str = "") -> List[str]:
    """_basic.json ファイルを検索する"""
    pattern = os.path.join(results_dir, "*_basic.json")
    files = sorted(glob.glob(pattern))

    if series_filter:
        files = [f for f in files if series_filter.upper() in os.path.basename(f).upper()]

    if card_filter:
        files = [f for f in files if card_filter.upper() in os.path.basename(f).upper()]

    return files


def get_output_path(basic_path: str, suffix: str) -> str:
    """_basic.json のパスから対応する派生ファイルパスを生成"""
    return basic_path.replace("_basic.json", f"_{suffix}.json")


def generate_derivatives_for_file(basic_path: str, force: bool = False,
                                   dry_run: bool = False) -> Tuple[bool, bool]:
    """
    1つの _basic.json から _sp.json と _sq_analysis.json を生成する。
    戻り値: (sp_generated, sq_generated)
    """
    sp_generated = False
    sq_generated = False

    try:
        with open(basic_path, "r", encoding="utf-8") as f:
            basic_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  ERROR: 読み込み失敗: {basic_path} - {e}")
        return sp_generated, sq_generated

    ocr_data = basic_data.get("ocr_data", {})
    card_number = basic_data.get("card_number", "")
    card_name = basic_data.get("card_name", "")
    series = basic_data.get("series", "")
    raw = ocr_data.get("raw", "")

    card_type = ocr_data.get("type", "")

    # MS カード → _sp.json 生成
    if card_type == "MS":
        sp_path = get_output_path(basic_path, "sp")
        if force or not os.path.exists(sp_path):
            if dry_run:
                print(f"  [DRY-RUN] SP生成予定: {os.path.basename(sp_path)}")
                sp_generated = True
            else:
                sp_data = generate_sp_from_basic(ocr_data, card_number, card_name, series)
                if sp_data:
                    with open(sp_path, "w", encoding="utf-8") as f:
                        json.dump(sp_data, f, ensure_ascii=False, indent=2)
                    sp_generated = True

    # PL カード → _sq_analysis.json 生成
    if card_type == "PL":
        sq_path = get_output_path(basic_path, "sq_analysis")
        if force or not os.path.exists(sq_path):
            if dry_run:
                print(f"  [DRY-RUN] SQ分析生成予定: {os.path.basename(sq_path)}")
                sq_generated = True
            else:
                sq_data = generate_sq_analysis_from_basic(ocr_data, card_number, card_name, series, raw)
                if sq_data:
                    with open(sq_path, "w", encoding="utf-8") as f:
                        json.dump(sq_data, f, ensure_ascii=False, indent=2)
                    sq_generated = True

    return sp_generated, sq_generated


# ---------------------------------------------------------------------------
# Public API: generate_derivatives_for_basic (called from OCR backends)
# ---------------------------------------------------------------------------
def generate_derivatives_for_basic(basic_path: str) -> None:
    """
    OCRバックエンドから _basic.json 保存後に呼び出すための簡易エントリポイント。
    既存の _sp.json / _sq_analysis.json がなければ生成する。
    """
    sp_ok, sq_ok = generate_derivatives_for_file(basic_path, force=False)
    if sp_ok:
        print(f"    -> SP派生ファイル生成完了")
    if sq_ok:
        print(f"    -> SQ分析派生ファイル生成完了")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="_basic.json から _sp.json / _sq_analysis.json を生成（API呼び出し不要）"
    )
    parser.add_argument("--all", action="store_true", help="全カードの派生ファイルを生成")
    parser.add_argument("--card", type=str, default="", help="カード番号指定 (例: AB01-001)")
    parser.add_argument("--series", type=str, default="", help="シリーズ絞り込み (例: AB01)")
    parser.add_argument("--force", action="store_true", help="既存ファイルを上書き")
    parser.add_argument("--dry-run", action="store_true", help="対象一覧のみ表示（ファイル生成なし）")
    parser.add_argument("--results-dir", type=str, default=DEFAULT_RESULTS_DIR,
                        help=f"OCR結果ディレクトリ (default: {DEFAULT_RESULTS_DIR})")
    args = parser.parse_args()

    if not args.all and not args.card:
        parser.error("--all または --card のいずれかを指定してください")

    results_dir = args.results_dir
    if not os.path.exists(results_dir):
        print(f"ERROR: ディレクトリが見つかりません: {results_dir}")
        sys.exit(1)

    # _basic.json ファイルを検索
    basic_files = find_basic_files(results_dir, series_filter=args.series, card_filter=args.card)
    print(f"対象 _basic.json ファイル数: {len(basic_files)}")

    if not basic_files:
        print("処理対象がありません。")
        return

    sp_total = 0
    sq_total = 0
    processed = 0

    for i, basic_path in enumerate(basic_files, 1):
        basename = os.path.basename(basic_path)
        sp_ok, sq_ok = generate_derivatives_for_file(basic_path, force=args.force, dry_run=args.dry_run)

        if sp_ok or sq_ok:
            tags = []
            if sp_ok:
                tags.append("SP")
                sp_total += 1
            if sq_ok:
                tags.append("SQ")
                sq_total += 1
            action = "DRY-RUN" if args.dry_run else "生成"
            print(f"[{i}/{len(basic_files)}] {action}: {basename} -> {', '.join(tags)}")
            processed += 1

    print(f"\n=== 完了 ===")
    print(f"処理ファイル数: {processed}")
    print(f"SP生成: {sp_total} 件")
    print(f"SQ分析生成: {sq_total} 件")


if __name__ == "__main__":
    main()
