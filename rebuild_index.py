#!/usr/bin/env python3
"""
アプリデータ再構築スクリプト

ocr_results_debug/ の _basic.json をソースとして、
data/card_index.json, data/card_details.json, data/link_index.json, data/version.json を再構築する。

使い方:
  python rebuild_index.py                  # 差分追加(新規カードのみ追加)
  python rebuild_index.py --full           # 全データをOCRソースから再構築
  python rebuild_index.py --dry-run        # 変更内容を表示するだけ(書き込みしない)
  python rebuild_index.py --series BP07    # 特定シリーズのみ追加/更新
"""

import json
import os
import re
import sys
import argparse
from datetime import datetime

from schema import normalize_ocr_data, canonicalize_ocr_data


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OCR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ocr_results_debug')
OCR_DIR_FALLBACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'abds-ocr', 'ocr_results_debug')
ALL_CARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'all_cards_list')

CARD_INDEX_PATH = os.path.join(DATA_DIR, 'card_index.json')
CARD_DETAILS_PATH = os.path.join(DATA_DIR, 'card_details.json')
LINK_INDEX_PATH = os.path.join(DATA_DIR, 'link_index.json')
VERSION_PATH = os.path.join(DATA_DIR, 'version.json')


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data, dry_run=False):
    if dry_run:
        return
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))


def _merge_sp_data(data, sp_path):
    """_sp.json からSP descriptionをマージ"""
    try:
        with open(sp_path, 'r', encoding='utf-8') as f:
            sp_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    ocr = data.get('ocr_data', {})
    sp = ocr.get('special_attack')
    if not isinstance(sp, dict):
        return
    descs = sp_data.get('descriptions', {})
    if not sp.get('description') and descs.get('normal_description'):
        sp['description'] = descs['normal_description']
    if not sp.get('sq_description') and descs.get('squad_description'):
        sp['sq_description'] = descs['squad_description']
    sp_info = sp_data.get('sp_info', {})
    if not sp.get('sp_type') and sp_info.get('squad_sp'):
        sp['sp_type'] = 'SQUAD SP'


def load_ocr_results(series_filter=None):
    """ocr_results_debug/ から全 _basic.json を読み込む。
    ローカルにないファイルは ../abds-ocr/ocr_results_debug/ からも読む。"""
    results = {}
    dirs = [OCR_DIR]
    if os.path.isdir(OCR_DIR_FALLBACK):
        dirs.append(OCR_DIR_FALLBACK)
    for ocr_dir in dirs:
        for fname in sorted(os.listdir(ocr_dir)):
            if not fname.endswith('_basic.json'):
                continue
            fpath = os.path.join(ocr_dir, fname)
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            num = data.get('card_number', '')
            if not num:
                continue
            if series_filter and not num.startswith(series_filter):
                continue
            if num not in results:
                data, _ = normalize_ocr_data(data)
                sp_path = fpath.replace('_basic.json', '_sp.json')
                if os.path.exists(sp_path):
                    _merge_sp_data(data, sp_path)
                card_name = data.get('card_name', '') or ''
                data['ocr_data'] = canonicalize_ocr_data(data.get('ocr_data', {}), card_name)
                results[num] = data
            else:
                print(f'警告: {num} のOCRソースが重複しています (無視: {fname})。'
                      f'同一card_numberの_basic.jsonは1つにしてください。')
    if len(dirs) > 1:
        print(f'OCRソース: ローカル + abds-ocr フォールバック')
    return results


