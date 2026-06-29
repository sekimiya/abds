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

    la = ocr.get('link_ability')
    if isinstance(la, list):
        for entry in la:
            if not isinstance(entry, dict):
                continue
            name = entry.get('name', '') or ''
            effect = entry.get('effect', '') or ''
            cond = entry.get('condition', '') or ''
            if re.search(r'\[.+\].*(アップ|ダウン)', name):
                if re.search(r'デッキに\d枚以上', effect):
                    real_name = cond
                    real_cond = effect
                    real_effect = name
                    entry['name'] = real_name
                    entry['condition'] = real_cond
                    entry['effect'] = real_effect
                    changes.append(f'link_ability: name/cond/effect入替({real_name})')
                elif re.search(r'.+\sデッキに\d枚以上', cond):
                    m = re.match(r'(.+?)\s+(デッキに\d枚以上)', cond)
                    if m:
                        entry['name'] = m.group(1)
                        entry['condition'] = m.group(2)
                        entry['effect'] = name
                        changes.append(f'link_ability: cond分離+name/effect入替({m.group(1)})')

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


def _safe_int(val, default=0):
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        m = re.search(r'\d+', val)
        return int(m.group()) if m else default
    return default


def _extract_links(ocr):
    """link_ability/link_abilitiesを統一リスト形式で取得"""
    la = ocr.get('link_ability') or ocr.get('link_abilities') or []
    if isinstance(la, dict):
        if 'condition_2' in la:
            la2 = {'name': la.get('name', ''), 'condition': la.get('condition_2', ''),
                    'effect': la.get('effect_2', '')}
            la1 = {'name': la.get('name', ''), 'condition': la.get('condition', ''),
                    'effect': la.get('effect', '')}
            la = [la1, la2]
        else:
            la = [la]
    result = []
    for entry in la:
        if not isinstance(entry, dict):
            continue
        name = entry.get('name', '') or ''
        effect = entry.get('effect', '') or ''
        cond = entry.get('condition', '') or ''
        if re.search(r'\[.+\].*(アップ|ダウン)', name):
            if re.search(r'デッキに\d枚以上', effect):
                name, cond, effect = cond, effect, name
            elif re.search(r'.+\sデッキに\d枚以上', cond):
                m_c = re.match(r'(.+?)\s+(デッキに\d枚以上)', cond)
                if m_c:
                    name, cond, effect = m_c.group(1), m_c.group(2), name
        is_eb = bool(entry.get('is_eb_link')) or name.startswith('[EB]') or 'ECHOES BEAT' in effect
        is_sq = bool(entry.get('is_sq_link')) or name.startswith('[SQ]') or 'SQゲージ' in effect
        is_ab = bool(entry.get('is_ab_link')) or name.startswith('[AB]')
        if name.startswith('[EB]'):
            name = re.sub(r'^\[EB\]\s*', '', name)
        elif name.startswith('[SQ]'):
            name = re.sub(r'^\[SQ\]\s*', '', name)
        elif name.startswith('[AB]'):
            name = re.sub(r'^\[AB\]\s*', '', name)
        result.append({
            'name': name,
            'condition': cond,
            'effect': effect,
            'is_eb_link': is_eb,
            'is_sq_link': is_sq,
            'is_ab_link': is_ab,
        })
    return result


def _extract_stats(ocr):
    """どのフォーマットからでもstatsを統一形式で取得"""
    stats = ocr.get('stats')
    if isinstance(stats, dict):
        return {
            'mobility': _safe_int(stats.get('mobility') or ocr.get('mobility', 0)),
            'ranged_attack': _safe_int(stats.get('ranged_attack') or stats.get('ranged', 0)),
            'melee_attack': _safe_int(stats.get('melee_attack') or stats.get('melee', 0)),
            'hp': _safe_int(stats.get('hp', 0)),
        }
    return {
        'mobility': _safe_int(ocr.get('mobility', 0)),
        'ranged_attack': _safe_int(
            ocr.get('ranged_attack') or ocr.get('long_range_attack', 0)),
        'melee_attack': _safe_int(
            ocr.get('melee_attack') or ocr.get('short_range_attack', 0)),
        'hp': _safe_int(ocr.get('hp', 0)),
    }


def _terrain_grade(val):
    """地形適性1値を正規化。項目なし(ー/-/None等)は None"""
    if not val or not isinstance(val, str):
        return None
    v = val.strip()
    return None if v in ('-', 'ー', '−', '一', '') else v


def _extract_terrain(ocr):
    """terrain_compatibility/terrainを統一形式で取得"""
    tc = ocr.get('terrain_compatibility') or ocr.get('terrain')
    if not isinstance(tc, dict):
        return {'ground': None, 'space': None, 'desert': None, 'water': None}
    return {
        'ground': _terrain_grade(tc.get('ground')),
        'space': _terrain_grade(tc.get('space')),
        'desert': _terrain_grade(tc.get('desert')),
        'water': _terrain_grade(tc.get('water') or tc.get('underwater')),
    }


