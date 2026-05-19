#!/usr/bin/env python3
"""
schema.py - OCRデータの正規スキーマ定義・正規化・バリデーション

正規フィールド名:
  stats: mobility, ranged_attack, melee_attack, hp
  リンク: link_ability (単数形)
  MSアビリティ発動条件: ms_ability.activation
"""

import re

ACTIVATION_KEYWORDS = {'任意発動', '出撃時発動', '常時発動', '自動発動', 'デッキに2枚以上'}

STAT_ALIASES = {
    'ranged': 'ranged_attack',
    'melee': 'melee_attack',
}

TOP_LEVEL_STAT_ALIASES = {
    'long_range_attack': 'ranged_attack',
    'short_range_attack': 'melee_attack',
    'ranged_attack': 'ranged_attack',
    'melee_attack': 'melee_attack',
}

NAME_ALIASES = ['ms_name_jp', 'ms_name', 'card_name_jp']

TERRAIN_KEY_ALIASES = {
    'underwater': 'water',
}

LINK_ALIASES = {
    'link_abilities': 'link_ability',
}


def _rename_key(d, old, new):
    if old in d and new not in d:
        d[new] = d.pop(old)
        return True
    return False


def normalize_ocr_data(data):
    """OCR _basic.json 1件を正規化する。
    Returns: (data, list[str]) - 正規化後データと変更内容リスト
    """
    changes = []
    ocr = data.get('ocr_data')
    if not ocr or not isinstance(ocr, dict):
        return data, changes

    if not ocr.get('name'):
        for alias in NAME_ALIASES:
            if ocr.get(alias):
                ocr['name'] = ocr[alias]
                changes.append(f'{alias} -> name')
                break

    stats = ocr.get('stats')
    if not isinstance(stats, dict):
        stats = {}
        has_top_stats = False
        for old, new in TOP_LEVEL_STAT_ALIASES.items():
            if old in ocr:
                stats[new] = ocr.pop(old)
                has_top_stats = True
                changes.append(f'{old} -> stats.{new}')
        if 'mobility' in ocr and isinstance(ocr['mobility'], (int, float)):
            stats['mobility'] = ocr.pop('mobility')
            has_top_stats = True
            changes.append('mobility -> stats.mobility')
        if 'hp' in ocr and isinstance(ocr['hp'], (int, float)):
            stats['hp'] = ocr.pop('hp')
            has_top_stats = True
            changes.append('hp -> stats.hp')
        if has_top_stats:
            ocr['stats'] = stats
    else:
        for old, new in STAT_ALIASES.items():
            if _rename_key(stats, old, new):
                changes.append(f'stats.{old} -> stats.{new}')
        if 'mobility' in ocr and isinstance(ocr['mobility'], (int, float)) and 'mobility' not in stats:
            stats['mobility'] = ocr.pop('mobility')
            changes.append('mobility -> stats.mobility')

    if 'terrain' in ocr and 'terrain_compatibility' not in ocr:
        t = ocr.get('terrain')
        if isinstance(t, dict):
            for old_k, new_k in TERRAIN_KEY_ALIASES.items():
                if old_k in t and new_k not in t:
                    t[new_k] = t.pop(old_k)
                    changes.append(f'terrain.{old_k} -> terrain.{new_k}')
            ocr['terrain_compatibility'] = ocr.pop('terrain')
            changes.append('terrain -> terrain_compatibility')

    la = ocr.get('link_ability')
    if isinstance(la, dict) and not isinstance(la, list):
        ocr['link_ability'] = [la]
        changes.append('link_ability: dict -> list')
        la = ocr['link_ability']

    eb_la = ocr.get('eb_link_ability')
    if isinstance(eb_la, dict):
        eb_la['is_eb_link'] = True
        if not isinstance(la, list):
            la = []
        la.append(eb_la)
        ocr['link_ability'] = la
        del ocr['eb_link_ability']
        changes.append('eb_link_ability -> link_ability (is_eb_link=true)')

    sp = ocr.get('special_attack')
    if isinstance(sp, dict):
        top_eb = ocr.get('echoes_beat')
        if isinstance(top_eb, dict) and 'echoes_beat' not in sp:
            sp['echoes_beat'] = top_eb
            if not sp.get('sp_type'):
                sp['sp_type'] = 'ECHOES BEAT'
            del ocr['echoes_beat']
            changes.append('echoes_beat -> special_attack.echoes_beat')

    sp_data = ocr.get('sp')
    if isinstance(sp_data, dict) and isinstance(sp, dict):
        if not sp.get('power') and sp_data.get('power'):
            power = sp_data['power']
            if isinstance(power, dict):
                sp['power'] = power.get('base', 0)
            else:
                sp['power'] = power
        if not sp.get('range') and sp_data.get('range'):
            sp['range'] = sp_data['range']
        if not sp.get('sp_cost') and sp_data.get('cost'):
            sp['sp_cost'] = sp_data['cost']
        if not sp.get('target') and sp_data.get('area'):
            sp['target'] = sp_data['area']
        if not sp.get('description'):
            sp['description'] = sp_data.get('description', '')
        changes.append('sp -> special_attack (merged)')
        del ocr['sp']

    for old, new in LINK_ALIASES.items():
        if old in ocr and new in ocr:
            del ocr[old]
            changes.append(f'{old} removed (duplicate of {new})')
        elif _rename_key(ocr, old, new):
            changes.append(f'{old} -> {new}')

    msa = ocr.get('ms_ability')
    if isinstance(msa, dict):
        if _rename_key(msa, 'timing', 'activation'):
            changes.append('ms_ability.timing -> ms_ability.activation')
        if 'type' in msa and 'activation' not in msa:
            if msa['type'] in ACTIVATION_KEYWORDS:
                msa['activation'] = msa.pop('type')
                changes.append('ms_ability.type -> ms_ability.activation')

    return data, changes