def load_parallel_cards(ocr_results, card_details):
    """all_cards_list/ からパラレルカード(_p1, _p2等)を読み込み、
    ベースカードのOCRデータをコピーして画像URLのみ差し替える。"""
    if not os.path.isdir(ALL_CARDS_DIR):
        return {}
    parallels = {}
    for fname in sorted(os.listdir(ALL_CARDS_DIR)):
        if not fname.endswith('.json') or '_p' not in fname:
            continue
        fpath = os.path.join(ALL_CARDS_DIR, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        num = data.get('number') or data.get('card_number', '')
        if not num or '_p' not in num:
            continue
        base_num = re.sub(r'_p\d+$', '', num)
        base_ocr = ocr_results.get(base_num) or card_details.get(base_num, {})
        if not base_ocr or not base_ocr.get('ocr_data', {}).get('name'):
            continue
        parallel_data = json.loads(json.dumps(base_ocr))
        parallel_data['card_number'] = num
        front_url = data.get('front_image_url') or (data.get('front', {}) or {}).get('image_url', '')
        back_url = data.get('back_image_url') or (data.get('back', {}) or {}).get('image_url', '')
        if front_url:
            parallel_data['front_image_url'] = front_url
            if 'front' not in parallel_data:
                parallel_data['front'] = {}
            if isinstance(parallel_data.get('front'), dict):
                parallel_data['front']['image_url'] = front_url
        if back_url:
            parallel_data['back_image_url'] = back_url
            if 'back' not in parallel_data:
                parallel_data['back'] = {}
            if isinstance(parallel_data.get('back'), dict):
                parallel_data['back']['image_url'] = back_url
        parallels[num] = parallel_data
    return parallels


def detect_series(card_number):
    """カード番号からシリーズプレフィックスを推定"""
    m = re.match(r'^([A-Z]+\d*)-', card_number)
    if m:
        prefix = m.group(1)
        if prefix.startswith('PR'):
            n = int(card_number.split('-')[1].split('_')[0])
            if n <= 100:
                return 'PR-001~100'
            elif n <= 200:
                return 'PR-101~200'
            elif n <= 300:
                return 'PR-201~300'
            elif n <= 400:
                return 'PR-301~400'
            else:
                return 'PR-401~500'
        return prefix
    return ''


def get_links(ocr_data):
    """ocr_data からリンクアビリティを取得"""
    return ocr_data.get('link_ability', []) or []


def build_search_text(card_number, ocr_data):
    """検索用テキストを構築"""
    parts = [card_number.lower()]
    card_type = ocr_data.get('type', '')
    name = ocr_data.get('name', '')
    parts.append(name)

    if card_type == 'MS':
        parts.append((ocr_data.get('model', '') or '').lower())
        parts.append(ocr_data.get('pilot', '') or '')
        msa = ocr_data.get('ms_ability', {}) or {}
        parts.append(msa.get('name', ''))
        parts.append(msa.get('description', ''))
        weapon = ocr_data.get('weapon', {}) or {}
        for slot in ['main', 'sub']:
            w = weapon.get(slot, {}) or {}
            parts.append(w.get('name', ''))
        sp = ocr_data.get('special_attack', {}) or {}
        parts.append(sp.get('name', ''))
        parts.append(sp.get('description', ''))
    else:
        parts.append(ocr_data.get('english_name', '') or '')
        ps = ocr_data.get('pilot_skill', {}) or {}
        parts.append(ps.get('name', ''))
        parts.append(ps.get('description', '') or ps.get('effect', '') or '')

    for la in get_links(ocr_data):
        if not isinstance(la, dict):
            continue
        parts.append(la.get('name', ''))
        parts.append(la.get('effect', '') or '')

    raw = ocr_data.get('raw', '')
    parts.append(raw)

    return ' '.join(p for p in parts if p).lower().strip()


def detect_eb_info(ocr_data):
    """ECHOES BEAT関連情報を検出"""
    card_type = ocr_data.get('type', '')
    links = get_links(ocr_data)

    has_eb_link = False
    for la in links:
        if not isinstance(la, dict):
            continue
        desc = (la.get('effect', '') or '') + ' ' + str(la.get('is_eb_link', ''))
        if la.get('is_eb_link') or 'ECHOES BEAT' in desc:
            has_eb_link = True
            break

    # MS: ECHOES BEAT SP detection
    has_eb = False
    eb_level = None
    eb_type = ''
    eb_text = ''
    if card_type == 'MS':
        sp = ocr_data.get('special_attack', {}) or {}
        usp = sp.get('united_sp', {}) or {}
        eb_sp = sp.get('echoes_beat', {}) or {}
        usp_name = usp.get('name', '') or ''
        eb_name = eb_sp.get('name', '') or ''
        sp_type = sp.get('sp_type', '') or ''
        if usp and 'Lv.' in usp_name:
            has_eb = True
            m = re.search(r'Lv\.(\d+)', usp_name)
            if m:
                eb_level = int(m.group(1))
            if 'ECHOES BEAT SP' in str(sp) or eb_level and eb_level >= 3:
                eb_type = 'sp'
                eb_text = f"ECHOES BEAT SP\nLv.{eb_level}\n威力:{usp.get('power','')}\n{usp.get('description','')}"
            else:
                eb_type = 'normal'
                eb_text = f"ECHOES BEAT\nLv.{eb_level}\n威力:{usp.get('power','')}\n{usp.get('description','')}"
        elif eb_sp and (eb_name or sp_type in ('ECHOES BEAT', 'ECHOES BEAT SP')):
            has_eb = True
            _eb_name = eb_name or eb_sp.get('eb_name', '') or ''
            m = re.search(r'Lv\.(\d+)', _eb_name)
            if not m:
                eb_level = eb_sp.get('level') or eb_sp.get('eb_level')
            else:
                eb_level = int(m.group(1))
            eb_power = eb_sp.get('power', '') or eb_sp.get('eb_power', '')
            eb_desc = eb_sp.get('description', '') or eb_sp.get('eb_description', '')
            if eb_level and eb_level >= 3:
                eb_type = 'sp'
                eb_text = f"ECHOES BEAT SP\nLv.{eb_level}\n威力:{eb_power}\n{eb_desc}"
            else:
                eb_type = 'normal'
                eb_text = f"ECHOES BEAT\nLv.{eb_level}\n威力:{eb_power}\n{eb_desc}"

    # PL: EB skill detection
    has_eb_skill = False
    eb_skill_text = ''
    eb_trigger_level = None
    eb_trigger_cond = ''
    if card_type == 'PL':
        ps = ocr_data.get('pilot_skill', {}) or {}
        trigger = ps.get('activation', '') or ps.get('trigger', '') or ''
        if 'EBLv.' in trigger or 'EB' in trigger:
            has_eb_skill = True
            skill_name = ps.get('name', '')
            skill_desc = ps.get('description', '') or ps.get('effect', '') or ''
            eb_skill_text = f"{skill_name}\n{skill_desc}"
            m = re.search(r'EBLv\.(\d+)', trigger)
            if m:
                eb_trigger_level = int(m.group(1))
            if '上昇時' in trigger:
                eb_trigger_cond = '上昇時'
            elif '以上' in trigger:
                eb_trigger_cond = '以上'

    return {
        'has_eb': has_eb,
        'has_eb_skill': has_eb_skill,
        'has_eb_link': has_eb_link,
        'eb_level': eb_level,
        'eb_type': eb_type,
        'eb_text': eb_text,
        'eb_skill_text': eb_skill_text,
        'eb_trigger_level': eb_trigger_level,
        'eb_trigger_cond': eb_trigger_cond,
    }


def extract_effect_tags(description, sp_data=None):
    """SP/スキルのdescriptionからエフェクトタグを抽出"""
    tags = []
    desc = description or ''
    sp = sp_data or {}
    target = sp.get('target', '') or sp.get('range', '') or ''

    if '貫通' in target or '貫通' in desc:
        tags.append('貫通')
    if '範囲' in target or '範囲' in desc or '広範囲' in desc:
        tags.append('範囲')
    if 'スタン' in desc or '行動不能' in desc:
        tags.append('スタン')
    if '変身' in desc or 'に変身' in desc:
        tags.append('変身')
    if '撃破' in desc or '撃墜' in desc:
        tags.append('撃破')
    if '防衛無視' in desc or '防衛を無視' in desc:
        tags.append('防衛無視')
    if '必中' in desc:
        tags.append('必中')
    if '支援攻撃' in desc:
        tags.append('支援攻撃')
    if 'HP' in desc and ('回復' in desc or 'リペア' in desc):
        tags.append('HP回復')
    if re.search(r'アップ|小アップ|中アップ|大アップ', desc) and not re.search(r'ダウン', desc):
        tags.append('バフ')
    if re.search(r'ダウン|小ダウン|中ダウン|大ダウン', desc):
        tags.append('デバフ')

    return list(dict.fromkeys(tags))


def extract_skill_effect_tags(description):
    """PLスキルのdescriptionからSQスキル用タグを抽出"""
    tags = []
    desc = description or ''

    if '機動力' in desc and re.search(r'アップ|上昇', desc):
        tags.append('機動力UP')
    if '遠距離攻撃力' in desc and re.search(r'アップ|上昇', desc):
        tags.append('遠距離攻撃力UP')
    if '近距離攻撃力' in desc and re.search(r'アップ|上昇', desc):
        tags.append('近距離攻撃力UP')
    if 'SP' in desc and re.search(r'威力.*アップ|威力.*上昇', desc):
        tags.append('SP威力UP')
    if 'ダメージ' in desc and re.search(r'軽減|カット', desc):
        tags.append('ダメージ軽減')
    if '弱体' in desc and re.search(r'無効|解除', desc):
        tags.append('弱体無効')
    if re.search(r'全.*味方|出撃中の.*味方|全ユニット', desc) and re.search(r'アップ|上昇', desc):
        tags.append('全味方バフ')

    return list(dict.fromkeys(tags))


def detect_sq_info(ocr_data):
    """SQUAD SP / SQリンク / SQスキル関連情報を検出"""
    card_type = ocr_data.get('type', '')
    links = get_links(ocr_data)

    has_sq_link = False
    for la in links:
        if not isinstance(la, dict):
            continue
        if la.get('is_sq_link'):
            has_sq_link = True
            break

    has_sqsp = False
    sqsp_text = ''
    if card_type == 'MS':
        sp = ocr_data.get('special_attack', {}) or {}
        sp_type = sp.get('sp_type', '') or ''
        if sp_type == 'SQUAD SP':
            has_sqsp = True
            sqsp_text = f"SQUAD SP\n{sp.get('name','')}\n威力:{sp.get('power','')}\n{sp.get('description','')}"

    has_sq_skill = False
    sq_skill_text = ''
    if card_type == 'PL':
        ps = ocr_data.get('pilot_skill', {}) or {}
        if ps.get('has_sq_skill'):
            has_sq_skill = True
            sq_skill_text = f"{ps.get('name','')}\n{ps.get('description','') or ps.get('effect','')}"

    return {
        'has_sqsp': has_sqsp,
        'has_sq_skill': has_sq_skill,
        'has_sq_link': has_sq_link,
        'sqsp_text': sqsp_text,
        'sq_skill_text': sq_skill_text,
    }


def detect_ab_info(ocr_data):
    """ABリンク関連情報を検出"""
    links = get_links(ocr_data)
    has_ab_link = False
    for la in links:
        if not isinstance(la, dict):
            continue
        if la.get('is_ab_link'):
            has_ab_link = True
            break
    return {'has_ab_link': has_ab_link}


def build_card_index_entry(card_number, card_data):
    """1枚分のcard_index エントリを構築"""
    ocr = card_data.get('ocr_data', {})
    card_type = ocr.get('type', 'MS')
    stats = ocr.get('stats', {}) or {}
    label = ocr.get('card_label', {}) or {}
    tc = ocr.get('terrain_compatibility', {}) or {}

    series = detect_series(card_number)
    front_url = card_data.get('front_image_url', '') or card_data.get('front', {}).get('image_url', '')
    back_url = card_data.get('back_image_url', '') or card_data.get('back', {}).get('image_url', '')
    if not front_url:
        base = card_number.split('_')[0]
        front_url = f'https://www.gundam-ab.com/images/cardlist/card/{base}.jpg?v250630'
        back_url = f'https://www.gundam-ab.com/images/cardlist/card/{base}_b.jpg?v250630'

    eb_info = detect_eb_info(ocr)
    sq_info = detect_sq_info(ocr)
    ab_info = detect_ab_info(ocr)

    # Skill / ability name + effect tags
    skill_name = ''
    ability_name = ''
    sp_effect_tags = []
    sqsp_effect_tags = []
    ebsp_effect_tags = []
    sq_skill_effect_tags = []
    skill_effect_tags = []
    sq_rush_effect = ''

    sp = ocr.get('special_attack', {}) or {}
    sp_desc = sp.get('description', '') or ''
    sp_type = sp.get('sp_type', '') or ''

    if card_type == 'PL':
        ps = ocr.get('pilot_skill', {}) or {}
        skill_name = ps.get('name', '')
        ps_desc = ps.get('effect', '') or ''
        if ps.get('has_sq_skill'):
            sq_skill_effect_tags = extract_skill_effect_tags(ps_desc)
        skill_effect_tags = extract_skill_effect_tags(ps_desc)
        sq_rush_effect = ps.get('sq_rush_effect', '') or ''
    else:
        msa = ocr.get('ms_ability', {}) or {}
        ability_name = msa.get('name', '')
        if sp_type == 'SQUAD SP':
            sqsp_effect_tags = extract_effect_tags(sp_desc, sp)
        elif sp_type in ('ECHOES BEAT', 'ECHOES BEAT SP'):
            ebsp_effect_tags = extract_effect_tags(sp_desc, sp)
            eb_sp = sp.get('echoes_beat', {}) or {}
            if isinstance(eb_sp, dict):
                eb_desc = eb_sp.get('description', '') or ''
                if eb_desc:
                    ebsp_effect_tags = extract_effect_tags(eb_desc, eb_sp)
        elif sp_type == 'UNITED SP':
            usp = sp.get('united_sp', {}) or {}
            usp_desc = usp.get('description', '') or ''
            if usp_desc:
                sp_effect_tags = extract_effect_tags(usp_desc, usp)
        if not sp_effect_tags and sp_desc:
            sp_effect_tags = extract_effect_tags(sp_desc, sp)

    entry = {
        'number': card_number,
        'name': card_data.get('card_name', '') or ocr.get('name', ''),
        'type': card_type,
        'category': label.get('class', '') or ocr.get('category', ''),
        'cost': ocr.get('cost', 0),
        'series': series,
        'rarity': ocr.get('rarity', ''),
        'front_url': front_url,
        'back_url': back_url,
        'has_back_image': True,
        'mobility': stats.get('mobility', 0),
        'ranged': stats.get('ranged_attack', 0),
        'melee': stats.get('melee_attack', 0),
        'hp': stats.get('hp', 0),
        'has_ocr': True,
        'ocr_timestamp': card_data.get('ocr_timestamp', ''),
        'terrain': {
            'ground': tc.get('ground', ''),
            'space': tc.get('space', ''),
            'desert': tc.get('desert', ''),
            'water': tc.get('water', ''),
        },
        'search_text': build_search_text(card_number, ocr),
        'pilot': ocr.get('pilot', '') or '' if card_type == 'MS' else '',
        'model': ocr.get('model', '') or '' if card_type == 'MS' else '',
        'illustrator': ocr.get('illustrator', '') or '',
        'sq_rush_effect': sq_rush_effect,
        'sqsp_text': sq_info['sqsp_text'],
        'sq_skill_text': sq_info['sq_skill_text'],
        'has_sqsp': sq_info['has_sqsp'],
        'has_sq_skill': sq_info['has_sq_skill'],
        'has_sq_link': sq_info['has_sq_link'],
        'sq_trigger': '',
        'sq_gauge_rate': '',
        'sq_skill_effect_tags': sq_skill_effect_tags,
        'skill_name': skill_name,
        'skill_effect_tags': skill_effect_tags,
        'eb_text': eb_info['eb_text'],
        'eb_skill_text': eb_info['eb_skill_text'],
        'has_eb': eb_info['has_eb'],
        'has_eb_skill': eb_info['has_eb_skill'],
        'has_eb_link': eb_info['has_eb_link'],
        'has_ab_link': ab_info['has_ab_link'],
        'eb_level': eb_info['eb_level'],
        'eb_trigger_level': eb_info['eb_trigger_level'],
        'eb_trigger_cond': eb_info['eb_trigger_cond'],
        'eb_type': eb_info['eb_type'],
        'sp_effect_tags': sp_effect_tags,
        'sqsp_effect_tags': sqsp_effect_tags,
        'ebsp_effect_tags': ebsp_effect_tags,
        'ability_name': ability_name,
    }
    return entry


def build_card_details_entry(card_number, card_data):
    """1枚分のcard_details エントリを構築"""
    ocr = card_data.get('ocr_data', {})
    card_name = card_data.get('card_name', '') or ''
    front_url = card_data.get('front_image_url', '') or card_data.get('front', {}).get('image_url', '')
    back_url = card_data.get('back_image_url', '') or card_data.get('back', {}).get('image_url', '')

    canonical = canonicalize_ocr_data(ocr, card_name)

    return {
        'number': card_number,
        'name': canonical.get('name', '') or card_name,
        'url': front_url,
        'category': canonical.get('category', ''),
        'series': detect_series(card_number),
        'front': {'image_url': front_url},
        'back': {'image_url': back_url},
        'ocr_data': canonical,
    }


def rebuild_link_index(card_details, existing_link_index=None):
    """card_details から link_index を再構築

    - [SQ]プレフィックス付きリンク名はプレフィックスを除去して登録
    - 既存のlink_indexにある特殊エントリ(ECHOES BEAT等)は保持
    """
    link_index = {}

    for card_num, card_data in card_details.items():
        ocr = card_data.get('ocr_data', {})
        card_type = ocr.get('type', '')
        links = get_links(ocr)

        for la in links:
            if not isinstance(la, dict):
                continue
            link_name = la.get('name', '')
            if not link_name:
                continue

            # [SQ]/[EB]/[AB]プレフィックスを除去
            clean_name = re.sub(r'^\[(SQ|EB|AB)\]\s*', '', link_name)

            if clean_name not in link_index:
                link_index[clean_name] = {
                    'condition': la.get('condition', ''),
                    'effect': la.get('effect', ''),
                    'required': _parse_required(la.get('condition', '')),
                    'ms_cards': [],
                    'pl_cards': [],
                }

            entry = link_index[clean_name]
            target_key = 'pl_cards' if card_type == 'PL' else 'ms_cards'
            if card_num not in entry[target_key]:
                entry[target_key].append(card_num)

    # Sort card lists
    for data in link_index.values():
        data['ms_cards'].sort()
        data['pl_cards'].sort()

    # 既存link_indexの特殊エントリを保持 (ECHOES BEAT等、card_dataから導出できないもの)
    if existing_link_index:
        for name, data in existing_link_index.items():
            if name not in link_index:
                link_index[name] = data

    return link_index


def _parse_required(condition):
    """「デッキに3枚以上」から数値を抽出"""
    m = re.search(r'(\d+)枚', condition)
    return int(m.group(1)) if m else 0


def main():
    parser = argparse.ArgumentParser(description='アプリデータ再構築')
    parser.add_argument('--full', action='store_true', help='全データをOCRソースから再構築')
    parser.add_argument('--dry-run', action='store_true', help='変更内容を表示のみ')
    parser.add_argument('--series', type=str, default=None, help='特定シリーズのみ処理 (例: BP07)')
    parser.add_argument('--rebuild-links', action='store_true', help='link_indexのみ再構築')
    args = parser.parse_args()

    print(f'=== ABDS インデックス再構築 ===')
    print(f'モード: {"全再構築" if args.full else "差分追加"}')
    if args.series:
        print(f'対象シリーズ: {args.series}')
    if args.dry_run:
        print('(dry-run: 書き込みなし)')
    print()

    # Load existing data
    card_index = load_json(CARD_INDEX_PATH)
    card_details = load_json(CARD_DETAILS_PATH)

    existing_numbers = {c['number'] for c in card_index}
    ocr_results = load_ocr_results(series_filter=args.series)
    print(f'OCRソース: {len(ocr_results)}枚')
    print(f'既存card_index: {len(card_index)}枚')
    print(f'既存card_details: {len(card_details)}キー')
    print()

    if args.rebuild_links:
        print('link_indexのみ再構築...')
        link_index = rebuild_link_index(card_details)
        save_json(LINK_INDEX_PATH, link_index, dry_run=args.dry_run)
        print(f'link_index: {len(link_index)}リンク')
        print('完了')
        return

    # Process cards
    added = 0
    updated = 0

    if args.full:
        # Full rebuild: OCRソースから全構築
        new_index = []
        new_details = {}
        for num, data in sorted(ocr_results.items()):
            new_index.append(build_card_index_entry(num, data))
            new_details[num] = build_card_details_entry(num, data)
            added += 1

        # Keep cards NOT in OCR results (manually added, etc.)
        # パラレルカード(_p)はload_parallel_cardsで再追加するのでスキップ
        kept = 0
        for entry in card_index:
            if entry['number'] not in ocr_results and '_p' not in entry['number']:
                new_index.append(entry)
                kept += 1
        for num, data in card_details.items():
            if num not in ocr_results and '_p' not in num:
                new_details[num] = data
                kept += 1

        card_index = new_index
        card_details = new_details
        print(f'全再構築: OCRから{added}枚構築, 既存から{kept // 2}枚保持')
    else:
        # Incremental: 新規カードのみ追加
        for num, data in sorted(ocr_results.items()):
            if num in existing_numbers:
                if args.series:
                    # シリーズ指定時は更新も行う
                    card_index = [c for c in card_index if c['number'] != num]
                    card_index.append(build_card_index_entry(num, data))
                    card_details[num] = build_card_details_entry(num, data)
                    updated += 1
                continue
            card_index.append(build_card_index_entry(num, data))
            card_details[num] = build_card_details_entry(num, data)
            added += 1

    # パラレルカード(_p1, _p2等)をall_cards_listから追加
    existing_nums = {c['number'] for c in card_index}
    parallels = load_parallel_cards(ocr_results, card_details)
    parallel_added = 0
    for num, data in sorted(parallels.items()):
        if num not in existing_nums:
            card_index.append(build_card_index_entry(num, data))
            card_details[num] = build_card_details_entry(num, data)
            parallel_added += 1
    if parallel_added:
        print(f'パラレルカード追加: {parallel_added}枚')

    # Sort card_index by number
    card_index.sort(key=lambda c: c['number'])

    print(f'追加: {added}枚 (+パラレル{parallel_added}枚), 更新: {updated}枚')
    print(f'card_index: {len(card_index)}枚')
    print(f'card_details: {len(card_details)}キー')
    print()

    # Rebuild link_index from card_details
    print('link_index再構築中...')
    existing_link_index = load_json(LINK_INDEX_PATH)
    link_index = rebuild_link_index(card_details, existing_link_index)
    print(f'link_index: {len(link_index)}リンク')
    print()

    # Update version
    now = datetime.now()
    version = {
        'version': now.strftime('%Y%m%d-%H%M%S'),
        'card_count': len(card_index),
        'detail_count': len(card_details),
        'link_count': len(link_index),
        'index_hash': f'rebuild_{now.strftime("%Y%m%d")}',
        'built_at': now.isoformat(timespec='seconds'),
    }

    # Save
    if not args.dry_run:
        save_json(CARD_INDEX_PATH, card_index)
        save_json(CARD_DETAILS_PATH, card_details)
        save_json(LINK_INDEX_PATH, link_index)
        save_json(VERSION_PATH, version)
        print('全ファイル保存完了:')
        print(f'  {CARD_INDEX_PATH}')
        print(f'  {CARD_DETAILS_PATH}')
        print(f'  {LINK_INDEX_PATH}')
        print(f'  {VERSION_PATH}')
    else:
        print('(dry-run: ファイル書き込みスキップ)')

    print()
    print(f'=== 完了 ===')
    print(f'version: {version["version"]}')
    print(f'カード数: {version["card_count"]}')
    print(f'リンク数: {version["link_count"]}')


if __name__ == '__main__':
    main()