def _extract_weapon(ocr):
    """weapon情報を統一形式で取得"""
    w = ocr.get('weapon')
    if not isinstance(w, dict):
        return None
    result = {}
    for slot in ('main', 'sub'):
        s = w.get(slot)
        if not isinstance(s, dict):
            result[slot] = None
            continue
        result[slot] = {
            'name': s.get('name', '') or '',
            'range': _safe_int(s.get('range')) if s.get('range') is not None else None,
            'type': s.get('type', '') or '',
        }
    return result


def _extract_ms_ability(ocr):
    """ms_abilityを統一形式で取得"""
    msa = ocr.get('ms_ability')
    if not isinstance(msa, dict):
        return None
    activation = (msa.get('activation') or msa.get('timing') or '')
    if not activation and msa.get('type') in ACTIVATION_KEYWORDS:
        activation = msa['type']
    return {
        'name': msa.get('name', '') or '',
        'activation': activation,
        'target': msa.get('target', '') or '',
        'range': _safe_int(msa.get('range')) if msa.get('range') is not None else None,
        'cost': _safe_int(msa.get('cost')) if msa.get('cost') is not None else None,
        'description': msa.get('description', '') or '',
    }


def _extract_echoes_beat(eb):
    """echoes_beat内部のフォーマットを統一"""
    if not isinstance(eb, dict):
        return None
    return {
        'name': eb.get('name') or eb.get('eb_name', '') or '',
        'level': _safe_int(eb.get('level') or eb.get('eb_level')) if (eb.get('level') or eb.get('eb_level')) else None,
        'power': _safe_int(eb.get('power') or eb.get('eb_power')) if (eb.get('power') or eb.get('eb_power')) else None,
        'range': _safe_int(eb.get('range') or eb.get('eb_range')) if (eb.get('range') or eb.get('eb_range')) else None,
        'target': eb.get('target') or eb.get('eb_target', '') or '',
        'description': eb.get('description') or eb.get('eb_description', '') or '',
    }


def _extract_squad_sp(sp):
    """squad_sp情報を統一形式で取得(special_attack内の様々な形式から)"""
    sq = sp.get('squad_sp')
    if isinstance(sq, dict):
        return {
            'name': sq.get('name', '') or '',
            'target': sq.get('target', '') or '',
            'range': _safe_int(sq.get('range')) if sq.get('range') is not None else None,
            'power': _safe_int(sq.get('power')) if sq.get('power') is not None else None,
            'description': sq.get('description', '') or '',
            'note': sq.get('note', '') or '',
        }
    name = sp.get('squad_sp_name') or sp.get('sq_sp_name', '')
    if name:
        return {
            'name': name,
            'target': sp.get('squad_sp_target') or sp.get('sq_sp_target', '') or '',
            'range': _safe_int(sp.get('squad_sp_range') or sp.get('sq_sp_range')) if (sp.get('squad_sp_range') or sp.get('sq_sp_range')) else None,
            'power': _safe_int(sp.get('squad_sp_power') or sp.get('sq_sp_power')) if (sp.get('squad_sp_power') or sp.get('sq_sp_power')) else None,
            'description': sp.get('squad_sp_description') or sp.get('sq_sp_description') or sp.get('sq_description', '') or '',
            'note': sp.get('squad_sp_condition') or sp.get('squad_rush_condition', '') or '',
        }
    return None


def _extract_united_sp(usp):
    """united_spを統一形式で取得"""
    if not isinstance(usp, dict):
        return None
    partners = usp.get('partners') or []
    if not partners:
        p1 = usp.get('partner1')
        p2 = usp.get('partner2')
        p3 = usp.get('partner3')
        p4 = usp.get('partner4')
        partners = [p for p in [p1, p2, p3, p4] if p]
    return {
        'name': usp.get('name', '') or '',
        'partners': partners,
        'target': usp.get('target', '') or '',
        'range': _safe_int(usp.get('range')) if usp.get('range') is not None else None,
        'power': _safe_int(usp.get('power')) if usp.get('power') is not None else None,
        'description': usp.get('description', '') or '',
    }


def _extract_special_attack(ocr):
    """special_attackを統一形式で取得"""
    sp = ocr.get('special_attack')
    if not isinstance(sp, dict):
        return None
    power = sp.get('power')
    if isinstance(power, str):
        m = re.match(r'(\d+)', power)
        power = int(m.group(1)) if m else None
    elif isinstance(power, (int, float)):
        power = int(power)
    else:
        power = None

    eb_raw = sp.get('echoes_beat') or ocr.get('echoes_beat')
    eb = _extract_echoes_beat(eb_raw)

    usp = _extract_united_sp(sp.get('united_sp'))
    sqsp = _extract_squad_sp(sp)

    sp_type = sp.get('sp_type', '') or ''

    return {
        'name': sp.get('name', '') or '',
        'target': sp.get('target', '') or '',
        'range': _safe_int(sp.get('range')) if sp.get('range') is not None else None,
        'sp_cost': _safe_int(sp.get('sp_cost')) if sp.get('sp_cost') is not None else None,
        'power': power,
        'description': sp.get('description', '') or '',
        'sp_type': sp_type,
        'echoes_beat': eb,
        'united_sp': usp,
        'squad_sp': sqsp,
    }


