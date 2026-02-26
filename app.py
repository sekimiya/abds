from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, Response
import os
import re
import json
import secrets
import threading
import hashlib
import time
import uuid
import logging
import functools

from dotenv import load_dotenv
load_dotenv()

from fetch_series_ids import fetch_all_series_ids
from fetch_cards import fetch_cards_for_series, save_card_data

from logic import (
    safe_int,
    get_nested,
    extract_stats,
    get_link_abilities,
    parse_link_condition,
)

from card_ocr_cc import (
    load_unique_cards as ocr_load_unique_cards,
    process_card as ocr_process_card,
    get_existing_raw_numbers,
    get_existing_ocr_numbers,
)
import card_ocr_cc
import db

# 後方互換: 旧名でもアクセス可能にする
_safe_int = safe_int

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# --- セキュリティ設定 ---
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# 管理者トークン（.envのADMIN_TOKENから読み取り、未設定なら自動生成）
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', '').strip()
if not ADMIN_TOKEN:
    ADMIN_TOKEN = secrets.token_hex(24)
    print(f"[SECURITY] ADMIN_TOKEN が未設定のため自動生成しました: {ADMIN_TOKEN}")
    print(f"[SECURITY] 永続化するには .env に ADMIN_TOKEN={ADMIN_TOKEN} を追加してください")


