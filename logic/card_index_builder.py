"""
card_index_builder — カードインデックス構築ロジック

app.py の _build_card_index() / _classify_sp_effects() を抽出したモジュール。
Flask 非依存。stdlib + logic.utils のみに依存する。
"""

import os
import re
import json

from .utils import safe_int, get_nested, extract_stats, get_link_abilities, parse_link_condition


def classify_sp_effects(text):
    """SP技の説明文から効果タグを分類する"""
    tags = []
    if '変身' in text:
        tags.append('変身')
    if 'スタン' in text:
        tags.append('スタン')
    if '撃破する' in text or '撃破できる' in text:
        tags.append('撃破')
    if '貫通' in text:
        tags.append('貫通')
    if '範囲' in text:
        tags.append('範囲')
    if ('機動力' in text or '攻撃力' in text or '防御力' in text) and ('ダウン' in text or '低下' in text):
        tags.append('デバフ')
    if ('機動力' in text or '攻撃力' in text or 'SP威力' in text or '防御力' in text) and ('アップ' in text or '上昇' in text or 'UP' in text):
        tags.append('バフ')
    if 'HP' in text and ('回復' in text or '大回復' in text):
        tags.append('HP回復')
    if '防衛効果' in text and '無視' in text:
        tags.append('防衛無視')
    if '必中' in text:
        tags.append('必中')
    if '支援攻撃' in text or '支援射撃' in text:
        tags.append('支援攻撃')
    return tags