def _extract_pilot_skill(ocr):
    """pilot_skillを統一形式で取得(ms_ability形式含む)"""
    ps = ocr.get('pilot_skill')
    if not isinstance(ps, dict):
        return None
    trigger = ps.get('trigger') or ps.get('activation', '') or ''
    effect = ps.get('effect') or ps.get('description', '') or ''
    has_sq = bool(ps.get('has_sq_skill'))
    sq_details = ps.get('sq_skill_details')
    if isinstance(sq_details, dict):
        sq_details = {
            'name': sq_details.get('name', '') or '',
            'trigger': sq_details.get('trigger', '') or '',
            'effect': sq_details.get('effect', '') or '',
            'sq_gauge_effect': sq_details.get('sq_gauge_effect', '') or '',
            'sq_max_effect': sq_details.get('sq_max_effect', '') or '',
            'sq_rush_effect': sq_details.get('sq_rush_effect') or sq_details.get('squad_rush_effect', '') or '',
        }
    is_eb = bool(ps.get('is_eb_skill'))
    eb_level = ps.get('eb_trigger_level')
    if not eb_level and trigger:
        m = re.search(r'EBLv\.(\d+)', trigger)
        if m:
            eb_level = int(m.group(1))
    sq_rush = ps.get('sq_rush_effect') or ps.get('squad_rush_effect') or ''
    if isinstance(sq_rush, dict):
        sq_rush = sq_rush.get('effect', '') or ''
    return {
        'name': ps.get('name', '') or '',
        'trigger': trigger,
        'effect': effect,
        'has_sq_skill': has_sq,
        'sq_skill_details': sq_details,
        'is_eb_skill': is_eb,
        'eb_trigger_level': eb_level,
        'sq_rush_effect': sq_rush,
    }


def _extract_physical(ocr):
    """PL物理情報を統一形式で取得"""
    phys = ocr.get('physical')
    if isinstance(phys, dict):
        raw_age = phys.get('age')
        if isinstance(raw_age, int):
            age = raw_age
        elif isinstance(raw_age, str) and raw_age not in ('', 'ー', '-', '−'):
            age = _safe_int(raw_age, default=None)
        else:
            age = None
        return {
            'height': phys.get('height', '') or '',
            'age': age,
        }
    h = ocr.get('height', '') or ''
    a = ocr.get('age')
    if isinstance(a, int):
        age = a
    elif isinstance(a, str) and a not in ('', 'ー', '-', '−'):
        age = _safe_int(a, default=None)
    else:
        age = None
    if h or age is not None:
        return {'height': str(h), 'age': age}
    return None


def _extract_units(ocr):
    """PL搭乗機体を統一リスト形式で取得"""
    units = ocr.get('units')
    if isinstance(units, list):
        return units
    for key in ('boarding_ms', 'riding_ms', 'piloted_ms', 'mobile_suit',
                'ms', 'boarding_machine', 'piloted_units'):
        val = ocr.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, str) and val:
            return [val]
    return None


def canonicalize_ocr_data(ocr, card_name=''):
    """OCRデータをカノニカル形式に変換。入力フォーマットに依存しない統一出力を返す。"""
    if not ocr or not isinstance(ocr, dict):
        return {}

    card_type = ocr.get('type', 'MS')
    name = card_name or ocr.get('name', '') or ''
    if not name:
        for alias in NAME_ALIASES:
            name = ocr.get(alias, '') or ''
            if name:
                break

    base = {
        'type': card_type,
        'name': name,
        'cost': _safe_int(ocr.get('cost', 0)),
        'rarity': ocr.get('rarity', '') or '',
        'category': (ocr.get('card_label', {}) or {}).get('class', '') or ocr.get('category', '') or '',
        'affiliation': '' if ocr.get('affiliation', '') in ('', 'ー', '−', '-') else ocr.get('affiliation', ''),
        'illustrator': ocr.get('illustrator', '') or '',
        'stats': _extract_stats(ocr),
        'link_ability': _extract_links(ocr),
    }

    if card_type == 'MS':
        base['pilot'] = ocr.get('pilot', '') or ''
        base['model'] = ocr.get('model', '') or ''
        base['terrain_compatibility'] = _extract_terrain(ocr)
        base['weapon'] = _extract_weapon(ocr)
        base['ms_ability'] = _extract_ms_ability(ocr)
        base['special_attack'] = _extract_special_attack(ocr)
    else:
        base['english_name'] = ocr.get('english_name') or ocr.get('name_en', '') or ''
        base['physical'] = _extract_physical(ocr)
        base['units'] = _extract_units(ocr)
        base['pilot_skill'] = _extract_pilot_skill(ocr)

    return base


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