def require_admin(f):
    """管理エンドポイント用の認証デコレータ。
    Authorization: Bearer <token> ヘッダまたは ?token=<token> クエリで認証する。
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
        if not token:
            token = request.args.get('token', '').strip()
        if not token or not secrets.compare_digest(token, ADMIN_TOKEN):
            return jsonify({'success': False, 'error': '認証が必要です'}), 401
        return f(*args, **kwargs)
    return decorated


# --- セキュリティヘッダ ---
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


# --- レートリミット ---
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per minute"],
        storage_uri="memory://",
    )
except ImportError:
    limiter = None
    print("[WARNING] flask-limiter が未インストールです。レートリミットは無効です。")
    print("[WARNING] pip install flask-limiter でインストールしてください。")




# --- サーバーサイドカードインデックスキャッシュ ---
_card_index_cache = None
_card_detail_cache = {}
_link_index_cache = None
_tactics_cards_cache = None
_card_cache_lock = threading.Lock()

# --- バックグラウンド収集タスクの状態管理 ---
_collect_status = {
    "running": False,
    "current_series": "",
    "series_index": 0,
    "total_series": 0,
    "collected_cards": 0,
    "errors": [],
    "log": [],
    "started_at": None,
    "finished_at": None,
}
_collect_lock = threading.Lock()

# --- OCR実行タスクの状態管理 ---
_ocr_run_status = {
    "running": False,
    "stop_requested": False,
    "series": "",
    "stage": "both",
    "current_card": "",
    "current_card_name": "",
    "processed_count": 0,
    "success_count": 0,
    "failed_count": 0,
    "total_target": 0,
    "log": [],
    "errors": [],
    "started_at": None,
    "finished_at": None,
    "elapsed_seconds": 0,
    "eta_seconds": 0,
}
_ocr_run_lock = threading.Lock()


class OcrRunLogHandler(logging.Handler):
    """card_ocr_cc.logger のログを _ocr_run_status["log"] に転送するハンドラ"""
    def emit(self, record):
        msg = self.format(record)
        with _ocr_run_lock:
            _ocr_run_status["log"].append(msg)
            if len(_ocr_run_status["log"]) > 200:
                _ocr_run_status["log"] = _ocr_run_status["log"][-200:]


def _classify_sp_effects(text):
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


def _build_card_index():
    """全カードデータとOCRデータを統合し、軽量インデックスと詳細キャッシュを構築する"""
    global _card_index_cache, _card_detail_cache

    all_cards = []
    all_cards_dir = 'all_cards_list'
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
    ocr_dir = 'ocr_results_debug'
    if os.path.exists(ocr_dir):
        for filename in sorted(os.listdir(ocr_dir)):
            if not filename.endswith('.json'):
                continue
            try:
                base = filename.replace('.json', '')
                number_match = re.search(r'([A-Z0-9\-]{4,}-\d{2,4})', base)
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
                    if not (loaded.get('ocr_engine') or '').startswith('claude_code_cli'):
                        # 非CLIデータはスキップ（信頼性に問題あり）
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
                    # OCRがMS ABILITYセクション内に配置したが、内容がリンクアビリティ形式
                    # （「デッキに○枚以上」条件 + バフ効果、activation なし）のものを修正
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
                # パターン1: special_attack.echoes_beat / echoes_beat_sp がdict
                # パターン2: special_attack に eb_level, eb_power, eb_description がフラット
                # パターン3: special_attack に power_enhanced がフラット（EB SP威力）
                # パターン4: echoes_beat が True / "ECHOES BEAT"（最小限）

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

                    # パターン2: フラットフィールド（eb_level/echoes_beat_lv, eb_power/power_eb, eb_description）
                    elif sa_data.get('eb_level') or sa_data.get('echoes_beat_lv') or sa_data.get('eb_power') or sa_data.get('power_eb') or sa_data.get('eb_description'):
                        # name から EB SP名を分離
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
                        # description から EB 部分を分離（「／」区切り）
                        eb_desc = ''
                        full_desc = sa_data.get('description', '') or ''
                        if '／' in full_desc:
                            eb_desc = full_desc.split('／', 1)[1].strip()
                        elif 'EBLv' in full_desc:
                            eb_desc = full_desc
                        # name から EB SP名を分離（「SP名 EB名 Lv.X」形式）
                        eb_sp_name = ''
                        full_name = sa_data.get('name', '') or ''
                        lv_match = re.search(r'Lv\.(\d+)', full_name)
                        eb_lv = int(lv_match.group(1)) if lv_match else 3
                        # name が複数部分なら後半がEB名
                        name_parts = full_name.split(' ')
                        if len(name_parts) >= 2:
                            # 最後の Lv.X を除く後半部分がEB名
                            eb_name_parts = []
                            found_second = False
                            for i, p in enumerate(name_parts):
                                if re.match(r'Lv\.\d+', p):
                                    continue
                                if found_second:
                                    eb_name_parts.append(p)
                                else:
                                    # 最初の単語以降、大文字やカタカナで始まる新しい名前を検出
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
    # sp.json / sq_analysis.json のみ存在するケースも信頼性がないため除外
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
        series_match = re.match(r'([A-Z]{2,3}\d{2})', card_number)
        if series_match:
            series = series_match.group(1)

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

        # OCRデータの有無判定
        has_ocr = bool(ocr_data and (ocr_data.get('ms_ability') or ocr_data.get('weapon') or
                        ocr_data.get('special_attack') or ocr_data.get('pilot_skill') or
                        ocr_data.get('pl_skill') or ocr_data.get('model') or
                        ocr_data.get('terrain_compatibility')))
        ocr_timestamp = ocr_timestamps.get(card_number, '')

        # カードJSONにOCRフラグ・タイムスタンプを永続化
        card_ocr_changed = False
        if has_ocr:
            if not card.get('ocr_completed') or card.get('ocr_timestamp') != ocr_timestamp:
                card['ocr_completed'] = True
                card['ocr_timestamp'] = ocr_timestamp
                card_ocr_changed = True
        else:
            # カードJSON側にocr_completedがあるが実データがない場合
            # CLI信頼データが存在するカードのみカード側の値を尊重
            if card.get('ocr_completed') and card_number in _cli_trusted_numbers:
                has_ocr = True
                ocr_timestamp = card.get('ocr_timestamp', '')
        if card_ocr_changed and card.get('_file_path'):
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
            index_entry['sp_effect_tags'] = _classify_sp_effects(_sp_desc)
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
                index_entry['sqsp_effect_tags'] = _classify_sp_effects(' '.join(_sqsp_desc_parts))
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
                index_entry['ebsp_effect_tags'] = _classify_sp_effects(_eb['eb_description'])
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
    _card_index_cache = index_list
    _card_detail_cache = detail_map

    # リンクアビリティ索引を構築（logic.get_link_abilities / parse_link_condition を使用）
    global _link_index_cache
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
    _link_index_cache = link_map

    return index_list


def get_card_index():
    """キャッシュされたカードインデックスを返す（初回は構築）"""
    global _card_index_cache
    if _card_index_cache is None:
        with _card_cache_lock:
            if _card_index_cache is None:
                _build_card_index()
    return _card_index_cache


def get_card_detail(number):
    """カード番号から詳細データを返す"""
    global _card_detail_cache
    if not _card_detail_cache:
        get_card_index()  # インデックス構築で詳細もキャッシュされる
    return _card_detail_cache.get(number)


@app.route('/debug_summary')
def debug_summary():
    """ocr_results_debug の同一プレフィックス（ファイル名_*.json）を統合し、
    一枚の統合JSONとして返す。以降の数値はこの統合JSONから読み取る。"""
    base_dir = 'ocr_results_debug'
    results = {}
    if not os.path.exists(base_dir):
        return jsonify({'success': True, 'cards': []})

    file_list = [f for f in os.listdir(base_dir) if f.endswith('.json')]
    number_pattern = re.compile(r'([A-Z]{2}\d{2}-\d{3,4})')

    # 1) グルーピング: 「ファイル名_*.json」でプレフィックスごとにまとめる
    groups = {}
    for fn in file_list:
        base_no_ext = fn[:-5]
        if '_' not in base_no_ext:
            continue
        prefix = base_no_ext.rsplit('_', 1)[0]
        groups.setdefault(prefix, []).append(fn)

    # 2) 各プレフィックスグループを統合
    for prefix, files in groups.items():
        # カード番号をファイル名から推測
        m = number_pattern.search(prefix)
        number = m.group(1) if m else None
        entry = {
            'number': number,
            'name': None,
            'type': None,
            'category': None,
            'cost': None,
            'stats': {},
            'weapon': {},
            'ms_ability': None,
            'pl_skill': None,
            'link_abilities': [],
            'special_attack': None,
            'front': {},
            'back': {},
            'card_label': {},
            'source_files': []
        }

        for fn in files:
            path = os.path.join(base_dir, fn)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                continue
            entry['source_files'].append(fn)

            # front/back 画像
            if isinstance(data, dict):
                if 'front_image_url' in data:
                    entry.setdefault('front', {})['image_url'] = data['front_image_url']
                if 'back_image_url' in data:
                    entry.setdefault('back', {})['image_url'] = data['back_image_url']

            # basic 形式: ocr_data を持つ
            ocr = data.get('ocr_data') if isinstance(data, dict) else None
            if isinstance(ocr, dict):
                entry['name'] = entry['name'] or ocr.get('name')
                entry['type'] = entry['type'] or ocr.get('type') or ocr.get('category')
                entry['category'] = entry['category'] or ocr.get('category')
                entry['cost'] = entry['cost'] or ocr.get('cost')
                # stats/weapon
                entry['stats'] = {**entry['stats'], **(ocr.get('stats') or {})}
                if 'weapon' in ocr and isinstance(ocr['weapon'], dict):
                    entry['weapon'] = {**entry['weapon'], **ocr['weapon']}
                if 'ms_ability' in ocr:
                    entry['ms_ability'] = ocr.get('ms_ability')
                if 'pl_skill' in ocr or 'pilot_skill' in ocr:
                    entry['pl_skill'] = ocr.get('pl_skill') or ocr.get('pilot_skill')
                # card_label (Class など)
                if isinstance(ocr.get('card_label'), dict):
                    entry['card_label'] = {**entry.get('card_label', {}), **ocr.get('card_label')}
                # links
                la = ocr.get('link_abilities') or ocr.get('link_ability')
                if isinstance(la, list):
                    # 既存にマージ（重複名排除）
                    known = {l.get('name') for l in entry['link_abilities'] if isinstance(l, dict)}
                    for l in la:
                        if isinstance(l, dict) and l.get('name') not in known:
                            entry['link_abilities'].append(l)
                if 'special_attack' in ocr and not entry['special_attack']:
                    entry['special_attack'] = ocr.get('special_attack')

            # sq_analysis 形式
            if data.get('sq_analysis_type') or data.get('pilot_skill'):
                ps = data.get('pilot_skill')
                if ps and not entry['pl_skill']:
                    entry['pl_skill'] = ps
                la2 = data.get('link_ability')
                if isinstance(la2, list):
                    known = {l.get('name') for l in entry['link_abilities'] if isinstance(l, dict)}
                    for l in la2:
                        if isinstance(l, dict) and l.get('name') not in known:
                            entry['link_abilities'].append(l)
                full = data.get('full_ocr_data')
                if isinstance(full, dict):
                    entry['name'] = entry['name'] or full.get('name')
                    entry['type'] = entry['type'] or full.get('type')
                    entry['category'] = entry['category'] or full.get('category')
                    entry['cost'] = entry['cost'] or full.get('cost')
                    entry['stats'] = {**entry['stats'], **(full.get('stats') or {})}
                    if isinstance(full.get('card_label'), dict):
                        entry['card_label'] = {**entry.get('card_label', {}), **full.get('card_label')}

        # --- PLのカテゴリー補正 ---
        # デバッグOCRでは category に「パイロット」等が入るケースがあるため、
        # PL の場合は card_label.class（殲滅/制圧/防衛）を優先して category に反映する
        try:
            if entry.get('type') == 'PL':
                cls = None
                # ocr は最後に処理した data の ocr_data を参照しうるため安全に取得
                merged_ocr = None
                for fn in files:
                    try:
                        with open(os.path.join(base_dir, fn), 'r', encoding='utf-8') as f:
                            dtmp = json.load(f)
                            if isinstance(dtmp, dict) and isinstance(dtmp.get('ocr_data'), dict):
                                merged_ocr = dtmp['ocr_data']
                                break
                    except Exception:
                        continue
                if isinstance(merged_ocr, dict) and isinstance(merged_ocr.get('card_label'), dict):
                    cls = merged_ocr['card_label'].get('class')
                if not cls and isinstance(entry.get('card_label'), dict):
                    cls = entry['card_label'].get('Class') or entry['card_label'].get('class')
                # 一部データでは category に "PL" などが入るため上書きする
                if cls in {'殲滅', '制圧', '防衛'}:
                    entry['category'] = cls
                    entry.setdefault('front', {})['combat_style'] = cls
                else:
                    # 予備: raw テキストから殲滅/制圧/防衛を抽出
                    raw_text = None
                    if isinstance(merged_ocr, dict):
                        raw_text = merged_ocr.get('raw')
                    if raw_text and isinstance(raw_text, str):
                        for kw in ['殲滅','制圧','防衛']:
                            if kw in raw_text:
                                entry['category'] = kw
                                entry.setdefault('front', {})['combat_style'] = kw
                                break
        except Exception:
            pass

            # sp 情報（存在すれば）
            for key in ['special_attack', 'sp', 'sp_info']:
                if key in data and not entry['special_attack']:
                    entry['special_attack'] = data.get(key)

            # sp.json 形式（sp_info / power / descriptions）がある場合は保持し、可能なら表示用に統合
            if any(k in data for k in ['sp_info', 'power', 'descriptions']):
                try:
                    if 'sp_info' in data and isinstance(data['sp_info'], dict):
                        entry['sp_info'] = data['sp_info']
                    if 'power' in data and isinstance(data['power'], dict):
                        entry['power'] = data['power']
                    if 'descriptions' in data and isinstance(data['descriptions'], dict):
                        entry['descriptions'] = data['descriptions']

                    # 既存 special_attack に対しても不足項目を補完（上書きではなくマージ）
                    name = get_nested(entry, ['sp_info', 'name'])
                    norm = get_nested(entry, ['power', 'normal'])
                    squad_val = get_nested(entry, ['power', 'squad'])
                    if isinstance(squad_val, list):
                        squad = squad_val[0] if squad_val else None
                    else:
                        squad = squad_val
                    desc = get_nested(entry, ['descriptions', 'normal_description']) or get_nested(entry, ['descriptions', 'all_description'])

                    sa = entry.get('special_attack') or {}
                    if not isinstance(sa, dict):
                        sa = {}
                    if name and not sa.get('name'):
                        sa['name'] = name
                    if 'power' not in sa or not isinstance(sa['power'], dict):
                        sa['power'] = {}
                    if norm and not sa['power'].get('normal'):
                        sa['power']['normal'] = norm
                    if squad and not sa['power'].get('squad'):
                        sa['power']['squad'] = squad
                    if desc and not sa.get('description'):
                        sa['description'] = desc
                    entry['special_attack'] = sa
                except Exception:
                    pass

        # プレフィックスごとの統合結果を保存
        results[prefix] = entry

        # name は各ファイルの ocr_data や full_ocr_data から既に補完済み。外側で未設定なら空のまま返す

    # フォールバック画像URL生成（front/backが無い場合）
    for _, entry in results.items():
        if not entry.get('front') or not entry['front'].get('image_url'):
            if entry.get('number'):
                entry.setdefault('front', {})['image_url'] = f"http://www.gundam-ab.com/images/cardlist/card/{entry['number']}.jpg?v8"
        if not entry.get('back') or not entry['back'].get('image_url'):
            if entry.get('number'):
                entry.setdefault('back', {})['image_url'] = f"http://www.gundam-ab.com/images/cardlist/card/{entry['number']}_b.jpg?v8"

    # ソートし配列化
    cards = list(results.values())
    cards.sort(key=lambda x: (x.get('number') or '', x.get('name') or ''))
    return jsonify({'success': True, 'cards': cards})

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/readme')
def readme():
    return render_template('readme.html')

@app.route('/sim')
def index():
    return render_template('index.html')

_PLACEHOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="250" height="350" viewBox="0 0 250 350">'
    '<rect width="250" height="350" fill="#e0e0e0" rx="8"/>'
    '<text x="125" y="175" text-anchor="middle" fill="#999" font-size="14" '
    'font-family="sans-serif">No Image</text></svg>'
)

def _is_safe_filename(filename):
    """パストラバーサル攻撃を防ぐためのファイル名検証"""
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
        return False
    # 正規化して元のパスと一致するか確認
    normalized = os.path.normpath(filename)
    if normalized.startswith('..') or os.path.isabs(normalized):
        return False
    return True


@app.route('/api/image_proxy')
def api_image_proxy():
    url = request.args.get('url', '')
    # 許可するドメインを制限（公式サイトのみ）
    if not url.startswith('http://www.gundam-ab.com/') and not url.startswith('https://www.gundam-ab.com/'):
        return Response('Forbidden', status=403)
    try:
        import requests as req
        resp = req.get(url, timeout=10)
        resp.raise_for_status()
        return Response(resp.content, content_type=resp.headers.get('Content-Type', 'image/jpeg'))
    except Exception:
        return Response(_PLACEHOLDER_SVG, content_type='image/svg+xml'), 502


@app.route('/card_images/<path:filename>')
def serve_card_image(filename):
    if not _is_safe_filename(filename):
        return Response(_PLACEHOLDER_SVG, content_type='image/svg+xml'), 400
    filepath = os.path.join('card_images', filename)
    if os.path.isfile(filepath):
        return send_from_directory('card_images', filename)
    return Response(_PLACEHOLDER_SVG, content_type='image/svg+xml')


@app.route('/v2')
def index_v2():
    # モバイルUA検出 → /m へリダイレクト（?noredirect=1 で回避可能）
    if request.args.get('noredirect') != '1':
        ua = (request.headers.get('User-Agent') or '').lower()
        if any(k in ua for k in ('iphone', 'android', 'mobile', 'ipod')):
            return redirect('/m' + ('#' + request.args.get('hash', '') if request.args.get('hash') else ''))
    return render_template('index_v2.html')

@app.route('/m')
def mobile_v2():
    return render_template('mobile_v2_portrait.html')

@app.route('/mobile/portrait')
def mobile_portrait():
    return render_template('mobile_v2_portrait.html')

@app.route('/index2.html')
def index2():
    return render_template('index2.html')


@app.route('/fetch_cards')
def fetch_cards():
    # デバッグモード判定（ocr_results_debug を使用）
    debug_flag = request.args.get('debug', '').lower() in ['1', 'true', 'yes', 'on']

    # カードデータを読み込む
    all_cards = []
    all_cards_dir = 'all_cards_list'
    if os.path.exists(all_cards_dir):
        card_files = [f for f in os.listdir(all_cards_dir) if f.endswith('.json')]
        print(f"カードファイル数: {len(card_files)}")
        for filename in card_files:
            try:
                with open(os.path.join(all_cards_dir, filename), 'r', encoding='utf-8') as f:
                    card_data = json.load(f)
                    all_cards.append(card_data)
            except Exception as e:
                print(f"カードファイル読み込みエラー {filename}: {str(e)}")
    else:
        print(f"ディレクトリが存在しません: {all_cards_dir}")
    
    print(f"読み込まれたカード数: {len(all_cards)}")
    
    # OCR結果を読み込む（通常 or デバッグ）
    ocr_results = {}
    ocr_dir = 'ocr_results_debug' if debug_flag else 'ocr_results'
    debug_sources = {}
    if os.path.exists(ocr_dir):
        ocr_files = [f for f in os.listdir(ocr_dir) if f.endswith('.json')]
        print(f"OCRファイル数: {len(ocr_files)}")
        for filename in ocr_files:
            try:
                with open(os.path.join(ocr_dir, filename), 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    base = filename.replace('.json', '')

                    # カード番号を抽出（ファイル名に含まれる想定: FQ01-001 など）
                    number_match = re.search(r'([A-Z0-9\-]{4,}-\d{2,4})', base)
                    if not number_match:
                        continue
                    number = number_match.group(1)

                    # データの正規化
                    if debug_flag:
                        # debug形式: { card_number, front_image_url, back_image_url, ocr_data: {...} }
                        normalized = loaded.get('ocr_data', {}) if isinstance(loaded, dict) else {}
                        # 画像URLを front/back にブリッジ（UI互換）
                        front_url = loaded.get('front_image_url')
                        back_url = loaded.get('back_image_url')
                        if front_url:
                            normalized.setdefault('front', {})['image_url'] = front_url
                        if back_url:
                            normalized.setdefault('back', {})['image_url'] = back_url
                        # リンク配列のキー統一
                        if 'link_ability' in normalized and 'link_abilities' not in normalized:
                            normalized['link_abilities'] = normalized.get('link_ability')
                        # 複数種類がある場合は basic を優先
                        prev = ocr_results.get(number)
                        if prev is None or filename.endswith('_basic.json'):
                            ocr_results[number] = normalized
                        # ソースファイルの追跡
                        debug_sources.setdefault(number, []).append(filename)
                    else:
                        # 従来形式はそのまま格納
                        ocr_results[number] = loaded
                        # 通常側は追跡しない
            except Exception as e:
                print(f"OCRファイル読み込みエラー {filename}: {str(e)}")
    else:
        print(f"OCRディレクトリが存在しません: {ocr_dir}")
    
    print(f"OCR結果数: {len(ocr_results)}")
    
    # カードデータとOCRデータを突合
    result_cards = []
    for card in all_cards:
        # カードデータがリストの場合は最初の要素を取得
        if isinstance(card, list) and len(card) > 0:
            card = card[0]
        elif not isinstance(card, dict):
            continue
            
        card_number = card.get('number', '') if card else ''
        ocr_data = ocr_results.get(card_number, {})
        # イラスト違い (_p1, _p2 等) はベース番号のOCRデータをフォールバック参照
        if not ocr_data:
            _base_num2 = re.sub(r'_p\d+$', '', card_number)
            if _base_num2 != card_number:
                ocr_data = ocr_results.get(_base_num2, {})

        # 表面画像URL生成
        front_image_url = ''
        # 1. カードデータのfront.image_urlを優先
        if card and 'front' in card and card['front'] and 'image_url' in card['front']:
            front_image_url = card['front']['image_url']
        # 2. OCRデータのfront.image_url
        elif ocr_data and 'front' in ocr_data and ocr_data['front'] and 'image_url' in ocr_data['front']:
            front_image_url = ocr_data['front']['image_url']
        # 3. OCRデータのimage_url（表面用）
        elif ocr_data and 'image_url' in ocr_data:
            front_image_url = ocr_data['image_url']
        # 3.5 デバッグ由来のfront.image_url
        elif ocr_data and isinstance(ocr_data, dict) and 'front' in ocr_data and isinstance(ocr_data['front'], dict) and 'image_url' in ocr_data['front']:
            front_image_url = ocr_data['front']['image_url']
        # 4. カード番号から画像URLを生成
        if not front_image_url and card_number:
            front_image_url = f"http://www.gundam-ab.com/images/cardlist/card/{card_number}.jpg?v8"
        # 5. 裏面画像URLから表面画像URLを生成（_bを除去）
        if front_image_url and '_b' in front_image_url:
            front_image_url = front_image_url.replace('_b', '')

        # 裏面画像URL生成
        back_image_url = ''
        # 1. カードデータのback.image_urlを優先
        if card and 'back' in card and card['back'] and 'image_url' in card['back']:
            back_image_url = card['back']['image_url']
        # 2. OCRデータのback.image_url
        elif ocr_data and 'back' in ocr_data and ocr_data['back'] and 'image_url' in ocr_data['back']:
            back_image_url = ocr_data['back']['image_url']
        # 3. OCRデータのback_image_url
        elif ocr_data and 'back_image_url' in ocr_data:
            back_image_url = ocr_data['back_image_url']
        # 3.5 デバッグ由来のtop-level → すでに front/back に移植済みだが保険
        elif debug_flag and isinstance(ocr_data, dict):
            back_image_url = get_nested(ocr_data, ['back', 'image_url']) if 'back' in ocr_data else None
        # 4. カード番号から裏面画像URLを生成
        if not back_image_url and card_number:
            back_image_url = f"http://www.gundam-ab.com/images/cardlist/card/{card_number}_b.jpg?v8"
        
        # frontとbackオブジェクトを構築
        front_obj = {}
        if front_image_url:
            front_obj['image_url'] = front_image_url
        
        back_obj = {}
        if back_image_url:
            back_obj['image_url'] = back_image_url
        
        card_info = {
            'url': front_image_url,  # デフォルトURL（表面）
            'number': card_number,
            'name': card.get('name', '') if card else '',
            'category': card.get('category', 'MS') if card else 'MS',
            'ocr_data': ocr_data,
            'front': front_obj,
            'back': back_obj,
            'series': card.get('series', '') if card else '',
            'debug_sources': debug_sources.get(card_number, []) if debug_flag else []
        }

        # PLの戦闘スタイル（殲滅/制圧/防衛）を category に反映し、front.combat_style にもブリッジ
        try:
            pl_style = None
            if isinstance(ocr_data, dict):
                pl_style = ocr_data.get('category') \
                    or get_nested(ocr_data, ['front', 'combat_style']) \
                    or ocr_data.get('type')
            if pl_style and isinstance(pl_style, str) and pl_style.strip():
                card_info['category'] = pl_style
                card_info.setdefault('front', {})['combat_style'] = pl_style
        except Exception:
            pass
        
        # カード番号からシリーズコードを生成（SQリンク用）
        if card_number:
            series_match = re.match(r'([A-Z]{2,3}\d{2})', card_number)
            if series_match:
                card_info['series'] = series_match.group(1)
        
        result_cards.append(card_info)
    
    print(f"結果カード数: {len(result_cards)}")
    result_cards.sort(key=lambda x: x['number'])
    return jsonify({'success': True, 'images': result_cards})

@app.route('/ocr_results/<path:filename>')
def serve_ocr_results(filename):
    if not _is_safe_filename(filename):
        return jsonify({'error': 'Invalid filename'}), 400
    return send_from_directory('ocr_results', filename)

# --- デッキ投稿API ---
@app.route('/post_deck', methods=['POST'])
def post_deck():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data received'}), 400
    deck_name = data.get('deck_name', '').strip()
    comment = data.get('comment', '').strip()
    cards = data.get('cards', [])
    if not deck_name or not cards:
        return jsonify({'success': False, 'error': 'デッキ名とカード構成は必須です'}), 400
    deck_data = {
        'deck_name': deck_name,
        'comment': comment,
        'cards': cards,
        'tactics_main': data.get('tactics_main'),
        'tactics_sub': data.get('tactics_sub'),
        'timestamp': data.get('timestamp'),
    }
    entry, err = db.create_deck(deck_data)
    if err:
        return jsonify({'success': False, 'error': err}), 500
    return jsonify({'success': True, 'message': 'デッキを投稿しました'})

# --- デッキ一覧API ---
@app.route('/decks', methods=['GET'])
def get_decks():
    decks = db.list_decks()
    return jsonify({'success': True, 'decks': decks})

@app.route('/decks.html')
def decks_html():
    return render_template('decks.html')

@app.route('/search')
def search():
    return render_template('search.html')

@app.route('/mobile')
def mobile():
    return render_template('mobile.html')


@app.route('/series_list')
def series_list():
    try:
        with open('series_data/series_list.json', 'r', encoding='utf-8') as f:
            series_data = json.load(f)
        return jsonify(series_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ====================================================
# 新規API: カードインデックス・詳細・検索・デッキCRUD
# ====================================================

@app.route('/api/card_index')
def api_card_index():
    """軽量カードインデックスを返す（番号,名前,コスト,タイプ,カテゴリ,シリーズ,画像URL,基本ステータス）"""
    idx = get_card_index()
    return jsonify({'success': True, 'cards': idx})


@app.route('/api/link_index')
def api_link_index():
    """リンクアビリティ索引を返す（リンク名→条件,効果,必要枚数,MS/PLカード番号リスト）"""
    global _link_index_cache
    if _link_index_cache is None:
        get_card_index()
    return jsonify({'success': True, 'links': _link_index_cache or {}})


@app.route('/api/tactics_cards')
def api_tactics_cards():
    """作戦カードマスタデータを返す"""
    global _tactics_cards_cache
    if _tactics_cards_cache is None:
        tactics_file = os.path.join(os.path.dirname(__file__), 'tactics_cards.json')
        try:
            with open(tactics_file, 'r', encoding='utf-8') as f:
                _tactics_cards_cache = json.load(f)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'data': _tactics_cards_cache})


@app.route('/api/card/<number>')
def api_card_detail(number):
    """単一カードの詳細OCRデータを返す"""
    detail = get_card_detail(number)
    if detail is None:
        return jsonify({'success': False, 'error': 'Card not found'}), 404
    return jsonify({'success': True, 'card': detail})


@app.route('/api/cards/batch', methods=['POST'])
def api_cards_batch():
    """複数カード番号から詳細データを一括取得"""
    data = request.get_json()
    if not data or 'numbers' not in data:
        return jsonify({'success': False, 'error': 'numbers required'}), 400
    numbers = data['numbers']
    if not isinstance(numbers, list):
        return jsonify({'success': False, 'error': 'numbers must be array'}), 400
    result = {}
    for num in numbers:
        detail = get_card_detail(num)
        if detail:
            result[num] = detail
    return jsonify({'success': True, 'cards': result})


@app.route('/api/cards/search')
def api_cards_search():
    """サーバーサイドフィルタリング検索"""
    idx = get_card_index()
    q = request.args.get('q', '').strip().lower()
    card_type = request.args.get('type', '').strip()
    category = request.args.get('category', '').strip()
    series = request.args.get('series', '').strip()
    rarity = request.args.get('rarity', '').strip()
    cost_min = request.args.get('cost_min', type=int)
    cost_max = request.args.get('cost_max', type=int)
    sort_by = request.args.get('sort', 'number')
    sort_order = request.args.get('order', 'asc')
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    results = idx
    if card_type:
        results = [c for c in results if c['type'] == card_type]
    if category:
        results = [c for c in results if c['category'] == category]
    if series:
        results = [c for c in results if c['series'] == series]
    if rarity:
        results = [c for c in results if c.get('rarity') == rarity]
    if cost_min is not None:
        results = [c for c in results if c['cost'] is not None and c['cost'] >= cost_min]
    if cost_max is not None:
        results = [c for c in results if c['cost'] is not None and c['cost'] <= cost_max]
    if q:
        results = [c for c in results if q in (c['number'] or '').lower()
                   or q in (c['name'] or '').lower()
                   or q in (c['series'] or '').lower()]

    # ソート
    sort_key_map = {
        'number': 'number', 'cost': 'cost', 'name': 'name',
        'mobility': 'mobility', 'ranged': 'ranged', 'melee': 'melee', 'hp': 'hp',
    }
    key = sort_key_map.get(sort_by, 'number')
    reverse = sort_order == 'desc'
    # None値は常に末尾に配置（昇順でも降順でも）
    none_items = [c for c in results if c.get(key) is None]
    valid_items = [c for c in results if c.get(key) is not None]
    valid_items.sort(key=lambda c: c.get(key), reverse=reverse)
    results = valid_items + none_items

    total = len(results)
    results = results[offset:offset + limit]
    return jsonify({'success': True, 'total': total, 'cards': results})


@app.route('/api/decks', methods=['GET'])
def api_list_decks():
    """デッキ一覧を返す"""
    decks = db.list_decks()
    # Sanitize: replace hash with boolean flag
    for d in decks:
        has_pw = bool(d.get('delete_password_hash'))
        d.pop('delete_password_hash', None)
        d['delete_password_hash'] = has_pw
    return jsonify({'success': True, 'decks': decks})


@app.route('/api/decks', methods=['POST'])
def api_create_deck():
    """デッキを新規保存（カード番号のみ）"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data received'}), 400
    deck_name = data.get('deck_name', '').strip()
    cards = data.get('cards', [])
    comment = data.get('comment', '').strip()
    if not deck_name or not cards or not any(c for c in cards if c):
        return jsonify({'success': False, 'error': 'デッキ名とカード構成は必須です'}), 400
    deck_data = {
        'deck_name': deck_name,
        'comment': comment,
        'cards': cards,
        'tactics_main': data.get('tactics_main'),
        'tactics_sub': data.get('tactics_sub'),
        'timestamp': data.get('timestamp') or time.strftime('%Y-%m-%dT%H:%M:%S'),
        'delete_password': data.get('delete_password', '').strip(),
        'author': data.get('author', '').strip()[:30],
    }
    entry, err = db.create_deck(deck_data)
    if err:
        return jsonify({'success': False, 'error': err}), 500
    return jsonify({'success': True, 'id': entry['id'], 'message': 'デッキを保存しました'})


