#!/usr/bin/env python3
"""
OCR バリデーション＆補正テストシステム

_basic.json のリンクアビリティ名・パイロットスキル名・効果文・構造を
頻度分析＋パターンマッチで検証し、補正辞書で自動修正する。

Usage:
    python ocr_test.py --report                    # 全チェック（ファイル変更なし）
    python ocr_test.py --report --check link_names # 特定チェックのみ
    python ocr_test.py --fix                       # 補正辞書で自動修正
    python ocr_test.py --fix --dry-run             # 修正プレビュー
    python ocr_test.py --report --series VE01      # 特定シリーズのみ
"""

import json
import glob
import re
import argparse
import os
import sys
from collections import Counter

import requests
from bs4 import BeautifulSoup

# ====================================================================
# 定数（logic/ から直接インポートせず、ここで参照用に定義）
# parse_link_condition は logic/utils.py を再利用したいが、
# パッケージ構造の問題を避けるため軽量な再実装とする
# ====================================================================

RESULTS_DIR = 'ocr_results_debug'
CORRECTIONS_FILE = 'ocr_corrections.json'
MASTER_DATA_FILE = 'official_master_data.json'
OFFICIAL_CARDLIST_URL = 'https://www.gundam-ab.com/cardlist/?series=529001'

# OCRで頻出する文字混同の正規化マップ
# 外国語文字 → 正しい日本語文字
CHAR_NORMALIZE_MAP = {
    '\u0E21': 'ム',  # Thai ม → ム
    '\u092E': 'ム',  # Devanagari म → ム
    '\u09AE': 'ム',  # Bengali ম → ム
}

# BUFF_PATTERNS: logic/constants.py と同一
BUFF_PATTERNS = {
    ('mobility', 'small'): r'機動力.*小アップ',
    ('ranged', 'small'): r'遠距離攻撃力.*小アップ',
    ('melee', 'small'): r'近距離攻撃力.*小アップ',
    ('hp', 'small'): r'HP.*小アップ',
    ('mobility', 'medium'): r'機動力.*中アップ',
    ('ranged', 'medium'): r'遠距離攻撃力.*中アップ',
    ('melee', 'medium'): r'近距離攻撃力.*中アップ',
    ('hp', 'medium'): r'HP.*中アップ',
}

# LINK_CONDITION_CATEGORY_MAP: logic/constants.py と同一
LINK_CONDITION_CATEGORY_MAP = {
    '機動': '機動',
    '機動力': '機動',
    '遠距離': '遠距離',
    '近距離': '近距離',
    '殲滅': '殲滅',
    '殲滅系': '殲滅',
    '制圧': '制圧',
    '制圧/圧': '制圧',
    '防衛': '防衛',
}

# ABILITY_DATA: logic/constants.py と同一（基本名のみ使用）
ABILITY_DATA = {
    '連射', '連撃', '精密射撃', '妨撃', '縛撃', '縛射', '強撃', '逆襲',
    '砕撃', '撃滅', '強襲', '断砕', '貫通', '掃射', '爆撃', '砲撃',
    '支援砲撃', '奇襲', '全弾発射', 'オールレンジ', '砕撃', '鼓舞',
    '強化', '増援', '誘導', '補給', '集中砲火',
}

VALID_RARITIES = {'M', 'R', 'C', 'P', 'U', 'SR', 'PR', 'LR', 'LE', 'CP', 'N'}
VALID_TERRAIN_RANKS = {'S', 'A', 'B', 'C', 'D', None}
VALID_TYPES = {'MS', 'PL'}


# ====================================================================
# 文字正規化
# ====================================================================

def normalize_chars(text):
    """OCR由来の文字混同を正規化する。"""
    if not text:
        return text
    return ''.join(CHAR_NORMALIZE_MAP.get(c, c) for c in text)


# ====================================================================
# Levenshtein距離
# ====================================================================