def validate_ocr_basic(data):
    """OCR _basic.json のバリデーション。エラーリストを返す(空=OK)。"""
    errors = []
    cn = data.get('card_number', '?')

    if not data.get('card_number'):
        errors.append(f'{cn}: card_number missing')
    ocr = data.get('ocr_data')
    if not ocr or not isinstance(ocr, dict):
        errors.append(f'{cn}: ocr_data missing or invalid')
        return errors

    if not ocr.get('name'):
        errors.append(f'{cn}: ocr_data.name missing')
    if not ocr.get('type'):
        errors.append(f'{cn}: ocr_data.type missing')

    stats = ocr.get('stats')
    if not isinstance(stats, dict):
        errors.append(f'{cn}: ocr_data.stats missing')
    else:
        for alias in STAT_ALIASES:
            if alias in stats:
                errors.append(f'{cn}: non-canonical stat field "{alias}"')

    if 'link_abilities' in ocr:
        errors.append(f'{cn}: non-canonical "link_abilities" (should be "link_ability")')

    msa = ocr.get('ms_ability')
    if isinstance(msa, dict):
        if 'timing' in msa:
            errors.append(f'{cn}: non-canonical "ms_ability.timing"')
        if 'type' in msa and 'activation' not in msa and msa['type'] in ACTIVATION_KEYWORDS:
            errors.append(f'{cn}: non-canonical "ms_ability.type" used as activation')

    return errors


def validate_card_index_entry(entry):
    """card_index エントリのバリデーション。"""
    errors = []
    num = entry.get('number', '?')

    if not entry.get('name'):
        errors.append(f'{num}: name empty')
    if not entry.get('front_url'):
        errors.append(f'{num}: front_url empty')
    if not entry.get('has_ocr'):
        errors.append(f'{num}: has_ocr is false')

    for field in ('mobility', 'ranged', 'melee', 'hp'):
        val = entry.get(field)
        if not isinstance(val, (int, float)):
            errors.append(f'{num}: {field} is not numeric ({val})')

    return errors


def validate_card_details_entry(num, entry):
    """card_details エントリのバリデーション。"""
    errors = []
    ocr = entry.get('ocr_data', {})
    if not ocr:
        errors.append(f'{num}: ocr_data empty')
        return errors

    if not ocr.get('name') and not entry.get('name'):
        errors.append(f'{num}: name missing in details')

    return errors