@app.route('/api/decks/<deck_id>', methods=['PUT'])
def api_update_deck(deck_id):
    """デッキを更新"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data received'}), 400
    ok, err = db.update_deck(deck_id, data)
    if not ok:
        return jsonify({'success': False, 'error': err}), 404
    return jsonify({'success': True, 'message': 'デッキを更新しました'})


@app.route('/api/decks/<deck_id>', methods=['DELETE'])
def api_delete_deck(deck_id):
    """デッキを削除（パスワード認証）"""
    data = request.get_json() or {}
    password = data.get('password', '').strip()
    if not password:
        return jsonify({'success': False, 'error': '削除パスワードを入力してください'}), 400
    ok, err = db.verify_delete_password(deck_id, password)
    if not ok:
        return jsonify({'success': False, 'error': err}), 403
    ok, err = db.delete_deck(deck_id)
    if not ok:
        return jsonify({'success': False, 'error': err}), 404
    return jsonify({'success': True, 'message': 'デッキを削除しました'})


@app.route('/api/decks/<deck_id>/like', methods=['POST'])
def api_like_deck(deck_id):
    """デッキにイイネを追加"""
    likes, err = db.like_deck(deck_id)
    if err:
        return jsonify({'success': False, 'error': err}), 404
    return jsonify({'success': True, 'likes': likes})


@app.route('/api/decks/<deck_id>/comments', methods=['GET'])
def api_get_comments(deck_id):
    """デッキのコメント一覧を取得"""
    comments, err = db.get_comments(deck_id)
    if err:
        return jsonify({'success': False, 'error': err}), 404
    return jsonify({'success': True, 'comments': comments})


@app.route('/api/decks/<deck_id>/comments', methods=['POST'])
def api_post_comment(deck_id):
    """デッキにコメントを投稿"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data'}), 400
    text = (data.get('text') or '').strip()
    name = (data.get('name') or '').strip() or 'アースノイド'
    if not text:
        return jsonify({'success': False, 'error': 'コメントを入力してください'}), 400
    if len(text) > 500:
        return jsonify({'success': False, 'error': 'コメントは500文字以内にしてください'}), 400
    reply_to = (data.get('reply_to') or '').strip() or None
    comment, err = db.post_comment(deck_id, name, text, reply_to=reply_to)
    if err:
        return jsonify({'success': False, 'error': err}), 404
    return jsonify({'success': True, 'comment': comment})