def levenshtein_distance(s1, s2):
    """2つの文字列のLevenshtein編集距離を計算する。"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def find_closest_match(name, candidates, max_distance=2):
    """候補セットの中から最も近い文字列を見つける。

    Returns:
        (best_match, distance) or (None, None) if no match within threshold
    """
    best = None
    best_dist = max_distance + 1
    for candidate in candidates:
        dist = levenshtein_distance(name, candidate)
        if dist < best_dist:
            best_dist = dist
            best = candidate
        if dist == 0:
            break
    if best_dist <= max_distance:
        return (best, best_dist)
    return (None, None)


# ====================================================================
# 公式サイトマスターデータ取得
# ====================================================================

def fetch_official_master_data(force_refresh=False):
    """公式サイトからMSアビリティ名・リンクアビリティ名のマスターデータを取得する。

    キャッシュファイル (official_master_data.json) が存在する場合はそれを返す。
    force_refresh=True の場合は再取得する。

    Returns:
        dict: {'ms_abilities': [...], 'link_names': [...]}
    """
    if not force_refresh and os.path.exists(MASTER_DATA_FILE):
        with open(MASTER_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    r = requests.get(OFFICIAL_CARDLIST_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, 'html.parser')

    # MSアビリティ名のselect要素
    ms_abilities = []
    sel_ms = soup.find('select', id='msAbilityName')
    if sel_ms:
        for opt in sel_ms.find_all('option'):
            v = opt.get('value', '').strip()
            if v:
                ms_abilities.append(v)

    # リンクアビリティ名のselect要素
    link_names = []
    sel_link = soup.find('select', id='linkAbilityName')
    if sel_link:
        for opt in sel_link.find_all('option'):
            v = opt.get('value', '').strip()
            if v:
                link_names.append(v)

    data = {
        'ms_abilities': ms_abilities,
        'link_names': link_names,
        'fetched_at': __import__('datetime').datetime.now().isoformat(),
    }

    with open(MASTER_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


def update_ability_data_from_master(master_data):
    """公式マスターデータでABILITY_DATAセットを更新する。"""
    global ABILITY_DATA
    for full_name in master_data.get('ms_abilities', []):
        base = extract_ability_base_name(full_name)
        if base:
            ABILITY_DATA.add(base)


# ====================================================================
# マスター照合（OCR結果 vs 公式マスターデータ）
# ====================================================================

def check_against_master(cards, master_data):
    """OCR結果を公式マスターデータと照合し、不一致アイテムを返す。

    Returns:
        list of dict: 各アイテムは
            {file, card_id, category, ocr_value, closest_match, distance, field}
        category: 'ms_ability' or 'link_ability'
    """
    official_ms_abilities = set(master_data.get('ms_abilities', []))
    official_link_names = set(master_data.get('link_names', []))

    mismatches = []

    for basename, fpath, ocr in cards:
        card_id = ocr.get('card_id', basename.replace('_basic.json', ''))

        # --- リンクアビリティ名の照合 ---
        link_list = get_link_abilities(ocr)
        for i, link in enumerate(link_list):
            name = link.get('name', '')
            if not name:
                continue
            if name in official_link_names:
                continue
            # 不一致 → 最近傍を探す
            match, dist = find_closest_match(name, official_link_names, max_distance=3)
            mismatches.append({
                'file': basename,
                'card_id': card_id,
                'category': 'link_ability',
                'ocr_value': name,
                'closest_match': match,
                'distance': dist,
                'field': f'link_ability[{i}].name',
            })

        # --- MSアビリティ名の照合 ---
        if ocr.get('type') == 'MS':
            ms_ability = ocr.get('ms_ability')
            if ms_ability:
                name = ms_ability.get('name', '')
                if name and name not in official_ms_abilities:
                    match, dist = find_closest_match(name, official_ms_abilities, max_distance=3)
                    mismatches.append({
                        'file': basename,
                        'card_id': card_id,
                        'category': 'ms_ability',
                        'ocr_value': name,
                        'closest_match': match,
                        'distance': dist,
                        'field': 'ms_ability.name',
                    })

    return mismatches


# ====================================================================
# 自動補正候補生成
# ====================================================================

def auto_generate_corrections(cards, master_data=None, max_distance=2):
    """OCRデータを公式マスターデータと照合し、自動補正候補を生成する。

    Returns:
        list of dict: 各候補は
            {'category', 'ocr_value', 'suggested', 'distance', 'method', 'files'}
    """
    if master_data is None:
        master_data = fetch_official_master_data()

    official_ms_abilities = set(master_data.get('ms_abilities', []))
    official_link_names = set(master_data.get('link_names', []))

    # 既存の補正辞書をロード（既に登録済みのものはスキップ）
    corrections = load_corrections()
    existing_ms = set(corrections.get('ms_ability_names', {}).keys())
    existing_link = set(corrections.get('link_ability_names', {}).keys())
    existing_pilot = set(corrections.get('pilot_skill_names', {}).keys())

    candidates = []

    # --- MSアビリティ補正 ---
    ms_ability_names = {}  # name -> [files]
    for basename, fpath, ocr in cards:
        if ocr.get('type') != 'MS':
            continue
        ms_ability = ocr.get('ms_ability')
        if not ms_ability:
            continue
        name = ms_ability.get('name', '')
        if not name:
            continue
        ms_ability_names.setdefault(name, []).append(basename)

    for name, files in ms_ability_names.items():
        if name in existing_ms:
            continue
        if name in official_ms_abilities:
            continue
        match, dist = find_closest_match(name, official_ms_abilities, max_distance)
        if match:
            candidates.append({
                'category': 'ms_ability_names',
                'ocr_value': name,
                'suggested': match,
                'distance': dist,
                'method': 'levenshtein_vs_official',
                'count': len(files),
                'files': files[:3],
            })

    # --- リンクアビリティ名補正 ---
    link_name_files = {}  # name -> [files]
    for basename, fpath, ocr in cards:
        for link in get_link_abilities(ocr):
            name = link.get('name', '')
            if not name:
                continue
            link_name_files.setdefault(name, []).append(basename)

    for name, files in link_name_files.items():
        if name in existing_link:
            continue
        if name in official_link_names:
            continue
        # 出現1回のみ or 公式に似ているものを候補にする
        match, dist = find_closest_match(name, official_link_names, max_distance)
        if match:
            candidates.append({
                'category': 'link_ability_names',
                'ocr_value': name,
                'suggested': match,
                'distance': dist,
                'method': 'levenshtein_vs_official',
                'count': len(files),
                'files': files[:3],
            })

    # --- パイロットスキル名補正（頻度ベース） ---
    pilot_skill_names = {}  # name -> [files]
    for basename, fpath, ocr in cards:
        if ocr.get('type') != 'PL':
            continue
        ps = ocr.get('pilot_skill') or ocr.get('pl_skill')
        if not ps:
            continue
        name = ps.get('name', '')
        if not name:
            continue
        pilot_skill_names.setdefault(name, []).append(basename)

    # 多数派の名前をマスターとして使い、出現1回の名前を補正候補にする
    frequent_pilot_skills = {n for n, files in pilot_skill_names.items() if len(files) >= 2}
    rare_pilot_skills = {n: files for n, files in pilot_skill_names.items() if len(files) == 1}

    for name, files in rare_pilot_skills.items():
        if name in existing_pilot:
            continue
        if not frequent_pilot_skills:
            continue
        match, dist = find_closest_match(name, frequent_pilot_skills, max_distance)
        if match:
            candidates.append({
                'category': 'pilot_skill_names',
                'ocr_value': name,
                'suggested': match,
                'distance': dist,
                'method': 'frequency_levenshtein',
                'count': len(files),
                'files': files[:3],
            })

    return candidates


# ====================================================================
# データローダー
# ====================================================================

def load_basic_files(results_dir, series_filter=None):
    """_basic.json ファイルを全て読み込む。

    Returns:
        list of (filename, data_dict) — data_dict は ocr_data の中身
    """
    pattern = os.path.join(results_dir, '*_basic.json')
    files = sorted(glob.glob(pattern))
    results = []
    for fpath in files:
        basename = os.path.basename(fpath)

        # シリーズフィルタ
        if series_filter:
            # card_number からシリーズプレフィックスを抽出
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                card_number = raw.get('card_number', '')
                if not card_number.startswith(series_filter):
                    continue
                ocr_data = raw.get('ocr_data')
                if not ocr_data:
                    continue
                results.append((basename, fpath, ocr_data))
            except (json.JSONDecodeError, IOError):
                continue
        else:
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                ocr_data = raw.get('ocr_data')
                if not ocr_data:
                    continue
                results.append((basename, fpath, ocr_data))
            except (json.JSONDecodeError, IOError):
                continue

    return results


def load_corrections():
    """補正辞書を読み込む。ファイルがなければ空辞書を返す。"""
    if not os.path.exists(CORRECTIONS_FILE):
        return {
            'link_ability_names': {},
            'pilot_skill_names': {},
            'ms_ability_names': {},
            'link_effects': {},
        }
    with open(CORRECTIONS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_link_abilities(ocr_data):
    """OCRデータからリンクアビリティリストを取得（link_ability / link_abilities 両対応）。"""
    links = ocr_data.get('link_abilities') or ocr_data.get('link_ability') or []
    if not isinstance(links, list):
        return []
    return links


# ====================================================================
# parse_link_condition（logic/utils.py の軽量再実装）
# ====================================================================

def parse_link_condition(condition):
    """リンク条件文字列をパースする。成功時は dict、失敗時は None。"""
    if not condition or not isinstance(condition, str):
        return None
    m = re.search(r'(?:デッキに)?(.+?)(?:が|の)?(\d+)(?:枚|体)以上', condition)
    if not m:
        return None
    prefix = m.group(1).strip()
    required = int(m.group(2))
    category_filter = LINK_CONDITION_CATEGORY_MAP.get(prefix)
    return {'required': required, 'category_filter': category_filter, 'prefix': prefix}


# ====================================================================
# 1-A: リンクアビリティ名の頻度分析（出現1回 = OCRエラー候補）
# ====================================================================

def check_link_names(cards):
    """リンクアビリティ名の頻度分析。1回のみ出現の名前をOCRエラーの可能性として報告。"""
    warnings = []

    # 全リンク名を収集（名前→出現ファイルリスト）
    name_files = {}
    for basename, fpath, ocr in cards:
        for link in get_link_abilities(ocr):
            name = link.get('name', '')
            if not name:
                continue
            name_files.setdefault(name, []).append(basename)

    # 出現1回のものを抽出（OCRエラーの可能性が高い）
    rare_names = {n: files for n, files in name_files.items() if len(files) == 1}

    for rare_name, files in sorted(rare_names.items()):
        warnings.append({
            'level': 'WARNING',
            'message': f'1回のみ出現: "{rare_name}" ({files[0]})',
            'detail': 'OCRエラーの可能性あり（出現1回のみ）',
        })

    return warnings


# ====================================================================
# 1-B: リンク効果テキストのパターン検証
# ====================================================================

def check_link_effects(cards):
    """各リンク効果がBUFF_PATTERNSまたはSQゲージ系にマッチするか検証。"""
    warnings = []

    for basename, fpath, ocr in cards:
        for link in get_link_abilities(ocr):
            effect = link.get('effect', '')
            if not effect:
                continue

            # 複数バフが[]で並ぶ場合があるので分割して検査
            # 例: "[遠距離攻撃力][近距離攻撃力]小アップ" → 全体でマッチを試みる
            matched = False
            for (stat, size), pattern in BUFF_PATTERNS.items():
                if re.search(pattern, effect):
                    matched = True
                    break

            if not matched:
                # 複合バフパターン: [X][Y]小アップ / [X][Y]中アップ
                if re.search(r'\[.+?\]\[.+?\](?:小|中)アップ', effect):
                    matched = True

            if not matched:
                # SQゲージ系
                if 'SQゲージ' in effect:
                    matched = True

            if not matched:
                warnings.append({
                    'level': 'WARNING',
                    'message': f'不明な効果: "{effect}" ({basename})',
                    'detail': f'BUFF_PATTERNS にマッチせず (リンク名: "{link.get("name", "")}")',
                })

    return warnings


# ====================================================================
# 1-C: リンク条件フォーマット検証
# ====================================================================

def check_link_conditions(cards):
    """各リンク条件が parse_link_condition でパースできるか検証。"""
    warnings = []
    total = 0
    success = 0

    for basename, fpath, ocr in cards:
        for link in get_link_abilities(ocr):
            condition = link.get('condition', '')
            if not condition:
                continue
            total += 1
            parsed = parse_link_condition(condition)
            if parsed is None:
                warnings.append({
                    'level': 'WARNING',
                    'message': f'パース失敗: "{condition}" ({basename})',
                    'detail': f'リンク名: "{link.get("name", "")}"',
                })
            else:
                success += 1
                # カテゴリフィルタがある場合、既知カテゴリかチェック
                prefix = parsed.get('prefix', '')
                if prefix and prefix not in LINK_CONDITION_CATEGORY_MAP:
                    # カテゴリ名ではなく普通のリンク名カウント条件の場合は OK
                    # "デッキに3枚以上" のようなパターンではprefixが空文字列になる
                    pass

    if total > 0 and not warnings:
        warnings.append({
            'level': 'OK',
            'message': f'全{total}件パース成功',
            'detail': '',
        })

    return warnings


# ====================================================================
# 1-D: MSアビリティ名の検証
# ====================================================================

def extract_ability_base_name(name):
    """アビリティ名から基本名を抽出（[]内サフィックスを除去）。
    例: "増援[防衛]" → "増援", "掃射[広角]" → "掃射"
    """
    if not name:
        return ''
    return re.sub(r'\[.*?\]', '', name).strip()


def check_ms_abilities(cards):
    """MSアビリティ名がABILITY_DATAに存在するか検証。"""
    warnings = []

    # 全MSアビリティ名を収集（頻度分析用）
    name_files = {}
    for basename, fpath, ocr in cards:
        if ocr.get('type') != 'MS':
            continue
        ms_ability = ocr.get('ms_ability')
        if not ms_ability:
            continue
        name = ms_ability.get('name', '')
        if not name:
            continue
        name_files.setdefault(name, []).append(basename)

    for basename, fpath, ocr in cards:
        if ocr.get('type') != 'MS':
            continue
        ms_ability = ocr.get('ms_ability')
        if not ms_ability:
            continue

        name = ms_ability.get('name', '')
        if not name:
            continue

        base_name = extract_ability_base_name(name)

        if base_name in ABILITY_DATA:
            continue

        count = len(name_files.get(name, []))
        warnings.append({
            'level': 'WARNING',
            'message': f'未知のアビリティ名: "{name}" ({basename})',
            'detail': f'ABILITY_DATAに未登録（出現: {count}回）',
        })

    # 出現1回のみのアビリティ名を追加報告
    rare_names = {n: files for n, files in name_files.items() if len(files) == 1}
    for rare_name, files in sorted(rare_names.items()):
        base_name = extract_ability_base_name(rare_name)
        if base_name in ABILITY_DATA:
            # 既知アビリティだが出現1回のみ → OCRエラーの可能性
            warnings.append({
                'level': 'INFO',
                'message': f'1回のみ出現: "{rare_name}" ({files[0]})',
                'detail': 'OCRエラーの可能性あり（出現1回のみ）',
            })

    return warnings


# ====================================================================
# 1-E: パイロットスキル名の頻度分析（出現1回 = OCRエラー候補）
# ====================================================================

def check_pilot_skills(cards):
    """PLカードのパイロットスキル名を頻度分析。1回のみ出現の名前をOCRエラーの可能性として報告。"""
    warnings = []

    # 全パイロットスキル名を収集
    name_files = {}
    for basename, fpath, ocr in cards:
        if ocr.get('type') != 'PL':
            continue
        ps = ocr.get('pilot_skill') or ocr.get('pl_skill')
        if not ps:
            continue
        name = ps.get('name', '')
        if not name:
            continue
        name_files.setdefault(name, []).append(basename)

    # 出現1回のものを抽出（OCRエラーの可能性が高い）
    rare_names = {n: files for n, files in name_files.items() if len(files) == 1}

    for rare_name, files in sorted(rare_names.items()):
        warnings.append({
            'level': 'WARNING',
            'message': f'1回のみ出現: "{rare_name}" ({files[0]})',
            'detail': 'OCRエラーの可能性あり（出現1回のみ）',
        })

    return warnings


# ====================================================================
# 1-F: 構造的整合性チェック
# ====================================================================

def check_structure(cards):
    """構造的な整合性をチェック。"""
    warnings = []

    for basename, fpath, ocr in cards:
        card_type = ocr.get('type', '')

        # type が MS or PL のいずれか
        if card_type not in VALID_TYPES:
            warnings.append({
                'level': 'ERROR',
                'message': f'不正なtype: "{card_type}" ({basename})',
                'detail': f'期待値: {VALID_TYPES}',
            })

        # card_label.class と category の一致確認
        card_label = ocr.get('card_label', {})
        label_class = card_label.get('class', '')
        category = ocr.get('category', '')
        if label_class and category and label_class != category:
            warnings.append({
                'level': 'ERROR',
                'message': f'card_label.class="{label_class}" != category="{category}" ({basename})',
                'detail': '',
            })

        # card_id と card_number の一致確認（card_number は親オブジェクト側だが ocr_data にも card_id がある）
        card_id = ocr.get('card_id', '')
        # card_number はファイル名から推定 or ocr_data 外のフィールド
        # ここでは card_id の存在のみチェック

        # rarity の検証
        rarity = ocr.get('rarity')
        if rarity is not None and rarity not in VALID_RARITIES:
            warnings.append({
                'level': 'WARNING',
                'message': f'不明なレアリティ: "{rarity}" ({basename})',
                'detail': f'期待値: {sorted(VALID_RARITIES)}',
            })

        # terrain_compatibility の検証（MS のみ）
        if card_type == 'MS':
            terrain = ocr.get('terrain_compatibility', {})
            if terrain and isinstance(terrain, dict):
                for field in ['ground', 'space', 'desert', 'water']:
                    val = terrain.get(field)
                    if val not in VALID_TERRAIN_RANKS:
                        warnings.append({
                            'level': 'WARNING',
                            'message': f'不正な地形適性: {field}="{val}" ({basename})',
                            'detail': f'期待値: {sorted(r for r in VALID_TERRAIN_RANKS if r is not None)} or null',
                        })

        # stats の検証
        stats = ocr.get('stats', {})
        if stats and isinstance(stats, dict):
            for field in ['mobility', 'ranged_attack', 'melee_attack', 'hp']:
                val = stats.get(field)
                if val is not None:
                    if not isinstance(val, (int, float)):
                        warnings.append({
                            'level': 'WARNING',
                            'message': f'stats.{field} が非数値: "{val}" ({basename})',
                            'detail': '',
                        })
                    elif val < 0:
                        warnings.append({
                            'level': 'ERROR',
                            'message': f'stats.{field} が負の値: {val} ({basename})',
                            'detail': '',
                        })

        # cost の検証
        cost = ocr.get('cost')
        if cost is not None:
            if not isinstance(cost, int) or cost < 1 or cost > 8:
                warnings.append({
                    'level': 'WARNING',
                    'message': f'不正なコスト: {cost} ({basename})',
                    'detail': '期待値: 1〜8の整数',
                })

        # MS固有フィールド
        if card_type == 'MS':
            if not ocr.get('weapon'):
                warnings.append({
                    'level': 'WARNING',
                    'message': f'MSカードに weapon がない ({basename})',
                    'detail': '',
                })
            if not ocr.get('ms_ability'):
                warnings.append({
                    'level': 'WARNING',
                    'message': f'MSカードに ms_ability がない ({basename})',
                    'detail': '',
                })

        # PL固有フィールド
        if card_type == 'PL':
            if not ocr.get('pilot_skill') and not ocr.get('pl_skill'):
                warnings.append({
                    'level': 'WARNING',
                    'message': f'PLカードに pilot_skill がない ({basename})',
                    'detail': 'pilot_skill または pl_skill のいずれかが必要',
                })

    return warnings


# ====================================================================
# 補正適用ロジック
# ====================================================================

def _apply_char_normalize(text):
    """文字正規化を適用し、変更があれば (old, new) を返す。なければ None。"""
    normalized = normalize_chars(text)
    if normalized != text:
        return (text, normalized)
    return None


def apply_corrections(cards, corrections, dry_run=False):
    """補正辞書＋文字正規化に基づいて _basic.json を修正する。

    Returns:
        list of (filename, fpath, changes_list) — 変更があったファイルと変更内容
    """
    link_name_map = corrections.get('link_ability_names', {})
    pilot_skill_map = corrections.get('pilot_skill_names', {})
    ms_ability_map = corrections.get('ms_ability_names', {})
    link_effect_map = corrections.get('link_effects', {})

    all_changes = []

    for basename, fpath, ocr in cards:
        changes = []

        # リンクアビリティの補正
        for link in get_link_abilities(ocr):
            name = link.get('name', '')

            # 1) 文字正規化（外国語文字→日本語文字）
            norm = _apply_char_normalize(name)
            if norm:
                changes.append(f'link_ability.name [文字正規化]: "{norm[0]}" → "{norm[1]}"')
                if not dry_run:
                    link['name'] = norm[1]
                name = norm[1]  # 正規化後の値で辞書チェックを続行

            # 2) 補正辞書
            if name in link_name_map:
                new_name = link_name_map[name]
                changes.append(f'link_ability.name: "{name}" → "{new_name}"')
                if not dry_run:
                    link['name'] = new_name

            # リンク効果の補正
            effect = link.get('effect', '')
            if effect in link_effect_map:
                new_effect = link_effect_map[effect]
                changes.append(f'link_ability.effect: "{effect}" → "{new_effect}"')
                if not dry_run:
                    link['effect'] = new_effect

        # MSアビリティ名の補正
        if ocr.get('type') == 'MS':
            ms_ability = ocr.get('ms_ability')
            if ms_ability:
                name = ms_ability.get('name', '')
                norm = _apply_char_normalize(name)
                if norm:
                    changes.append(f'ms_ability.name [文字正規化]: "{norm[0]}" → "{norm[1]}"')
                    if not dry_run:
                        ms_ability['name'] = norm[1]
                    name = norm[1]
                if name in ms_ability_map:
                    new_name = ms_ability_map[name]
                    changes.append(f'ms_ability.name: "{name}" → "{new_name}"')
                    if not dry_run:
                        ms_ability['name'] = new_name

        # パイロットスキル名の補正
        if ocr.get('type') == 'PL':
            ps = ocr.get('pilot_skill') or ocr.get('pl_skill')
            if ps:
                name = ps.get('name', '')
                norm = _apply_char_normalize(name)
                if norm:
                    changes.append(f'pilot_skill.name [文字正規化]: "{norm[0]}" → "{norm[1]}"')
                    if not dry_run:
                        ps['name'] = norm[1]
                    name = norm[1]
                if name in pilot_skill_map:
                    new_name = pilot_skill_map[name]
                    changes.append(f'pilot_skill.name: "{name}" → "{new_name}"')
                    if not dry_run:
                        ps['name'] = new_name

        if changes:
            all_changes.append((basename, fpath, changes))

            # ファイルに書き戻す
            if not dry_run:
                with open(fpath, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                raw['ocr_data'] = ocr
                with open(fpath, 'w', encoding='utf-8') as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)

    return all_changes


# ====================================================================
# フィールドパス解決ヘルパー
# ====================================================================

def _resolve_field(ocr_data, field):
    """フィールドパス文字列からオブジェクト参照を解決する。

    例:
        'link_ability[0].name' → (ocr_data['link_ability'][0], 'name')
        'ms_ability.name'      → (ocr_data['ms_ability'], 'name')
        'pilot_skill.name'     → (ocr_data['pilot_skill'], 'name')

    link_ability / link_abilities エイリアス対応。
    pilot_skill / pl_skill エイリアス対応。

    Returns:
        (parent_obj, key) or (None, None) if resolution fails
    """
    # トップレベルフィールドを抽出
    parts = field.split('.', 1)
    top = parts[0]
    rest = parts[1] if len(parts) > 1 else None

    # 配列インデックスを解析: link_ability[0] → ('link_ability', 0)
    idx_match = re.match(r'^(.+?)\[(\d+)\]$', top)
    if idx_match:
        top_name = idx_match.group(1)
        idx = int(idx_match.group(2))
    else:
        top_name = top
        idx = None

    # エイリアス対応
    obj = ocr_data.get(top_name)
    if obj is None:
        if top_name in ('link_ability', 'link_abilities'):
            obj = ocr_data.get('link_abilities') or ocr_data.get('link_ability')
        elif top_name in ('pilot_skill', 'pl_skill'):
            obj = ocr_data.get('pilot_skill') or ocr_data.get('pl_skill')

    if obj is None:
        return (None, None)

    # 配列インデックスの解決
    if idx is not None:
        if not isinstance(obj, list) or idx >= len(obj):
            return (None, None)
        obj = obj[idx]

    # ネストされたキーの解決
    if rest is None:
        return (None, None)  # 末端キーがない

    sub_parts = rest.split('.')
    for sub in sub_parts[:-1]:
        if isinstance(obj, dict):
            obj = obj.get(sub)
        else:
            return (None, None)
        if obj is None:
            return (None, None)

    final_key = sub_parts[-1]
    if not isinstance(obj, dict):
        return (None, None)

    return (obj, final_key)


# ====================================================================
# 構造化変更プレビュー生成
# ====================================================================

def generate_correction_preview(cards, corrections):
    """補正辞書＋文字正規化に基づく変更候補を構造化リストとして返す。

    apply_corrections() と同じロジックだが、ファイルを変更せず
    構造化された変更候補リストを返す。

    Returns:
        list of dict: 各候補は
            {id, file, file_path, field, source, old_value, new_value, context}
    """
    link_name_map = corrections.get('link_ability_names', {})
    pilot_skill_map = corrections.get('pilot_skill_names', {})
    ms_ability_map = corrections.get('ms_ability_names', {})
    link_effect_map = corrections.get('link_effects', {})

    items = []
    item_id = 0

    for basename, fpath, ocr in cards:
        # リンクアビリティの補正
        link_list = get_link_abilities(ocr)
        for i, link in enumerate(link_list):
            name = link.get('name', '')

            # 1) 文字正規化
            norm = _apply_char_normalize(name)
            if norm:
                items.append({
                    'id': item_id,
                    'file': basename,
                    'file_path': fpath,
                    'field': f'link_ability[{i}].name',
                    'source': 'char_normalize',
                    'old_value': norm[0],
                    'new_value': norm[1],
                    'context': f'文字正規化',
                })
                item_id += 1
                name = norm[1]

            # 2) 辞書補正
            if name in link_name_map:
                items.append({
                    'id': item_id,
                    'file': basename,
                    'file_path': fpath,
                    'field': f'link_ability[{i}].name',
                    'source': 'dictionary',
                    'old_value': name,
                    'new_value': link_name_map[name],
                    'context': f'辞書: link_ability_names',
                })
                item_id += 1

            # リンク効果の辞書補正
            effect = link.get('effect', '')
            if effect in link_effect_map:
                items.append({
                    'id': item_id,
                    'file': basename,
                    'file_path': fpath,
                    'field': f'link_ability[{i}].effect',
                    'source': 'dictionary',
                    'old_value': effect,
                    'new_value': link_effect_map[effect],
                    'context': f'辞書: link_effects',
                })
                item_id += 1

        # MSアビリティ名の補正
        if ocr.get('type') == 'MS':
            ms_ability = ocr.get('ms_ability')
            if ms_ability:
                name = ms_ability.get('name', '')
                norm = _apply_char_normalize(name)
                if norm:
                    items.append({
                        'id': item_id,
                        'file': basename,
                        'file_path': fpath,
                        'field': 'ms_ability.name',
                        'source': 'char_normalize',
                        'old_value': norm[0],
                        'new_value': norm[1],
                        'context': f'文字正規化',
                    })
                    item_id += 1
                    name = norm[1]
                if name in ms_ability_map:
                    items.append({
                        'id': item_id,
                        'file': basename,
                        'file_path': fpath,
                        'field': 'ms_ability.name',
                        'source': 'dictionary',
                        'old_value': name,
                        'new_value': ms_ability_map[name],
                        'context': f'辞書: ms_ability_names',
                    })
                    item_id += 1

        # パイロットスキル名の補正
        if ocr.get('type') == 'PL':
            ps = ocr.get('pilot_skill') or ocr.get('pl_skill')
            if ps:
                name = ps.get('name', '')
                # pilot_skill or pl_skill のキー名を特定
                ps_field = 'pilot_skill' if ocr.get('pilot_skill') else 'pl_skill'
                norm = _apply_char_normalize(name)
                if norm:
                    items.append({
                        'id': item_id,
                        'file': basename,
                        'file_path': fpath,
                        'field': f'{ps_field}.name',
                        'source': 'char_normalize',
                        'old_value': norm[0],
                        'new_value': norm[1],
                        'context': f'文字正規化',
                    })
                    item_id += 1
                    name = norm[1]
                if name in pilot_skill_map:
                    items.append({
                        'id': item_id,
                        'file': basename,
                        'file_path': fpath,
                        'field': f'{ps_field}.name',
                        'source': 'dictionary',
                        'old_value': name,
                        'new_value': pilot_skill_map[name],
                        'context': f'辞書: pilot_skill_names',
                    })
                    item_id += 1

    return items


# ====================================================================
# 選択的修正適用
# ====================================================================

def apply_selective_corrections(change_items):
    """ユーザーが承認した変更アイテムのみをファイルに適用する。

    change_items: list of dict — generate_correction_preview() で生成されたアイテムに
                  new_value が（ユーザー編集済みの場合は上書きされて）入っている

    Returns:
        dict: {'applied': int, 'files_modified': int, 'errors': [str]}
    """
    # file_path でグループ化
    by_file = {}
    for item in change_items:
        fpath = item['file_path']
        by_file.setdefault(fpath, []).append(item)

    applied = 0
    files_modified = 0
    errors = []

    for fpath, items in by_file.items():
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                raw = json.load(f)

            ocr_data = raw.get('ocr_data')
            if not ocr_data:
                errors.append(f'{fpath}: ocr_data が見つかりません')
                continue

            file_changed = False
            for item in items:
                parent, key = _resolve_field(ocr_data, item['field'])
                if parent is None:
                    errors.append(f'{item["file"]}: フィールド "{item["field"]}" の解決に失敗')
                    continue

                parent[key] = item['new_value']
                applied += 1
                file_changed = True

            if file_changed:
                raw['ocr_data'] = ocr_data
                with open(fpath, 'w', encoding='utf-8') as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
                files_modified += 1

        except Exception as e:
            errors.append(f'{fpath}: {str(e)}')

    return {'applied': applied, 'files_modified': files_modified, 'errors': errors}


# ====================================================================
# レポート出力
# ====================================================================

CHECK_FUNCTIONS = {
    'link_names': ('リンクアビリティ名 頻度分析', check_link_names),
    'link_effects': ('リンク効果パターン検証', check_link_effects),
    'link_conditions': ('リンク条件フォーマット検証', check_link_conditions),
    'ms_abilities': ('MSアビリティ名検証', check_ms_abilities),
    'pilot_skills': ('パイロットスキル名 頻度分析', check_pilot_skills),
    'structure': ('構造整合性', check_structure),
}


def print_report(cards, checks=None):
    """バリデーションレポートを出力する。"""
    if checks is None:
        checks = list(CHECK_FUNCTIONS.keys())

    total_warnings = 0
    total_errors = 0
    total_ok = len(cards)

    for check_key in checks:
        if check_key not in CHECK_FUNCTIONS:
            print(f'[ERROR] 不明なチェック名: {check_key}')
            print(f'  利用可能: {", ".join(CHECK_FUNCTIONS.keys())}')
            continue

        title, func = CHECK_FUNCTIONS[check_key]
        print(f'\n=== {title} ===')

        results = func(cards)

        if not results:
            print('[OK] 問題なし')
            continue

        for r in results:
            level = r['level']
            if level == 'WARNING':
                total_warnings += 1
                print(f'[WARNING] {r["message"]}')
                if r.get('detail'):
                    print(f'  → {r["detail"]}')
            elif level == 'ERROR':
                total_errors += 1
                print(f'[ERROR] {r["message"]}')
                if r.get('detail'):
                    print(f'  → {r["detail"]}')
            elif level == 'INFO':
                print(f'[INFO] {r["message"]}')
                if r.get('detail'):
                    print(f'  → {r["detail"]}')
            elif level == 'OK':
                print(f'[OK] {r["message"]}')

    # サマリ
    ok_count = total_ok - total_warnings - total_errors
    if ok_count < 0:
        ok_count = 0
    print(f'\nサマリ: {total_warnings} warnings, {total_errors} errors, {len(cards)} カード検査済み')


def print_fix_report(changes, dry_run=False):
    """修正レポートを出力する。"""
    mode = 'ドライラン' if dry_run else '修正適用'
    print(f'\n=== {mode} ===')

    if not changes:
        print('補正対象なし（辞書エントリに該当するデータがありません）')
        return

    for basename, fpath, file_changes in changes:
        print(f'\n{basename}:')
        for change in file_changes:
            print(f'  {change}')

    total = sum(len(c) for _, _, c in changes)
    print(f'\n合計: {len(changes)} ファイル, {total} 件の変更')

    if not dry_run:
        print('\n注意: _basic.json を修正しました。')
        print('_sp.json / _sq_analysis.json も更新するには generate_derivatives.py を再実行してください。')


# ====================================================================
# CLI
# ====================================================================

def main():
    parser = argparse.ArgumentParser(
        description='OCR バリデーション＆補正テストシステム',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python ocr_test.py --report                     # 全チェック
  python ocr_test.py --report --check link_names  # 特定チェックのみ
  python ocr_test.py --fix                        # 補正辞書で自動修正
  python ocr_test.py --fix --dry-run              # 修正プレビュー
  python ocr_test.py --report --series VE01       # 特定シリーズのみ
""")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--report', action='store_true', help='バリデーションレポートを出力（ファイル変更なし）')
    group.add_argument('--fix', action='store_true', help='補正辞書に基づく自動修正')

    parser.add_argument('--check', type=str, action='append',
                        choices=list(CHECK_FUNCTIONS.keys()),
                        help='実行するチェック（複数指定可。省略時は全チェック）')
    parser.add_argument('--series', type=str, help='対象シリーズ（例: VE01, AB01）')
    parser.add_argument('--dry-run', action='store_true', help='修正のドライラン（変更プレビューのみ）')
    parser.add_argument('--results-dir', type=str, default=RESULTS_DIR,
                        help=f'OCR結果ディレクトリ（デフォルト: {RESULTS_DIR}）')

    args = parser.parse_args()

    # データ読み込み
    print(f'OCR結果ディレクトリ: {args.results_dir}')
    cards = load_basic_files(args.results_dir, series_filter=args.series)
    print(f'読み込み: {len(cards)} ファイル')

    if not cards:
        print('対象ファイルが見つかりません。')
        sys.exit(1)

    if args.series:
        print(f'シリーズフィルタ: {args.series}')

    if args.report:
        print_report(cards, checks=args.check)

    elif args.fix:
        corrections = load_corrections()

        # 辞書の中身を確認
        entry_count = sum(len(v) for v in corrections.values())
        if entry_count == 0:
            print('補正辞書が空です。--report で問題を確認し、辞書にエントリを追加してください。')
            sys.exit(0)

        print(f'補正辞書: {entry_count} エントリ')
        changes = apply_corrections(cards, corrections, dry_run=args.dry_run)
        print_fix_report(changes, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
