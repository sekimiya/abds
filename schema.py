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

    stats = ocr.get('stats')
    if isinstance(stats, dict):
        for old, new in STAT_ALIASES.items():
            if _rename_key(stats, old, new):
                changes.append(f'stats.{old} -> stats.{new}')

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