@app.route('/api/cache/clear', methods=['POST'])
@require_admin
def api_clear_cache():
    """カードインデックスキャッシュをクリアして再構築する"""
    global _card_index_cache, _card_detail_cache, _link_index_cache, _ocr_file_map_cache, _tactics_cards_cache
    with _card_cache_lock:
        _card_index_cache = None
        _card_detail_cache = {}
        _link_index_cache = None
        _tactics_cards_cache = None
    with _ocr_file_map_lock:
        _ocr_file_map_cache = None
    get_card_index()
    return jsonify({'success': True, 'message': 'キャッシュを再構築しました'})


# ====================================================
# 管理画面: カードデータ収集・閲覧
# ====================================================

@app.route('/admin')
@require_admin
def admin():
    return render_template('admin.html')


@app.route('/api/admin/stats')
@require_admin
def api_admin_stats():
    """カードデータの統計情報を返す"""
    all_cards_dir = 'all_cards_list'
    ocr_dir = 'ocr_results_debug'

    card_count = 0
    series_set = set()
    back_image_count = 0

    if os.path.exists(all_cards_dir):
        for fn in os.listdir(all_cards_dir):
            if not fn.endswith('.json'):
                continue
            card_count += 1
            # シリーズをファイル名から抽出
            m = re.match(r'([A-Z]{2,3}\d{2})', fn)
            if m:
                series_set.add(m.group(1))
            # 裏面画像の有無を確認
            try:
                with open(os.path.join(all_cards_dir, fn), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        data = data[0]
                    if isinstance(data, dict):
                        back_url = data.get('back', {}).get('image_url', '')
                        if back_url:
                            back_image_count += 1
            except Exception:
                continue

    ocr_count = 0
    ocr_numbers = set()
    if os.path.exists(ocr_dir):
        for fn in os.listdir(ocr_dir):
            if fn.endswith('.json'):
                m = re.search(r'([A-Z0-9\-]{4,}-\d{2,4})', fn)
                if m:
                    ocr_numbers.add(m.group(1))
        ocr_count = len(ocr_numbers)

    # シリーズ別カード数
    series_counts = {}
    if os.path.exists(all_cards_dir):
        for fn in os.listdir(all_cards_dir):
            if not fn.endswith('.json'):
                continue
            m = re.match(r'([A-Z]{2,3}\d{2})', fn)
            if m:
                s = m.group(1)
                series_counts[s] = series_counts.get(s, 0) + 1

    return jsonify({
        'success': True,
        'card_count': card_count,
        'back_image_count': back_image_count,
        'ocr_count': ocr_count,
        'series_count': len(series_set),
        'series_counts': series_counts,
    })


def _run_collection():
    """バックグラウンドでカードデータを収集する"""
    global _collect_status, _card_index_cache, _card_detail_cache, _link_index_cache

    with _collect_lock:
        _collect_status["running"] = True
        _collect_status["errors"] = []
        _collect_status["log"] = []
        _collect_status["collected_cards"] = 0
        _collect_status["series_index"] = 0
        _collect_status["total_series"] = 0
        _collect_status["current_series"] = ""
        _collect_status["started_at"] = time.strftime('%Y-%m-%dT%H:%M:%S')
        _collect_status["finished_at"] = None

    try:
        # Step 1: シリーズ一覧を取得
        with _collect_lock:
            _collect_status["log"].append("シリーズ一覧を取得中...")
        series_list = fetch_all_series_ids()
        if not series_list:
            with _collect_lock:
                _collect_status["errors"].append("シリーズ一覧の取得に失敗しました")
                _collect_status["log"].append("エラー: シリーズ一覧の取得に失敗")
                _collect_status["running"] = False
                _collect_status["finished_at"] = time.strftime('%Y-%m-%dT%H:%M:%S')
            return

        # シリーズリストを保存
        os.makedirs('series_data', exist_ok=True)
        with open('series_data/series_list.json', 'w', encoding='utf-8') as f:
            json.dump(series_list, f, ensure_ascii=False, indent=2)

        with _collect_lock:
            _collect_status["total_series"] = len(series_list)
            _collect_status["log"].append(f"{len(series_list)}個のシリーズを取得しました")

        # Step 2: 各シリーズのカードを収集
        all_cards_dir = 'all_cards_list'
        os.makedirs(all_cards_dir, exist_ok=True)

        for i, series in enumerate(series_list):
            with _collect_lock:
                _collect_status["series_index"] = i + 1
                _collect_status["current_series"] = series['label']

            try:
                cards = fetch_cards_for_series(series['url'], series['id'], series['label'])
                saved = 0
                if cards:
                    for card in cards:
                        if save_card_data(card, all_cards_dir):
                            saved += 1
                with _collect_lock:
                    _collect_status["collected_cards"] += saved
                    _collect_status["log"].append(
                        f"[{i+1}/{len(series_list)}] {series['label']} → {saved}枚収集"
                    )
            except Exception as e:
                with _collect_lock:
                    err_msg = f"{series['label']}: {str(e)}"
                    _collect_status["errors"].append(err_msg)
                    _collect_status["log"].append(f"エラー: {err_msg}")

            # サーバーに負荷をかけないように待機
            if i < len(series_list) - 1:
                time.sleep(1)

        # Step 3: キャッシュクリア → 再構築
        with _card_cache_lock:
            _card_index_cache = None
            _card_detail_cache = {}
            _link_index_cache = None
        get_card_index()

        with _collect_lock:
            _collect_status["log"].append("収集完了。キャッシュを再構築しました。")

    except Exception as e:
        with _collect_lock:
            _collect_status["errors"].append(f"予期しないエラー: {str(e)}")
            _collect_status["log"].append(f"致命的エラー: {str(e)}")
    finally:
        with _collect_lock:
            _collect_status["running"] = False
            _collect_status["finished_at"] = time.strftime('%Y-%m-%dT%H:%M:%S')


@app.route('/api/admin/collect', methods=['POST'])
@require_admin
def api_admin_collect():
    """全カードデータ収集をバックグラウンドで開始"""
    with _collect_lock:
        if _collect_status["running"]:
            return jsonify({'success': False, 'error': '収集タスクが既に実行中です'}), 409

    t = threading.Thread(target=_run_collection, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': '収集を開始しました'})


@app.route('/api/admin/collect/status')
@require_admin
def api_admin_collect_status():
    """収集タスクの進捗を返す"""
    with _collect_lock:
        return jsonify({
            'success': True,
            'running': _collect_status["running"],
            'current_series': _collect_status["current_series"],
            'series_index': _collect_status["series_index"],
            'total_series': _collect_status["total_series"],
            'collected_cards': _collect_status["collected_cards"],
            'errors': list(_collect_status["errors"]),
            'log': list(_collect_status["log"][-50:]),  # 最新50件
            'started_at': _collect_status["started_at"],
            'finished_at': _collect_status["finished_at"],
        })


@app.route('/api/admin/cards')
@require_admin
def api_admin_cards():
    """収集済みカードの一覧（ページネーション付き）"""
    idx = get_card_index()
    series_filter = request.args.get('series', '').strip()
    q = request.args.get('q', '').strip().lower()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(per_page, 200)

    results = idx
    if series_filter:
        results = [c for c in results if c['series'] == series_filter]
    if q:
        results = [c for c in results if
                   q in (c['number'] or '').lower() or
                   q in (c['name'] or '').lower()]

    total = len(results)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    page_items = results[start:start + per_page]

    # OCRデータ有無を付与
    ocr_numbers = set()
    ocr_dir = 'ocr_results_debug'
    if os.path.exists(ocr_dir):
        for fn in os.listdir(ocr_dir):
            if fn.endswith('.json'):
                m = re.search(r'([A-Z0-9\-]{4,}-\d{2,4})', fn)
                if m:
                    ocr_numbers.add(m.group(1))

    cards_out = []
    for c in page_items:
        cards_out.append({
            'number': c['number'],
            'name': c['name'],
            'series': c['series'],
            'front_url': c['front_url'],
            'back_url': c.get('back_url', ''),
            'has_ocr': c['number'] in ocr_numbers,
        })

    # シリーズ一覧（フィルタ用）
    all_series = sorted(set(c['series'] for c in idx if c['series']))

    return jsonify({
        'success': True,
        'cards': cards_out,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'series_list': all_series,
    })


# ====================================================
# OCR管理画面: OCRデータ閲覧・進捗確認
# ====================================================

# OCRファイルマップキャッシュ（カード番号→OCRファイル種別）
_ocr_file_map_cache = None
_ocr_file_map_lock = threading.Lock()


def _build_ocr_file_map():
    """ocr_results_debug/ のファイル名をスキャンし、カード番号→OCRファイル種別マップを構築"""
    global _ocr_file_map_cache
    ocr_dir = 'ocr_results_debug'
    file_map = {}
    if os.path.exists(ocr_dir):
        number_pattern = re.compile(r'([A-Z0-9]+-\d{2,4})')
        for fn in os.listdir(ocr_dir):
            if not fn.endswith('.json'):
                continue
            m = number_pattern.search(fn)
            if not m:
                continue
            number = m.group(1)
            if number not in file_map:
                file_map[number] = {'raw': False, 'basic': False, 'sp': False, 'sq': False}
            if fn.endswith('_ocr_raw.json'):
                file_map[number]['raw'] = True
            elif fn.endswith('_basic.json'):
                file_map[number]['basic'] = True
            elif fn.endswith('_sp.json'):
                file_map[number]['sp'] = True
            elif fn.endswith('_sq_analysis.json'):
                file_map[number]['sq'] = True
    _ocr_file_map_cache = file_map
    return file_map


def _get_ocr_file_map():
    """キャッシュされたOCRファイルマップを返す（初回は構築）"""
    global _ocr_file_map_cache
    if _ocr_file_map_cache is None:
        with _ocr_file_map_lock:
            if _ocr_file_map_cache is None:
                _build_ocr_file_map()
    return _ocr_file_map_cache


@app.route('/ocr-admin')
@require_admin
def ocr_admin():
    return redirect('/admin')


def _get_failed_numbers():
    """ocr_cc_progress.json から失敗カード番号セットを返す（_p1等サフィックスを正規化）"""
    progress_file = 'ocr_cc_progress.json'
    if not os.path.exists(progress_file):
        return set()
    try:
        with open(progress_file, 'r', encoding='utf-8') as f:
            pdata = json.load(f)
        failed_raw = pdata.get('failed', [])
        # _p1, _p2 等のサフィックスを除去して正規化
        normalized = set()
        for item in failed_raw:
            clean = re.sub(r'_p\d+$', '', item)
            if clean:
                normalized.add(clean)
        return normalized
    except Exception:
        return set()


@app.route('/api/ocr-admin/stats')
@require_admin
def api_ocr_admin_stats():
    """OCR処理の全体統計を返す"""
    ocr_map = _get_ocr_file_map()
    failed_numbers = _get_failed_numbers()

    # 公式サイトから取得した全カードを all_cards_list/ から直接カウント（get_card_indexに依存しない）
    all_cards_dir = 'all_cards_list'
    total_cards = 0
    series_total = {}
    all_card_numbers = set()
    back_image_numbers = set()

    if os.path.exists(all_cards_dir):
        for fn in os.listdir(all_cards_dir):
            if not fn.endswith('.json'):
                continue
            total_cards += 1
            # シリーズをファイル名から抽出
            m = re.match(r'([A-Z]{2,3}\d{2})', fn)
            if m:
                s = m.group(1)
                series_total[s] = series_total.get(s, 0) + 1
            # カード番号と裏面画像の有無を確認
            try:
                with open(os.path.join(all_cards_dir, fn), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        data = data[0]
                    if isinstance(data, dict):
                        num = data.get('number', '')
                        if num:
                            all_card_numbers.add(num)
                        if data.get('back', {}).get('image_url', ''):
                            back_image_numbers.add(num)
            except Exception:
                continue

    raw_count = sum(1 for v in ocr_map.values() if v['raw'] or v['basic'])
    basic_count = sum(1 for v in ocr_map.values() if v['basic'])

    # 画像ありかつ未OCRカード数（実際の裏面画像があるがOCR未実施）
    image_no_ocr = len(back_image_numbers - set(ocr_map.keys()))
    # OCR失敗カード数（公式カードに存在する失敗のみカウント）
    failed_count = len(failed_numbers & all_card_numbers)

    series_ocr = {}
    for number, info in ocr_map.items():
        m = re.match(r'([A-Z]{2,3}\d{2})', number)
        if m:
            s = m.group(1)
            if info['basic']:
                series_ocr[s] = series_ocr.get(s, 0) + 1

    # シリーズ別失敗カウント
    series_failed = {}
    for num in (failed_numbers & all_card_numbers):
        m = re.match(r'([A-Z]{2,}\d{2})', num)
        if m:
            s = m.group(1)
            series_failed[s] = series_failed.get(s, 0) + 1

    series_coverage = []
    for s in sorted(series_total.keys()):
        t = series_total[s]
        o = series_ocr.get(s, 0)
        series_coverage.append({
            'series': s,
            'total': t,
            'raw': sum(1 for num, info in ocr_map.items() if re.match(r'^' + re.escape(s), num) and (info['raw'] or info['basic'])),
            'basic': o,
            'failed': series_failed.get(s, 0),
            'coverage': round(o / t * 100, 1) if t > 0 else 0,
        })

    return jsonify({
        'success': True,
        'total_cards': total_cards,
        'raw_count': raw_count,
        'basic_count': basic_count,
        'image_no_ocr': image_no_ocr,
        'failed_count': failed_count,
        'coverage_pct': round(basic_count / total_cards * 100, 1) if total_cards > 0 else 0,
        'series_coverage': series_coverage,
    })


@app.route('/api/ocr-admin/cards')
@require_admin
def api_ocr_admin_cards():
    """OCRステータス付きカード一覧（ページネーション対応）"""
    ocr_map = _get_ocr_file_map()
    idx = get_card_index()
    failed_numbers = _get_failed_numbers()

    series_filter = request.args.get('series', '').strip()
    status_filter = request.args.get('status', '').strip()
    q = request.args.get('q', '').strip().lower()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(per_page, 200)

    results = idx
    if series_filter:
        results = [c for c in results if c['series'] == series_filter]
    if q:
        results = [c for c in results if
                   q in (c['number'] or '').lower() or
                   q in (c['name'] or '').lower()]
    if status_filter:
        if status_filter == 'raw_only':
            results = [c for c in results if
                       c['number'] in ocr_map and
                       (ocr_map[c['number']]['raw'] or ocr_map[c['number']]['basic']) and
                       not ocr_map[c['number']]['basic']]
        elif status_filter == 'basic':
            results = [c for c in results if
                       c['number'] in ocr_map and ocr_map[c['number']]['basic']]
        elif status_filter == 'none':
            results = [c for c in results if c['number'] not in ocr_map]
        elif status_filter == 'failed':
            results = [c for c in results if c['number'] in failed_numbers]
        elif status_filter == 'image_no_ocr':
            results = [c for c in results if c.get('has_back_image') and c['number'] not in ocr_map]

    total = len(results)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    page_items = results[start:start + per_page]

    cards_out = []
    for c in page_items:
        info = ocr_map.get(c['number'], {})
        cards_out.append({
            'number': c['number'],
            'name': c['name'],
            'series': c['series'],
            'type': c.get('type', ''),
            'front_url': c['front_url'],
            'has_raw': info.get('raw', False) or info.get('basic', False),
            'has_basic': info.get('basic', False),
            'is_failed': c['number'] in failed_numbers,
        })

    all_series = sorted(set(c['series'] for c in idx if c['series']))

    return jsonify({
        'success': True,
        'cards': cards_out,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'series_list': all_series,
    })


@app.route('/api/ocr-admin/card/<number>')
@require_admin
def api_ocr_admin_card_detail(number):
    """単一カードの全OCRデータ（raw_text + structured）を返す"""
    ocr_dir = 'ocr_results_debug'

    raw_text = None
    basic_data = None

    if os.path.exists(ocr_dir):
        for fn in sorted(os.listdir(ocr_dir)):
            if not fn.endswith('.json'):
                continue
            if number not in fn:
                continue
            try:
                filepath = os.path.join(ocr_dir, fn)
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if fn.endswith('_ocr_raw.json'):
                    raw_text = data
                elif fn.endswith('_basic.json'):
                    basic_data = data
            except Exception:
                continue

    # カード基本情報
    detail = get_card_detail(number)
    card_info = {
        'number': number,
        'name': detail.get('name', '') if detail else '',
        'front_url': detail['front']['image_url'] if detail and detail.get('front') else '',
        'back_url': detail['back']['image_url'] if detail and detail.get('back') else '',
    }

    return jsonify({
        'success': True,
        'card': card_info,
        'raw_text': raw_text,
        'basic': basic_data,
    })


# ====================================================
# OCR実行管理画面
# ====================================================

@app.route('/ocr-run')
@require_admin
def ocr_run():
    return render_template('ocr_run.html')


@app.route('/api/ocr-run/series-stats')
@require_admin
def api_ocr_run_series_stats():
    """シリーズ別OCRカバレッジ統計を返す"""
    idx = get_card_index()
    existing_raw = get_existing_raw_numbers()
    existing_basic = get_existing_ocr_numbers()

    series_total = {}
    for c in idx:
        s = c.get('series', '')
        if s:
            series_total[s] = series_total.get(s, 0) + 1

    series_raw = {}
    for num in existing_raw:
        m = re.match(r'([A-Z]{2,3}\d{2})', num)
        if m:
            s = m.group(1)
            series_raw[s] = series_raw.get(s, 0) + 1

    series_basic = {}
    for num in existing_basic:
        m = re.match(r'([A-Z]{2,3}\d{2})', num)
        if m:
            s = m.group(1)
            series_basic[s] = series_basic.get(s, 0) + 1

    series_list = []
    for s in sorted(series_total.keys()):
        t = series_total[s]
        r = series_raw.get(s, 0)
        b = series_basic.get(s, 0)
        remaining = t - b
        series_list.append({
            'series': s,
            'total': t,
            'raw': r,
            'basic': b,
            'remaining': remaining,
            'coverage': round(b / t * 100, 1) if t > 0 else 0,
        })

    total_cards = sum(v for v in series_total.values())
    total_raw = len(existing_raw)
    total_basic = len(existing_basic)

    return jsonify({
        'success': True,
        'total_cards': total_cards,
        'total_raw': total_raw,
        'total_basic': total_basic,
        'series': series_list,
    })


@app.route('/api/ocr-run/start', methods=['POST'])
@require_admin
def api_ocr_run_start():
    """OCR実行を開始する（課金発生のため特に保護）"""
    with _ocr_run_lock:
        if _ocr_run_status["running"]:
            return jsonify({'success': False, 'error': 'OCRタスクが既に実行中です'}), 409

    data = request.get_json() or {}
    series = data.get('series', '').strip()
    stage = data.get('stage', 'both').strip()
    force = bool(data.get('force', False))
    limit = int(data.get('limit', 0))

    if not series:
        return jsonify({'success': False, 'error': 'シリーズを指定してください'}), 400
    if stage not in ('raw', 'structure', 'both'):
        return jsonify({'success': False, 'error': '無効なステージです'}), 400

    t = threading.Thread(
        target=_run_ocr_execution,
        args=(series, stage, force, limit),
        daemon=True,
    )
    t.start()
    return jsonify({'success': True, 'message': f'{series} のOCR実行を開始しました'})


@app.route('/api/ocr-run/status')
@require_admin
def api_ocr_run_status():
    """OCR実行の進捗を返す"""
    with _ocr_run_lock:
        return jsonify({
            'success': True,
            'running': _ocr_run_status["running"],
            'stop_requested': _ocr_run_status["stop_requested"],
            'series': _ocr_run_status["series"],
            'stage': _ocr_run_status["stage"],
            'current_card': _ocr_run_status["current_card"],
            'current_card_name': _ocr_run_status["current_card_name"],
            'processed_count': _ocr_run_status["processed_count"],
            'success_count': _ocr_run_status["success_count"],
            'failed_count': _ocr_run_status["failed_count"],
            'total_target': _ocr_run_status["total_target"],
            'log': list(_ocr_run_status["log"][-100:]),
            'errors': list(_ocr_run_status["errors"]),
            'started_at': _ocr_run_status["started_at"],
            'finished_at': _ocr_run_status["finished_at"],
            'elapsed_seconds': _ocr_run_status["elapsed_seconds"],
            'eta_seconds': _ocr_run_status["eta_seconds"],
        })


@app.route('/api/ocr-run/stop', methods=['POST'])
@require_admin
def api_ocr_run_stop():
    """OCR実行の停止をリクエスト"""
    with _ocr_run_lock:
        if not _ocr_run_status["running"]:
            return jsonify({'success': False, 'error': '実行中のタスクがありません'}), 400
        _ocr_run_status["stop_requested"] = True
        _ocr_run_status["log"].append("停止リクエストを受信しました。現在のカード処理完了後に停止します。")
    return jsonify({'success': True, 'message': '停止をリクエストしました'})


def _run_ocr_execution(series, stage, force, limit):
    """バックグラウンドでOCR処理を実行するワーカー"""
    global _ocr_file_map_cache, _card_index_cache, _card_detail_cache, _link_index_cache

    # ログハンドラを一時的に追加
    log_handler = OcrRunLogHandler()
    log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    card_ocr_cc.logger.addHandler(log_handler)

    with _ocr_run_lock:
        _ocr_run_status["running"] = True
        _ocr_run_status["stop_requested"] = False
        _ocr_run_status["series"] = series
        _ocr_run_status["stage"] = stage
        _ocr_run_status["current_card"] = ""
        _ocr_run_status["current_card_name"] = ""
        _ocr_run_status["processed_count"] = 0
        _ocr_run_status["success_count"] = 0
        _ocr_run_status["failed_count"] = 0
        _ocr_run_status["total_target"] = 0
        _ocr_run_status["log"] = []
        _ocr_run_status["errors"] = []
        _ocr_run_status["started_at"] = time.strftime('%Y-%m-%dT%H:%M:%S')
        _ocr_run_status["finished_at"] = None
        _ocr_run_status["elapsed_seconds"] = 0
        _ocr_run_status["eta_seconds"] = 0

    start_time = time.time()

    try:
        with _ocr_run_lock:
            _ocr_run_status["log"].append(f"カード一覧を読み込み中... (シリーズ: {series})")

        all_cards = ocr_load_unique_cards()

        # シリーズでフィルタ
        targets = [c for c in all_cards if c["card_number"].upper().startswith(series.upper())]

        # ステージに応じてフィルタ
        if not force:
            existing_raw = get_existing_raw_numbers()
            existing_basic = get_existing_ocr_numbers()
            if stage == "structure":
                targets = [c for c in targets
                           if c["card_number"] in existing_raw
                           and c["card_number"] not in existing_basic]
            elif stage == "raw":
                targets = [c for c in targets if c["card_number"] not in existing_raw]
            else:  # both
                targets = [c for c in targets if c["card_number"] not in existing_basic]

        # 裏面画像なしを除外（raw/bothの場合）
        if stage in ("raw", "both"):
            targets = [c for c in targets if c.get("back_url")]

        if limit > 0:
            targets = targets[:limit]

        total = len(targets)
        with _ocr_run_lock:
            _ocr_run_status["total_target"] = total
            _ocr_run_status["log"].append(f"処理対象: {total} 件 (stage: {stage}, force: {force})")

        if total == 0:
            with _ocr_run_lock:
                _ocr_run_status["log"].append("処理対象カードがありません。")
            return

        done_count = 0
        fatal = False
        for card in targets:
            # 停止チェック
            with _ocr_run_lock:
                if _ocr_run_status["stop_requested"]:
                    _ocr_run_status["log"].append("停止リクエストにより処理を中断しました。")
                    break

            card_number = card["card_number"]
            card_name = card["card_name"]
            try:
                ok = ocr_process_card(card, model=None, force=force, stage=stage)
                error_msg = None
                is_fatal = False
            except SystemExit:
                ok = False
                error_msg = "claude CLIが見つかりません (SystemExit)"
                is_fatal = True
            except Exception as e:
                ok = False
                error_msg = str(e)
                is_fatal = False

            done_count += 1
            with _ocr_run_lock:
                _ocr_run_status["processed_count"] = done_count
                _ocr_run_status["current_card"] = card_number
                _ocr_run_status["current_card_name"] = card_name
                if ok:
                    _ocr_run_status["success_count"] += 1
                else:
                    _ocr_run_status["failed_count"] += 1
                    if error_msg:
                        _ocr_run_status["errors"].append(f"{card_number}: {error_msg}")

                elapsed = time.time() - start_time
                _ocr_run_status["elapsed_seconds"] = int(elapsed)
                if done_count > 0 and done_count < total:
                    eta = elapsed / done_count * (total - done_count)
                    _ocr_run_status["eta_seconds"] = int(eta)
                else:
                    _ocr_run_status["eta_seconds"] = 0

                status_str = "OK" if ok else "FAIL"
                _ocr_run_status["log"].append(
                    f"[{done_count}/{total}] {card_number} {card_name} {status_str}"
                )

            if is_fatal:
                with _ocr_run_lock:
                    _ocr_run_status["log"].append("致命的エラー: claude CLIが見つかりません。処理を中断します。")
                fatal = True
                break

        # キャッシュクリア
        with _ocr_run_lock:
            _ocr_run_status["log"].append("キャッシュをクリア中...")

        with _card_cache_lock:
            _card_index_cache = None
            _card_detail_cache = {}
            _link_index_cache = None
        with _ocr_file_map_lock:
            _ocr_file_map_cache = None

        with _ocr_run_lock:
            _ocr_run_status["log"].append("処理完了。")

    except Exception as e:
        with _ocr_run_lock:
            _ocr_run_status["errors"].append(f"予期しないエラー: {str(e)}")
            _ocr_run_status["log"].append(f"致命的エラー: {str(e)}")
    finally:
        card_ocr_cc.logger.removeHandler(log_handler)
        with _ocr_run_lock:
            _ocr_run_status["running"] = False
            _ocr_run_status["finished_at"] = time.strftime('%Y-%m-%dT%H:%M:%S')
            _ocr_run_status["elapsed_seconds"] = int(time.time() - start_time)
            _ocr_run_status["current_card"] = ""
            _ocr_run_status["current_card_name"] = ""


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host='0.0.0.0', port=port)