def build_card_index(all_cards_dir='all_cards_list', ocr_dir='ocr_results_debug',
                     *, write_back_ocr_flags=False):
    """全カードデータとOCRデータを統合し、軽量インデックスと詳細キャッシュを構築する。

    Returns:
        tuple: (index_list, detail_map, link_map)
    """
    all_cards = []
    if os.path.exists(all_cards_dir):
        for filename in os.listdir(all_cards_dir):
            if not filename.endswith('.json'):
                continue
            try:
                fpath = os.path.join(all_cards_dir, filename)
                with open(fpath, 'r', encoding='utf-8') as f:
                    card_data = json.load(f)
                    if isinstance(card_data, list) and len(card_data) > 0:
                        card_data = card_data[0]
                    if isinstance(card_data, dict):
                        card_data['_file_path'] = fpath
                        all_cards.append(card_data)
            except Exception:
                continue

    # OCRデータ読み込み（debug形式 — _basic, _sp, _sq_analysis を統合）
    # Claude Code CLI で生成されたデータのみを信頼する
    ocr_results = {}
    ocr_timestamps = {}  # number → 最新のOCRタイムスタンプ
    _cli_trusted_numbers = set()  # Claude Code CLI で basic OCR が存在するカード番号
    if os.path.exists(ocr_dir):
        for filename in sorted(os.listdir(ocr_dir)):
            if not filename.endswith('.json'):
                continue
            try:
                base = filename.replace('.json', '')
                number_match = re.search(r'([A-Z0-9\-]{2,}-\d{2,4}(?:_p\d+)?)', base)
                if not number_match:
                    continue
                number = number_match.group(1)
                with open(os.path.join(ocr_dir, filename), 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict):
                    continue

                prev = ocr_results.get(number, {})

                # _basic.json: ocr_data を持つメインデータ
                # Claude Code CLI で生成されたデータのみ取り込む
                if 'ocr_data' in loaded and isinstance(loaded['ocr_data'], dict):
                    _eng = loaded.get('ocr_engine') or ''
                    if not (_eng.startswith('claude_code_cli') or _eng == 'claude_code_subagent'):
                        continue
                    _cli_trusted_numbers.add(number)
                    normalized = loaded['ocr_data']
                    front_url = loaded.get('front_image_url')
                    back_url = loaded.get('back_image_url')
                    if front_url:
                        normalized.setdefault('front', {})['image_url'] = front_url
                    if back_url:
                        normalized.setdefault('back', {})['image_url'] = back_url
                    if 'link_ability' in normalized and 'link_abilities' not in normalized:
                        normalized['link_abilities'] = normalized.get('link_ability')
                    # 既存データにマージ（basicが基盤）
                    # sq_analysis由来の詳細なpilot_skillが既にある場合は保護
                    _prev_ps = prev.get('pilot_skill')
                    _keep_ps = (isinstance(_prev_ps, dict) and _prev_ps.get('has_sq_skill')
                                and isinstance(_prev_ps.get('sq_skill_details'), dict))
                    prev.update(normalized)
                    if _keep_ps and 'pilot_skill' in normalized:
                        prev['pilot_skill'] = _prev_ps

                    # ms_ability 内のリンクアビリティ形式エントリを link_abilities に移動
                    _ms_ab = prev.get('ms_ability')
                    if _ms_ab:
                        _ab_list = _ms_ab if isinstance(_ms_ab, list) else [_ms_ab]
                        _real_abilities = []
                        _moved = False
                        _la_target = prev.get('link_abilities') or prev.get('link_ability') or []
                        if not isinstance(_la_target, list):
                            _la_target = [_la_target] if _la_target else []
                        _known_la_names = {l.get('name') for l in _la_target if isinstance(l, dict)}
                        for _ab in _ab_list:
                            if not isinstance(_ab, dict):
                                _real_abilities.append(_ab)
                                continue
                            _cond = _ab.get('condition', '') or ''
                            _act = _ab.get('activation') or _ab.get('type')
                            if 'デッキに' in _cond and not _act and _ab.get('name') not in _known_la_names:
                                _la_target.append({
                                    'name': _ab.get('name', ''),
                                    'condition': _cond,
                                    'effect': _ab.get('description', ''),
                                })
                                _moved = True
                            else:
                                _real_abilities.append(_ab)
                        if _moved:
                            prev['ms_ability'] = _real_abilities if _real_abilities else None
                            prev['link_abilities'] = _la_target

                # _sp.json: sp_info / power / descriptions を持つSPデータ
                if 'sp_info' in loaded or 'power' in loaded or 'descriptions' in loaded:
                    sp_info = loaded.get('sp_info', {})
                    power = loaded.get('power', {})
                    descs = loaded.get('descriptions', {})
                    sa = prev.get('special_attack') or {}
                    if not isinstance(sa, dict):
                        sa = {}
                    if sp_info.get('name') and not sa.get('name'):
                        sa['name'] = sp_info['name']
                    if sp_info.get('target') and not sa.get('target'):
                        sa['target'] = sp_info['target']
                    if sp_info.get('range') is not None and sa.get('range') is None:
                        sa['range'] = sp_info['range']
                    if sp_info.get('attack_type') and not sa.get('attack_type'):
                        sa['attack_type'] = sp_info['attack_type']
                    if sp_info.get('type') and not sa.get('sp_type'):
                        sa['sp_type'] = sp_info['type']
                    # Power
                    if power:
                        if 'power' not in sa or not isinstance(sa.get('power'), dict):
                            sa['power'] = {}
                        if power.get('normal') and not sa['power'].get('normal'):
                            sa['power']['normal'] = power['normal']
                        if power.get('squad') and not sa['power'].get('squad'):
                            sa['power']['squad'] = power['squad']
                        if power.get('united') and not sa['power'].get('united'):
                            sa['power']['united'] = power['united']
                    # Description
                    desc = descs.get('normal_description') or descs.get('all_description')
                    if desc and not sa.get('description'):
                        sa['description'] = desc
                    prev['special_attack'] = sa

                # _sq_analysis.json: pilot_skill / link_ability を持つSQデータ
                if loaded.get('sq_analysis_type') or (loaded.get('pilot_skill') and 'ocr_data' not in loaded):
                    ps = loaded.get('pilot_skill')
                    if isinstance(ps, dict) and ps.get('has_sq_skill'):
                        # SQ分析データは常に優先（_basic.jsonの不完全なpilot_skillを上書き）
                        existing_ps = prev.get('pilot_skill') or prev.get('pl_skill') or {}
                        if not isinstance(existing_ps, dict) or not existing_ps.get('has_sq_skill'):
                            prev['pilot_skill'] = ps
                        else:
                            # 既存もSQスキルありの場合、sq_skill_detailsがより詳細な方を採用
                            new_det = (ps.get('sq_skill_details') or {})
                            old_det = (existing_ps.get('sq_skill_details') or {})
                            if new_det.get('trigger') and not old_det.get('trigger'):
                                prev['pilot_skill'] = ps
                    elif ps and not prev.get('pilot_skill') and not prev.get('pl_skill'):
                        prev['pilot_skill'] = ps
                    la = loaded.get('link_ability')
                    if isinstance(la, list):
                        existing = prev.get('link_abilities') or prev.get('link_ability') or []
                        known = {l.get('name') for l in existing if isinstance(l, dict)}
                        for l in la:
                            if isinstance(l, dict) and l.get('name') not in known:
                                existing.append(l)
                        prev['link_abilities'] = existing

                # ECHOES BEAT情報の統合（_basic.json内の複数パターンを正規化）
                # トップレベルの echoes_beat dict を正規化（VE01-034等）
                _top_eb = prev.get('echoes_beat')
                if isinstance(_top_eb, dict) and not _top_eb.get('has_eb'):
                    _teb_name = _top_eb.get('name', '') or ''
                    _teb_lv_match = re.search(r'Lv\.(\d+)', _teb_name)
                    _teb_desc = _top_eb.get('description') or _top_eb.get('description_eb') or ''
                    if _teb_desc.startswith('/'):
                        _teb_desc = _teb_desc.lstrip('/').strip()
                    _teb_lv = int(_teb_lv_match.group(1)) if _teb_lv_match else None
                    prev['echoes_beat'] = {
                        'has_eb': True,
                        'eb_type': 'sp' if (_teb_lv and _teb_lv == 3) else 'normal',
                        'eb_level': _teb_lv,
                        'eb_sp_name': _teb_name,
                        'eb_description': _teb_desc,
                        'eb_power': _top_eb.get('power') or _top_eb.get('power_eb'),
                        'eb_target': _top_eb.get('target') or _top_eb.get('target_eb') or '',
                        'eb_range': _top_eb.get('range') or _top_eb.get('range_eb'),
                    }

                sa_data = prev.get('special_attack')
                if isinstance(sa_data, dict) and not prev.get('echoes_beat'):
                    is_eb_sp = sa_data.get('sp_type') == 'ECHOES BEAT SP'
                    eb = sa_data.get('echoes_beat')
                    eb_sp = sa_data.get('echoes_beat_sp')

                    # パターン1: nested dict
                    if isinstance(eb, dict) or isinstance(eb_sp, dict):
                        src = eb if isinstance(eb, dict) else eb_sp
                        eb_entry = {
                            'has_eb': True,
                            'eb_type': src.get('eb_type') or ('sp' if is_eb_sp else 'normal'),
                            'eb_level': src.get('eb_level') or src.get('level'),
                            'eb_sp_name': src.get('eb_name') or src.get('name', ''),
                            'eb_description': src.get('eb_description') or src.get('description') or src.get('description_eb') or '',
                            'eb_power': src.get('eb_power') or src.get('power') or src.get('power_eb'),
                            'eb_target': src.get('eb_target') or src.get('target') or src.get('target_eb') or '',
                            'eb_range': src.get('eb_range') or src.get('range') or src.get('range_eb'),
                        }
                        # base部分の情報もあれば保存
                        if isinstance(src.get('base'), dict):
                            eb_entry['base_power'] = src['base'].get('power')
                            eb_entry['base_description'] = src['base'].get('description', '')
                        if isinstance(src.get('lv_down'), dict):
                            eb_entry['eb_power'] = eb_entry['eb_power'] or src['lv_down'].get('power')
                            eb_entry['eb_description'] = eb_entry['eb_description'] or src['lv_down'].get('description', '')
                        prev['echoes_beat'] = eb_entry

                    # パターン2: フラットフィールド
                    elif sa_data.get('eb_level') or sa_data.get('echoes_beat_lv') or sa_data.get('eb_power') or sa_data.get('power_eb') or sa_data.get('eb_description'):
                        eb_sp_name2 = ''
                        full_name2 = sa_data.get('name', '') or ''
                        name_parts2 = full_name2.split(' ')
                        if len(name_parts2) >= 2:
                            eb_name_parts2 = []
                            found2 = False
                            for i2, p2 in enumerate(name_parts2):
                                if re.match(r'Lv\.\d+', p2):
                                    continue
                                if found2:
                                    eb_name_parts2.append(p2)
                                elif i2 > 0:
                                    found2 = True
                                    eb_name_parts2.append(p2)
                            eb_sp_name2 = ' '.join(eb_name_parts2)
                        _eb_lv2 = sa_data.get('eb_level') or sa_data.get('echoes_beat_lv')
                        _eb_pw2 = sa_data.get('eb_power') or sa_data.get('power_eb') or sa_data.get('power_enhanced')
                        _eb_desc2 = sa_data.get('eb_description', '')
                        if not _eb_desc2:
                            _full_desc2 = sa_data.get('description', '') or ''
                            if '／' in _full_desc2:
                                _eb_desc2 = _full_desc2.split('／', 1)[1].strip()
                        prev['echoes_beat'] = {
                            'has_eb': True,
                            'eb_type': 'sp' if is_eb_sp else 'normal',
                            'eb_level': _eb_lv2,
                            'eb_sp_name': eb_sp_name2,
                            'eb_description': _eb_desc2,
                            'eb_power': _eb_pw2,
                            'eb_target': sa_data.get('eb_target', '') or sa_data.get('target', ''),
                            'eb_range': sa_data.get('eb_range') or sa_data.get('range'),
                        }

                    # パターン3: power_enhanced のみ（ECHOES BEAT SP）
                    elif is_eb_sp and sa_data.get('power_enhanced'):
                        eb_desc = ''
                        full_desc = sa_data.get('description', '') or ''
                        if '／' in full_desc:
                            eb_desc = full_desc.split('／', 1)[1].strip()
                        elif 'EBLv' in full_desc:
                            eb_desc = full_desc
                        eb_sp_name = ''
                        full_name = sa_data.get('name', '') or ''
                        lv_match = re.search(r'Lv\.(\d+)', full_name)
                        eb_lv = int(lv_match.group(1)) if lv_match else 3
                        name_parts = full_name.split(' ')
                        if len(name_parts) >= 2:
                            eb_name_parts = []
                            found_second = False
                            for i, p in enumerate(name_parts):
                                if re.match(r'Lv\.\d+', p):
                                    continue
                                if found_second:
                                    eb_name_parts.append(p)
                                else:
                                    if i > 0:
                                        found_second = True
                                        eb_name_parts.append(p)
                            eb_sp_name = ' '.join(eb_name_parts)
                        prev['echoes_beat'] = {
                            'has_eb': True,
                            'eb_type': 'sp',
                            'eb_level': eb_lv,
                            'eb_sp_name': eb_sp_name,
                            'eb_description': eb_desc,
                            'eb_power': sa_data.get('power_enhanced'),
                            'eb_target': '',
                            'eb_range': None,
                        }

                    # パターン4: True / "ECHOES BEAT" 文字列
                    elif eb:
                        prev['echoes_beat'] = {'has_eb': True, 'eb_type': 'normal', 'eb_level': None}

                    # sp_type だけ ECHOES BEAT SP の場合
                    elif is_eb_sp:
                        prev['echoes_beat'] = {'has_eb': True, 'eb_type': 'sp', 'eb_level': 3}

                # パターン5: united_sp 内にEB情報がある場合（BP07等）
                if isinstance(sa_data, dict) and not prev.get('echoes_beat'):
                    _usp = sa_data.get('united_sp')
                    if isinstance(_usp, dict) and _usp.get('description'):
                        _usp_desc = _usp['description']
                        _usp_name = _usp.get('name', '') or ''
                        _eb_lv_down = re.search(r'EBLv\.を(\d+)下げる', _usp_desc)
                        _eb_lv_name = re.search(r'Lv\.(\d+)', _usp_name)
                        if _eb_lv_down or _eb_lv_name:
                            _lv = int((_eb_lv_name or _eb_lv_down).group(1))
                            _is_sp = _lv == 3 or 'EBLv.を3下げる' in _usp_desc
                            prev['echoes_beat'] = {
                                'has_eb': True,
                                'eb_type': 'sp' if _is_sp else 'normal',
                                'eb_level': _lv,
                                'eb_sp_name': _usp_name,
                                'eb_description': _usp_desc,
                                'eb_power': _usp.get('power'),
                                'eb_target': _usp.get('target', ''),
                                'eb_range': _usp.get('range'),
                            }
                            sa_data['echoes_beat'] = {
                                'level': _lv,
                                'name': _usp_name,
                                'target': _usp.get('target'),
                                'range': _usp.get('range'),
                                'power': _usp.get('power'),
                                'description': _usp_desc,
                            }
                            if _is_sp:
                                sa_data['sp_type'] = 'ECHOES BEAT SP'

                # sa_data['echoes_beat'] を UI が期待する {name, level, ...} 形式に正規化
                _eb_prev = prev.get('echoes_beat')
                if isinstance(sa_data, dict) and isinstance(_eb_prev, dict) and _eb_prev.get('has_eb'):
                    _sa_eb = sa_data.get('echoes_beat')
                    sa_data['echoes_beat'] = {
                        'level': ((_sa_eb or {}).get('level') or (_sa_eb or {}).get('eb_level')
                                  or _eb_prev.get('eb_level')),
                        'name': ((_sa_eb or {}).get('name') or (_sa_eb or {}).get('eb_name')
                                 or _eb_prev.get('eb_sp_name', '')),
                        'target': ((_sa_eb or {}).get('target') or (_sa_eb or {}).get('eb_target')
                                   or _eb_prev.get('eb_target')),
                        'range': ((_sa_eb or {}).get('range') or (_sa_eb or {}).get('eb_range')
                                  or _eb_prev.get('eb_range')),
                        'power': ((_sa_eb or {}).get('power') or (_sa_eb or {}).get('eb_power')
                                  or _eb_prev.get('eb_power')),
                        'description': ((_sa_eb or {}).get('description') or (_sa_eb or {}).get('eb_description')
                                        or _eb_prev.get('eb_description', '')),
                    }

                # _ocr_raw.json の raw テキストから EB 情報を補完
                raw_ocr = loaded.get('raw_ocr_text', '')
                if raw_ocr and 'ECHOES BEAT' in raw_ocr and not prev.get('echoes_beat'):
                    eb_lv_match = re.search(r'Lv\.(\d+)', raw_ocr[raw_ocr.index('ECHOES BEAT'):])
                    if eb_lv_match:
                        lv = int(eb_lv_match.group(1))
                        eb_type = 'sp' if lv == 3 or 'ECHOES BEAT SP' in raw_ocr else 'normal'
                        prev['echoes_beat'] = {'has_eb': True, 'eb_type': eb_type, 'eb_level': lv}

                # SP攻撃のdescriptionからEB部分を分離（"/" or "／" で区切り）
                _eb_generic_notes = [
                    'ECHOES BEAT Lv.を下げることで、共鳴戦術技が発動する。',
                    'ECHOES BEAT Lv.を下げることで、Lv.戦術技が発動する。',
                ]
                _sa_final = prev.get('special_attack')
                if isinstance(_sa_final, dict):
                    _desc = _sa_final.get('description', '') or ''
                    # generic EB note を除去
                    for _gn in _eb_generic_notes:
                        _desc = _desc.replace(_gn, '').strip()
                    # "／"（全角）で分割
                    _split_done = False
                    if '／' in _desc:
                        _parts = _desc.split('／', 1)
                        _normal = _parts[0].strip()
                        _eb_part = _parts[1].strip()
                        if _eb_part and _eb_part not in ('ー', '—', '-'):
                            _sa_final['description'] = _normal
                            _eb_obj = prev.get('echoes_beat')
                            if isinstance(_eb_obj, dict):
                                _exist_desc = _eb_obj.get('eb_description', '')
                                if not _exist_desc or any(g in _exist_desc for g in _eb_generic_notes):
                                    _eb_obj['eb_description'] = _eb_part
                        else:
                            _sa_final['description'] = _normal
                        _split_done = True
                    # "/ " followed by "EBLv" or "ー" or "—" で分割（半角）
                    if not _split_done:
                        _eb_sep_match = re.search(r'/\s*(EBLv|ー|—)', _desc)
                        if _eb_sep_match:
                            _normal = _desc[:_eb_sep_match.start()].strip()
                            _eb_part = _desc[_eb_sep_match.start()+1:].strip()
                            if _eb_part and _eb_part not in ('ー', '—', '-'):
                                _sa_final['description'] = _normal
                                _eb_obj = prev.get('echoes_beat')
                                if isinstance(_eb_obj, dict):
                                    _exist_desc = _eb_obj.get('eb_description', '')
                                    if not _exist_desc or any(g in _exist_desc for g in _eb_generic_notes):
                                        _eb_obj['eb_description'] = _eb_part
                            else:
                                _sa_final['description'] = _normal
                            _split_done = True
                    if not _split_done:
                        _sa_final['description'] = _desc
                # echoes_beat の eb_description から先頭の "/" や generic note を除去
                _eb_clean = prev.get('echoes_beat')
                if isinstance(_eb_clean, dict):
                    _ebd = _eb_clean.get('eb_description', '') or ''
                    if _ebd.startswith('/'):
                        _ebd = _ebd.lstrip('/').strip()
                    for _gn in _eb_generic_notes:
                        _ebd = _ebd.replace(_gn, '').strip()
                    _eb_clean['eb_description'] = _ebd

                # PL の EB PL SKILL 検出
                if raw_ocr and 'EB PL SKILL' in raw_ocr:
                    ps = prev.get('pilot_skill') or prev.get('pl_skill')
                    if isinstance(ps, dict):
                        ps['is_eb_skill'] = True
                        eb_trig = re.search(r'EBLv\.(\d+)', ps.get('trigger', '') or ps.get('effect', ''))
                        if eb_trig:
                            ps['eb_trigger_level'] = int(eb_trig.group(1))
                elif isinstance(loaded.get('ocr_data'), dict):
                    # _basic.json 内の pilot_skill.trigger からも検出
                    ps = prev.get('pilot_skill') or prev.get('pl_skill')
                    if isinstance(ps, dict):
                        trig = ps.get('trigger', '') or ''
                        if 'EBLv' in trig or 'EB' in ps.get('name', ''):
                            ps['is_eb_skill'] = True
                            eb_trig = re.search(r'EBLv\.(\d+)', trig)
                            if eb_trig:
                                ps['eb_trigger_level'] = int(eb_trig.group(1))

                # PL の EB LINK ABILITY 検出
                la_list = prev.get('link_abilities') or prev.get('link_ability') or []
                if isinstance(la_list, list):
                    for la_item in la_list:
                        if isinstance(la_item, dict):
                            eff = la_item.get('effect', '')
                            if 'ECHOES BEAT' in eff or 'EBLv' in eff:
                                la_item['is_eb_link'] = True

                # AB LINK ABILITY 検出
                _ab_link_names = {'不思議な音', '閃光', '俺たちのトライエイジ'}
                if isinstance(la_list, list):
                    for la_item in la_list:
                        if isinstance(la_item, dict):
                            la_name = la_item.get('name', '').strip()
                            bare_name = la_name.replace('[AB]', '')
                            if bare_name in _ab_link_names:
                                la_item['is_ab_link'] = True
                                if not la_name.startswith('[AB]'):
                                    la_item['name'] = f'[AB]{la_name}'

                # タイムスタンプ収集（各ファイル種別のタイムスタンプから最新を取得）
                for ts_key in ['ocr_timestamp', 'sp_ocr_timestamp', 'sq_analysis_timestamp']:
                    ts = loaded.get(ts_key)
                    if ts:
                        existing_ts = ocr_timestamps.get(number, '')
                        if ts > existing_ts:
                            ocr_timestamps[number] = ts

                ocr_results[number] = prev
            except Exception:
                continue

    # Claude Code CLI の basic OCR データがないカードの OCR 結果を除去
    for _num in list(ocr_results.keys()):
        if _num not in _cli_trusted_numbers:
            del ocr_results[_num]
            ocr_timestamps.pop(_num, None)

    # 統合してインデックスと詳細を構築
    index_list = []
    detail_map = {}
    seen_numbers = set()

    for card in all_cards:
        card_number = card.get('number', '')
        if not card_number or card_number in seen_numbers:
            continue
        seen_numbers.add(card_number)

        ocr_data = ocr_results.get(card_number, {})
        # イラスト違い (_p1, _p2 等) はベース番号のOCRデータをフォールバック参照
        if not ocr_data:
            _base_num = re.sub(r'_p\d+$', '', card_number)
            if _base_num != card_number:
                ocr_data = ocr_results.get(_base_num, {})

        # 画像URL解決
        front_image_url = ''
        if card.get('front', {}).get('image_url'):
            front_image_url = card['front']['image_url']
        elif get_nested(ocr_data, ['front', 'image_url']):
            front_image_url = get_nested(ocr_data, ['front', 'image_url'])
        if not front_image_url and card_number:
            front_image_url = f"http://www.gundam-ab.com/images/cardlist/card/{card_number}.jpg?v8"
        if front_image_url and '_b' in front_image_url:
            front_image_url = front_image_url.replace('_b', '')

        back_image_url = ''
        if card.get('back', {}).get('image_url'):
            back_image_url = card['back']['image_url']
        elif get_nested(ocr_data, ['back', 'image_url']):
            back_image_url = get_nested(ocr_data, ['back', 'image_url'])
        has_back_image = bool(back_image_url)
        if not back_image_url and card_number:
            back_image_url = f"http://www.gundam-ab.com/images/cardlist/card/{card_number}_b.jpg?v8"

        # タイプとカテゴリを決定
        card_type = ocr_data.get('type') or card.get('category', 'MS')
        category = ocr_data.get('category') or card.get('category', '')

        # PLの戦闘スタイル補正
        if card_type == 'PL':
            pl_style = ocr_data.get('category') or get_nested(ocr_data, ['front', 'combat_style']) or ocr_data.get('type')
            if pl_style in ('殲滅', '制圧', '防衛'):
                category = pl_style

        cost_raw = ocr_data.get('cost')
        cost = safe_int(cost_raw) if cost_raw is not None else None

        # シリーズコード
        series = card.get('series', '')
        series_match = re.match(r'([A-Z]{2,3}\d{0,2})', card_number)
        if series_match:
            series = series_match.group(1)

        # PR カードは100枚ごとにシリーズ分割
        if card_number.startswith('PR-'):
            pr_num_match = re.search(r'PR-(\d+)', card_number)
            if pr_num_match:
                pr_num = int(pr_num_match.group(1))
                g = (pr_num - 1) // 100
                series = f'PR-{g*100+1:03d}~{(g+1)*100}'

        # ステータス抽出（logic.extract_stats でOCRキー揺れを吸収）
        normalized_stats = extract_stats(ocr_data)

        # レアリティ抽出（OCR raw テキスト末尾 → ocr_data.rarity フォールバック）
        rarity = None
        raw_text = ocr_data.get('raw')
        if raw_text and isinstance(raw_text, str):
            rarity_match = re.search(r'\b(SR|PR|LR|LE|CP|M|C|R|P|U)\s*$', raw_text.strip())
            if rarity_match:
                rarity = rarity_match.group(1)
        if not rarity and ocr_data.get('rarity'):
            rarity = ocr_data['rarity']

        # OCRデータの有無判定: CLIで生成された_basic.jsonが存在すればOCR済み
        # パラレルカード(_p1等)はベース番号にフォールバック済みなので、
        # ベース番号が_cli_trusted_numbersにあればOK
        _base_for_ocr = re.sub(r'_p\d+$', '', card_number)
        has_ocr = card_number in _cli_trusted_numbers or _base_for_ocr in _cli_trusted_numbers
        ocr_timestamp = ocr_timestamps.get(card_number, '') or ocr_timestamps.get(_base_for_ocr, '')

        # カードJSONにOCRフラグ・タイムスタンプを書き戻し
        if write_back_ocr_flags and has_ocr:
            if not card.get('ocr_completed') or card.get('ocr_timestamp') != ocr_timestamp:
                card['ocr_completed'] = True
                card['ocr_timestamp'] = ocr_timestamp
                if card.get('_file_path'):
                    try:
                        save_data = {k: v for k, v in card.items() if k != '_file_path'}
                        with open(card['_file_path'], 'w', encoding='utf-8') as f:
                            json.dump(save_data, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass

        # 地形適性
        tc = ocr_data.get('terrain_compatibility', {}) or {}
        terrain = {
            'ground': tc.get('ground') or '',
            'space': tc.get('space') or '',
            'desert': tc.get('desert') or '',
            'water': tc.get('water') or '',
        }

        # 検索用テキスト構築（カードテキスト全文検索用）
        search_parts = [card_number, card.get('name', '')]
        if ocr_data.get('model'):
            search_parts.append(ocr_data['model'])
        if ocr_data.get('pilot'):
            search_parts.append(ocr_data['pilot'])
        ms_ab = ocr_data.get('ms_ability')
        if isinstance(ms_ab, dict):
            search_parts.extend([ms_ab.get('name', ''), ms_ab.get('description', ''), ms_ab.get('type', '')])
        pl_sk = ocr_data.get('pilot_skill') or ocr_data.get('pl_skill')
        if isinstance(pl_sk, dict):
            search_parts.extend([pl_sk.get('name', ''), pl_sk.get('effect', ''), pl_sk.get('description', '')])
            sq_det = pl_sk.get('sq_skill_details')
            if isinstance(sq_det, dict):
                search_parts.extend([sq_det.get('sq_rush_effect', ''), sq_det.get('sq_max_effect', '')])
        wep = ocr_data.get('weapon', {}) or {}
        if isinstance(wep.get('main'), dict):
            search_parts.append(wep['main'].get('name', ''))
        if isinstance(wep.get('sub'), dict):
            search_parts.append(wep['sub'].get('name', ''))
        sp_atk = ocr_data.get('special_attack')
        if isinstance(sp_atk, dict):
            search_parts.extend([sp_atk.get('name', ''), sp_atk.get('description', '')])
        la_list = ocr_data.get('link_abilities') or ocr_data.get('link_ability') or []
        if isinstance(la_list, list):
            for la_item in la_list:
                if isinstance(la_item, dict):
                    search_parts.extend([la_item.get('name', ''), la_item.get('effect', '')])
        if raw_text:
            search_parts.append(raw_text)
        search_text = ' '.join(p for p in search_parts if p).lower()

        # 軽量インデックスエントリ
        index_entry = {
            'number': card_number,
            'name': card.get('name', ''),
            'type': card_type,
            'category': category,
            'cost': cost,
            'series': series,
            'rarity': rarity,
            'front_url': front_image_url,
            'back_url': back_image_url,
            'has_back_image': has_back_image,
            'mobility': normalized_stats['mobility'],
            'ranged': normalized_stats['ranged'],
            'melee': normalized_stats['melee'],
            'hp': normalized_stats['hp'],
            'has_ocr': has_ocr,
            'ocr_timestamp': ocr_timestamp,
            'terrain': terrain,
            'search_text': search_text,
            'pilot': ocr_data.get('pilot') or '',
            'model': ocr_data.get('model') or '',
            'illustrator': ocr_data.get('illustrator') or '',
            'sq_rush_effect': '',
            'sqsp_text': '',
            'sq_skill_text': '',
            'has_sqsp': False,
            'has_sq_skill': False,
            'has_sq_link': False,
            'sq_trigger': '',
            'sq_gauge_rate': '',
            'sq_skill_effect_tags': [],
            'skill_name': '',
            'skill_effect_tags': [],
            'eb_text': '',
            'eb_skill_text': '',
            'has_eb': False,
            'has_eb_skill': False,
            'has_eb_link': False,
            'has_ab_link': False,
            'eb_level': None,
            'eb_trigger_level': None,
            'eb_trigger_cond': '',
            'eb_type': '',
            'sp_effect_tags': [],
            'sqsp_effect_tags': [],
            'ebsp_effect_tags': [],
        }
        # SQSP効果テキスト (MS用)
        _sp_atk = ocr_data.get('special_attack')
        _is_sqsp = False
        _sqsp_parts = []
        if isinstance(_sp_atk, dict):
            if (_sp_atk.get('sp_type') == 'SQUAD SP'
                    or _sp_atk.get('squad_rush_condition')
                    or _sp_atk.get('united_sp')):
                _is_sqsp = True
                if _sp_atk.get('name'):
                    _sqsp_parts.append(_sp_atk['name'])
                if _sp_atk.get('description'):
                    _sqsp_parts.append(_sp_atk['description'])
                _sq_desc = _sp_atk.get('squad_description')
                if isinstance(_sq_desc, list):
                    _sqsp_parts.extend([d for d in _sq_desc if d])
                elif isinstance(_sq_desc, str) and _sq_desc:
                    _sqsp_parts.append(_sq_desc)
                _usp = _sp_atk.get('united_sp')
                if isinstance(_usp, dict):
                    if _usp.get('name'):
                        _sqsp_parts.append(_usp['name'])
                    if _usp.get('description'):
                        _sqsp_parts.append(_usp['description'])
        # rawテキストからのフォールバック検出
        if not _is_sqsp and 'SQUAD SP' in ocr_data.get('raw', ''):
            _is_sqsp = True
        if _is_sqsp:
            index_entry['sqsp_text'] = '\n'.join(_sqsp_parts)
            index_entry['has_sqsp'] = True
        # SP効果タグ分類 (Normal SP / SQSP)
        if isinstance(_sp_atk, dict):
            _sp_desc = (_sp_atk.get('description') or '') + ' ' + (_sp_atk.get('target') or '')
            index_entry['sp_effect_tags'] = classify_sp_effects(_sp_desc)
            if _is_sqsp:
                _sqsp_desc_parts = []
                _sq_d = _sp_atk.get('squad_description')
                if isinstance(_sq_d, list):
                    _sqsp_desc_parts.extend([d for d in _sq_d if d])
                elif isinstance(_sq_d, str) and _sq_d:
                    _sqsp_desc_parts.append(_sq_d)
                _usp2 = _sp_atk.get('united_sp')
                if isinstance(_usp2, dict) and _usp2.get('description'):
                    _sqsp_desc_parts.append(_usp2['description'])
                index_entry['sqsp_effect_tags'] = classify_sp_effects(' '.join(_sqsp_desc_parts))
        # PLスキル情報
        _pl_sk = ocr_data.get('pilot_skill') or ocr_data.get('pl_skill')
        if isinstance(_pl_sk, dict):
            index_entry['skill_name'] = _pl_sk.get('name') or ''
            # SQスキル情報
            if _pl_sk.get('has_sq_skill'):
                # SQ詳細が全てnull/emptyならEB誤判定として除外
                _sq_det = _pl_sk.get('sq_skill_details')
                _sq_is_real = False
                if isinstance(_sq_det, dict):
                    _sq_is_real = bool(
                        _sq_det.get('trigger')
                        or _sq_det.get('sq_rush_effect') or _sq_det.get('squad_rush_effect')
                        or _sq_det.get('sq_gauge_effect')
                        or _sq_det.get('sq_max_effect')
                    )
                if _sq_is_real:
                    # SQスキル全文テキスト（名前+効果）
                    _sq_text_parts = []
                    if _pl_sk.get('name'):
                        _sq_text_parts.append(_pl_sk['name'])
                    if _pl_sk.get('effect'):
                        _sq_text_parts.append(_pl_sk['effect'])
                    index_entry['sq_skill_text'] = '\n'.join(_sq_text_parts)
                    index_entry['has_sq_skill'] = True
                    # SQラッシュ効果テキスト & SQスキル効果タグ
                    index_entry['sq_rush_effect'] = _sq_det.get('sq_rush_effect') or _sq_det.get('squad_rush_effect') or ''
                    # SQゲージ増加率
                    _sq_ge = _sq_det.get('sq_gauge_effect') or ''
                    if '大アップ' in _sq_ge or '大UP' in _sq_ge:
                        index_entry['sq_gauge_rate'] = '大'
                    elif '中アップ' in _sq_ge or '中UP' in _sq_ge:
                        index_entry['sq_gauge_rate'] = '中'
                    elif '小アップ' in _sq_ge or '小UP' in _sq_ge:
                        index_entry['sq_gauge_rate'] = '小'
                    elif _sq_ge:
                        index_entry['sq_gauge_rate'] = _sq_ge
                    # SQ発動条件
                    _sq_trigger = _sq_det.get('trigger') or ''
                    if 'ロックオン' in _sq_trigger and ('戦艦' in _sq_trigger or '拠点' in _sq_trigger):
                        index_entry['sq_trigger'] = '戦艦/拠点ロックオン時'
                    elif 'ロックオン' in _sq_trigger:
                        index_entry['sq_trigger'] = 'ロックオン時'
                    elif '撃破' in _sq_trigger:
                        index_entry['sq_trigger'] = '撃破時'
                    elif 'SQゲージ' in _sq_trigger and '最大' in _sq_trigger:
                        index_entry['sq_trigger'] = 'SQゲージ最大時'
                    elif 'アビリティ' in _sq_trigger and '発動' in _sq_trigger:
                        index_entry['sq_trigger'] = 'MSアビリティ発動時'
                    elif '出撃' in _sq_trigger:
                        index_entry['sq_trigger'] = '出撃時'
                    elif _sq_trigger:
                        index_entry['sq_trigger'] = _sq_trigger
                    # SQスキル効果カテゴリ分類
                    _sq_eff_all = ' '.join(filter(None, [
                        _sq_det.get('sq_rush_effect') or _sq_det.get('squad_rush_effect') or '',
                        _sq_det.get('sq_max_effect') or '',
                        _sq_det.get('sq_gauge_effect') or '',
                        _sq_det.get('effect') or '',
                    ]))
                    _sq_tags = []
                    if '機動力' in _sq_eff_all and ('アップ' in _sq_eff_all or '上昇' in _sq_eff_all):
                        _sq_tags.append('機動力UP')
                    if '遠距離攻撃力' in _sq_eff_all and ('アップ' in _sq_eff_all or '上昇' in _sq_eff_all):
                        _sq_tags.append('遠距離攻撃力UP')
                    if '近距離攻撃力' in _sq_eff_all and ('アップ' in _sq_eff_all or '上昇' in _sq_eff_all):
                        _sq_tags.append('近距離攻撃力UP')
                    if 'SP威力' in _sq_eff_all and ('アップ' in _sq_eff_all or '上昇' in _sq_eff_all):
                        _sq_tags.append('SP威力UP')
                    if 'ダメージ' in _sq_eff_all and '軽減' in _sq_eff_all:
                        _sq_tags.append('ダメージ軽減')
                    if '弱体' in _sq_eff_all and ('無効' in _sq_eff_all or '受けない' in _sq_eff_all):
                        _sq_tags.append('弱体無効')
                    if '全味方' in _sq_eff_all:
                        _sq_tags.append('全味方バフ')
                    index_entry['sq_skill_effect_tags'] = _sq_tags
            # 効果カテゴリ分類
            eff = (_pl_sk.get('effect') or '') + ' ' + (_pl_sk.get('description') or '')
            tags = []
            if '機動力' in eff and ('アップ' in eff or 'UP' in eff):
                tags.append('機動力UP')
            if '遠距離攻撃力' in eff and ('アップ' in eff or 'UP' in eff):
                tags.append('遠距離攻撃力UP')
            if ('近距離攻撃力' in eff) and ('アップ' in eff or 'UP' in eff):
                tags.append('近距離攻撃力UP')
            if 'SP威力' in eff and ('アップ' in eff or 'UP' in eff):
                tags.append('SP威力UP')
            if 'ダメージ' in eff and '軽減' in eff:
                tags.append('ダメージ軽減')
            if 'ダウン' in eff and ('敵' in eff or 'ロックオン' in eff):
                tags.append('敵デバフ')
            if ('敵戦艦' in eff or '敵拠点' in eff or '戦艦／拠点' in eff) and ('ダメージ' in eff and 'アップ' in eff):
                tags.append('対戦艦/拠点')
            if 'SQゲージ' in eff and ('アップ' in eff or '増加' in eff or '最大' in eff):
                tags.append('SQゲージ増加')
            if '全味方' in eff:
                tags.append('全味方バフ')
            if 'HP' in eff and ('以下' in eff or '低い' in eff):
                tags.append('HP条件')
            if '弱体' in eff and '無効' in eff:
                tags.append('弱体無効')
            index_entry['skill_effect_tags'] = tags
        # ECHOES BEAT情報 (MS用)
        _eb = ocr_data.get('echoes_beat')
        if isinstance(_eb, dict) and _eb.get('has_eb'):
            index_entry['has_eb'] = True
            index_entry['eb_type'] = _eb.get('eb_type', 'normal')
            index_entry['eb_level'] = _eb.get('eb_level')
            _eb_parts = []
            eb_type = _eb.get('eb_type', 'normal')
            lvl = _eb.get('eb_level')
            if eb_type == 'sp':
                _eb_parts.append('ECHOES BEAT SP')
            if lvl:
                _eb_parts.append(f"Lv.{lvl}")
            if _eb.get('eb_sp_name'):
                _eb_parts.append(_eb['eb_sp_name'])
            if _eb.get('eb_power'):
                _eb_parts.append(f"威力:{_eb['eb_power']}")
            if _eb.get('eb_description'):
                _eb_parts.append(_eb['eb_description'])
            index_entry['eb_text'] = '\n'.join(_eb_parts) if _eb_parts else 'ECHOES BEAT'
            # EBSP効果タグ
            if _eb.get('eb_type') == 'sp' and _eb.get('eb_description'):
                index_entry['ebsp_effect_tags'] = classify_sp_effects(_eb['eb_description'])
        # EB PLスキル情報
        if isinstance(_pl_sk, dict) and _pl_sk.get('is_eb_skill'):
            index_entry['has_eb_skill'] = True
            index_entry['eb_trigger_level'] = _pl_sk.get('eb_trigger_level')
            # EBトリガー条件分類
            _eb_trig_text = _pl_sk.get('trigger', '') or _pl_sk.get('effect', '') or ''
            if '上昇するたびに' in _eb_trig_text or 'が上昇時' in _eb_trig_text:
                index_entry['eb_trigger_cond'] = '上昇毎'
            elif '以上' in _eb_trig_text:
                index_entry['eb_trigger_cond'] = '以上'
            elif 'に上昇時' in _eb_trig_text or 'に上昇した時' in _eb_trig_text:
                index_entry['eb_trigger_cond'] = '上昇時'
            elif 'EBLv' in _eb_trig_text:
                index_entry['eb_trigger_cond'] = 'Lv到達時'
            _eb_sk_parts = []
            if _pl_sk.get('name'):
                _eb_sk_parts.append(_pl_sk['name'])
            if _pl_sk.get('effect'):
                _eb_sk_parts.append(_pl_sk['effect'])
            index_entry['eb_skill_text'] = '\n'.join(_eb_sk_parts)
        # EB リンクアビリティ
        _la_all = ocr_data.get('link_abilities') or ocr_data.get('link_ability') or []
        if isinstance(_la_all, list):
            for _la_item in _la_all:
                if isinstance(_la_item, dict) and _la_item.get('is_eb_link'):
                    index_entry['has_eb_link'] = True
                    break
        # AB リンクアビリティ
        if isinstance(_la_all, list):
            for _la_item in _la_all:
                if isinstance(_la_item, dict) and _la_item.get('is_ab_link'):
                    index_entry['has_ab_link'] = True
                    break
        # SQ リンクアビリティ（効果にSQ関連キーワードを含むリンクアビリティ）
        if isinstance(_la_all, list):
            for _la_item in _la_all:
                if not isinstance(_la_item, dict):
                    continue
                _la_eff = (_la_item.get('effect') or '') + ' ' + (_la_item.get('condition') or '')
                if 'SQゲージ' in _la_eff or 'SQUAD RUSH' in _la_eff or 'SQ RUSH' in _la_eff or 'SQUAD SP' in _la_eff:
                    index_entry['has_sq_link'] = True
                    break
        index_list.append(index_entry)

        # 詳細キャッシュ
        detail_map[card_number] = {
            'number': card_number,
            'name': card.get('name', ''),
            'url': front_image_url,
            'category': category,
            'series': series,
            'front': {'image_url': front_image_url},
            'back': {'image_url': back_image_url},
            'ocr_data': ocr_data,
        }

    index_list.sort(key=lambda x: x['number'])

    # リンクアビリティ索引を構築（logic.get_link_abilities / parse_link_condition を使用）
    link_map = {}
    for card_number, detail in detail_map.items():
        ocr = detail.get('ocr_data', {})
        card_type = ocr.get('type') or detail.get('category', 'MS')
        links = get_link_abilities(ocr)
        for link in links:
            if not isinstance(link, dict):
                continue
            name = link.get('name', '').strip()
            if not name:
                continue
            if name not in link_map:
                condition = link.get('condition', '')
                effect = link.get('effect', '')
                cond = parse_link_condition(condition)
                required = cond['required'] if cond else 2
                link_map[name] = {
                    'condition': condition,
                    'effect': effect,
                    'required': required,
                    'ms_cards': [],
                    'pl_cards': [],
                }
            entry = link_map[name]
            if card_type == 'PL':
                if card_number not in entry['pl_cards']:
                    entry['pl_cards'].append(card_number)
            else:
                if card_number not in entry['ms_cards']:
                    entry['ms_cards'].append(card_number)

    return (index_list, detail_map, link_map)
