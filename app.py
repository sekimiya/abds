from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, Response, g
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

try:
    from flask_compress import Compress
except ImportError:
    Compress = None

from fetch_series_ids import fetch_all_series_ids
from fetch_cards import fetch_cards_for_series, save_card_data

from logic import (
    safe_int,
    get_nested,
    extract_stats,
    get_link_abilities,
    parse_link_condition,
    build_card_index,
    classify_sp_effects,
)

_classify_sp_effects = classify_sp_effects  # 内部参照の互換性

from card_ocr_cc import (
    load_unique_cards as ocr_load_unique_cards,
    process_card as ocr_process_card,
    get_existing_raw_numbers,
    get_existing_ocr_numbers,
)
import card_ocr_cc
import ocr_test
import db
import metrics

# 後方互換: 旧名でもアクセス可能にする
_safe_int = safe_int

app = Flask(__name__)

# --- 本番/開発モード判定 ---
_is_production = os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production'
app.config['TEMPLATES_AUTO_RELOAD'] = not _is_production

# --- gzip圧縮 ---
if Compress:
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html', 'text/css', 'text/xml', 'text/plain',
        'application/json', 'application/javascript',
    ]
    app.config['COMPRESS_MIN_SIZE'] = 500  # 500B以上を圧縮
    Compress(app)

# --- セキュリティ設定 ---
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# 管理者認証設定（Basic認証 or トークン認証）
ADMIN_USER = os.environ.get('ADMIN_USER', '').strip()
ADMIN_PASS = os.environ.get('ADMIN_PASS', '').strip()
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', '').strip()
if not ADMIN_TOKEN:
    ADMIN_TOKEN = secrets.token_hex(24)
if ADMIN_USER and ADMIN_PASS:
    print(f"[SECURITY] Basic認証が有効です (user: {ADMIN_USER})")
else:
    print(f"[SECURITY] ADMIN_TOKEN: {ADMIN_TOKEN}")
    print(f"[SECURITY] Basic認証を使うには .env に ADMIN_USER / ADMIN_PASS を設定してください")


def _check_basic_auth(auth_header):
    """Basic認証ヘッダを検証する。成功ならTrue。"""
    if not auth_header.startswith('Basic ') or not ADMIN_USER:
        return False
    import base64
    try:
        decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        user, pw = decoded.split(':', 1)
        return secrets.compare_digest(user, ADMIN_USER) and secrets.compare_digest(pw, ADMIN_PASS)
    except Exception:
        return False


def require_admin(f):
    """管理エンドポイント用の認証デコレータ。
    セッションCookie、Basic認証、Bearer トークン、?token= クエリのいずれかで認証する。
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        from flask import session
        # 0. セッションCookie（Basic認証成功後に発行）
        if session.get('admin_authenticated'):
            return f(*args, **kwargs)
        auth_header = request.headers.get('Authorization', '')
        # 1. Basic認証 → 成功したらセッションに記録
        if _check_basic_auth(auth_header):
            session['admin_authenticated'] = True
            return f(*args, **kwargs)
        # 2. Bearerトークン
        token = None
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
        # 3. クエリパラメータ
        if not token:
            token = request.args.get('token', '').strip()
        if token and secrets.compare_digest(token, ADMIN_TOKEN):
            session['admin_authenticated'] = True
            return f(*args, **kwargs)
        # Basic認証が設定されている場合は401 + WWW-Authenticate を返す
        if ADMIN_USER and ADMIN_PASS:
            return Response('認証が必要です', 401, {'WWW-Authenticate': 'Basic realm="Admin"'})
        return jsonify({'success': False, 'error': '認証が必要です'}), 401
    return decorated


# --- セキュリティヘッダ ---
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


# --- アクセスメトリクス ---
metrics.init_db()

@app.before_request
def _metrics_before():
    g._metrics_start = time.time()

@app.after_request
def _metrics_after(response):
    elapsed = (time.time() - getattr(g, '_metrics_start', time.time())) * 1000
    try:
        metrics.record_request(
            request.method, request.path,
            response.status_code, elapsed,
            request.remote_addr
        )
    except Exception:
        pass
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

# --- 事前シリアライズ済みレスポンスキャッシュ ---
_serialized_card_index = None   # JSON bytes
_serialized_link_index = None   # JSON bytes
_serialized_all_details = None  # JSON bytes
_card_index_etag = None         # ETag文字列
_link_index_etag = None         # ETag文字列
_all_details_etag = None        # ETag文字列

# --- バックグラウンド収集タスクの状態管理 ---
_COLLECT_HISTORY_FILE = 'collect_history.json'

def _load_collect_history():
    """前回のカード収集結果をファイルから復元"""
    if os.path.exists(_COLLECT_HISTORY_FILE):
        try:
            with open(_COLLECT_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None

def _save_collect_history(status):
    """カード収集結果をファイルに永続化"""
    history = {
        'collected_cards': status['collected_cards'],
        'total_series': status['total_series'],
        'started_at': status['started_at'],
        'finished_at': status['finished_at'],
        'error_count': len(status['errors']),
    }
    try:
        with open(_COLLECT_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

_prev_collect = _load_collect_history()
_collect_status = {
    "running": False,
    "current_series": "",
    "series_index": 0,
    "total_series": 0,
    "collected_cards": 0,
    "errors": [],
    "log": [],
    "started_at": _prev_collect.get('started_at') if _prev_collect else None,
    "finished_at": _prev_collect.get('finished_at') if _prev_collect else None,
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


def _build_card_index():
    """全カードデータとOCRデータを統合し、軽量インデックスと詳細キャッシュを構築する"""
    global _card_index_cache, _card_detail_cache, _link_index_cache

    index_list, detail_map, link_map = build_card_index(
        write_back_ocr_flags=True,
    )
    _card_index_cache = index_list
    _card_detail_cache = detail_map
    _link_index_cache = link_map
    _pre_serialize_responses(index_list, link_map)
    return index_list


def _pre_serialize_responses(index_list, link_map):
    """card_index / link_index / all_details のJSONレスポンスを事前シリアライズしてキャッシュする"""
    global _serialized_card_index, _serialized_link_index, _serialized_all_details
    global _card_index_etag, _link_index_etag, _all_details_etag

    idx_json = json.dumps({'success': True, 'cards': index_list}, ensure_ascii=False, separators=(',', ':'))
    _serialized_card_index = idx_json.encode('utf-8')
    _card_index_etag = hashlib.md5(_serialized_card_index).hexdigest()

    link_json = json.dumps({'success': True, 'links': link_map}, ensure_ascii=False, separators=(',', ':'))
    _serialized_link_index = link_json.encode('utf-8')
    _link_index_etag = hashlib.md5(_serialized_link_index).hexdigest()

    # all_details (クライアントキャッシュ用 — サイズ大のため遅延シリアライズも可)
    det_json = json.dumps({'success': True, 'cards': _card_detail_cache}, ensure_ascii=False, separators=(',', ':'))
    _serialized_all_details = det_json.encode('utf-8')
    _all_details_etag = hashlib.md5(_serialized_all_details).hexdigest()


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
        return jsonify({'error': 'invalid filename'}), 400
    filepath = os.path.join('card_images', filename)
    if os.path.isfile(filepath):
        resp = send_from_directory('card_images', filename)
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp
    return jsonify({'error': 'not found'}), 404


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
                    number_match = re.search(r'([A-Z0-9\-]{2,}-\d{2,4}(?:_p\d+)?)', base)
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
            series_match = re.match(r'([A-Z]{2,3}\d{0,2})', card_number)
            if series_match:
                card_info['series'] = series_match.group(1)

        # PR カードは100枚ごとにシリーズ分割
        if card_number and card_number.startswith('PR-'):
            pr_num_match = re.search(r'PR-(\d+)', card_number)
            if pr_num_match:
                pr_num = int(pr_num_match.group(1))
                g = (pr_num - 1) // 100
                card_info['series'] = f'PR-{g*100+1:03d}~{(g+1)*100}'

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

def _make_cached_response(serialized_bytes, etag):
    """事前シリアライズ済みJSONからETag対応レスポンスを生成"""
    # ブラウザキャッシュが有効なら304を返す
    if_none_match = request.headers.get('If-None-Match', '')
    if if_none_match and if_none_match == etag:
        return Response(status=304)
    resp = Response(serialized_bytes, mimetype='application/json')
    resp.headers['ETag'] = etag
    resp.headers['Cache-Control'] = 'public, max-age=60, stale-while-revalidate=300'
    return resp


@app.route('/api/card_index')
def api_card_index():
    """軽量カードインデックスを返す（事前シリアライズ済み + ETag対応）"""
    get_card_index()  # キャッシュ構築を確実に
    if _serialized_card_index and _card_index_etag:
        return _make_cached_response(_serialized_card_index, _card_index_etag)
    idx = get_card_index()
    return jsonify({'success': True, 'cards': idx})


@app.route('/api/link_index')
def api_link_index():
    """リンクアビリティ索引を返す（事前シリアライズ済み + ETag対応）"""
    get_card_index()  # キャッシュ構築を確実に
    if _serialized_link_index and _link_index_etag:
        return _make_cached_response(_serialized_link_index, _link_index_etag)
    global _link_index_cache
    if _link_index_cache is None:
        get_card_index()
    return jsonify({'success': True, 'links': _link_index_cache or {}})


_tactics_serialized = None
_tactics_etag = None

@app.route('/api/tactics_cards')
def api_tactics_cards():
    """作戦カードマスタデータを返す（ETag対応）"""
    global _tactics_cards_cache, _tactics_serialized, _tactics_etag
    if _tactics_cards_cache is None:
        tactics_file = os.path.join(os.path.dirname(__file__), 'tactics_cards.json')
        try:
            with open(tactics_file, 'r', encoding='utf-8') as f:
                _tactics_cards_cache = json.load(f)
            t_json = json.dumps({'success': True, 'data': _tactics_cards_cache}, ensure_ascii=False, separators=(',', ':'))
            _tactics_serialized = t_json.encode('utf-8')
            _tactics_etag = hashlib.md5(_tactics_serialized).hexdigest()
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    if _tactics_serialized and _tactics_etag:
        return _make_cached_response(_tactics_serialized, _tactics_etag)
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


@app.route('/api/cards/all_details')
def api_cards_all_details():
    """全カードの詳細データを一括返却（キャッシュ用 + ETag対応）"""
    get_card_index()  # キャッシュ構築を確実に
    if _serialized_all_details and _all_details_etag:
        return _make_cached_response(_serialized_all_details, _all_details_etag)
    global _card_detail_cache
    if not _card_detail_cache:
        get_card_index()
    return jsonify({'success': True, 'cards': _card_detail_cache})


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
    global _serialized_card_index, _serialized_link_index, _serialized_all_details
    global _card_index_etag, _link_index_etag, _all_details_etag
    global _tactics_serialized, _tactics_etag
    with _card_cache_lock:
        _card_index_cache = None
        _card_detail_cache = {}
        _link_index_cache = None
        _tactics_cards_cache = None
        _serialized_card_index = None
        _serialized_link_index = None
        _serialized_all_details = None
        _card_index_etag = None
        _link_index_etag = None
        _all_details_etag = None
        _tactics_serialized = None
        _tactics_etag = None
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


@app.route('/api/admin/metrics/summary')
@require_admin
def api_admin_metrics_summary():
    """メトリクス集計データ"""
    hours = request.args.get('hours', 24, type=int)
    hours = min(max(hours, 1), 720)  # 1h〜30d
    return jsonify(success=True, **metrics.get_summary(hours))


@app.route('/api/admin/metrics/recent')
@require_admin
def api_admin_metrics_recent():
    """直近リクエスト一覧"""
    limit = request.args.get('limit', 100, type=int)
    limit = min(max(limit, 1), 500)
    return jsonify(success=True, requests=metrics.get_recent(limit))


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
            m = re.match(r'([A-Z]{2,3}\d{0,2})', fn)
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
                m = re.search(r'([A-Z0-9\-]{2,}-\d{2,4}(?:_p\d+)?)', fn)
                if m:
                    ocr_numbers.add(m.group(1))
    # _pバリアントはベース番号のOCRがあれば処理済みとみなす
    if os.path.exists(all_cards_dir):
        for fn in os.listdir(all_cards_dir):
            m = re.search(r'([A-Z0-9\-]{2,}-\d{2,4}_p\d+)', fn)
            if m:
                p_num = m.group(1)
                base_num = re.sub(r'_p\d+$', '', p_num)
                if base_num in ocr_numbers:
                    ocr_numbers.add(p_num)
    ocr_count = len(ocr_numbers)

    # シリーズ別カード数
    series_counts = {}
    if os.path.exists(all_cards_dir):
        for fn in os.listdir(all_cards_dir):
            if not fn.endswith('.json'):
                continue
            m = re.match(r'([A-Z]{2,3}\d{0,2})', fn)
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
            _save_collect_history(_collect_status)


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
                m = re.search(r'([A-Z0-9\-]{2,}-\d{2,4}(?:_p\d+)?)', fn)
                if m:
                    ocr_numbers.add(m.group(1))
    # _pバリアントはベース番号のOCRがあれば処理済みとみなす
    all_cards_dir = 'all_cards_list'
    if os.path.exists(all_cards_dir):
        for fn in os.listdir(all_cards_dir):
            m = re.search(r'([A-Z0-9\-]{2,}-\d{2,4}_p\d+)', fn)
            if m:
                p_num = m.group(1)
                base_num = re.sub(r'_p\d+$', '', p_num)
                if base_num in ocr_numbers:
                    ocr_numbers.add(p_num)

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
        number_pattern = re.compile(r'([A-Z0-9\-]{2,}-\d{2,4}(?:_p\d+)?)')
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
            m = re.match(r'([A-Z]{2,3}\d{0,2})', fn)
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
        m = re.match(r'([A-Z]{2,3}\d{0,2})', number)
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
        m = re.match(r'([A-Z]{2,3}\d{0,2})', num)
        if m:
            s = m.group(1)
            series_raw[s] = series_raw.get(s, 0) + 1

    series_basic = {}
    for num in existing_basic:
        m = re.match(r'([A-Z]{2,3}\d{0,2})', num)
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
        _invalidate_validate_cache()

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


# ====================================================
# サーバーサイド画像キャッシュ管理
# ====================================================

from download_card_images import download_image as _dl_image, CARD_IMAGES_DIR, MIN_IMAGE_SIZE, DEFAULT_DELAY

_img_cache_status = {
    "running": False,
    "stop_requested": False,
    "processed_count": 0,
    "downloaded_count": 0,
    "cached_count": 0,
    "failed_count": 0,
    "total_target": 0,
    "current_card": "",
    "log": [],
    "started_at": None,
    "finished_at": None,
    "elapsed_seconds": 0,
    "eta_seconds": 0,
}
_img_cache_lock = threading.Lock()


def _count_cached_images():
    """card_images/ 内の有効な画像ファイル数を返す"""
    count = 0
    try:
        with os.scandir(str(CARD_IMAGES_DIR)) as entries:
            for entry in entries:
                if entry.is_file() and entry.name.endswith('.jpg') and entry.stat().st_size > MIN_IMAGE_SIZE:
                    count += 1
    except OSError:
        pass
    return count


@app.route('/api/admin/image-cache/stats')
@require_admin
def api_image_cache_stats():
    """サーバーキャッシュ済み画像枚数と全カード数を返す"""
    cached = _count_cached_images()
    cards = ocr_load_unique_cards()
    total_images = sum(1 + (1 if c.get('back_url') else 0) for c in cards)
    return jsonify({
        'success': True,
        'cached_images': cached,
        'total_images': total_images,
        'total_cards': len(cards),
    })


@app.route('/api/admin/image-cache/start', methods=['POST'])
@require_admin
def api_image_cache_start():
    """バックグラウンドで画像DLを開始する"""
    with _img_cache_lock:
        if _img_cache_status["running"]:
            return jsonify({'success': False, 'error': '画像DLタスクが既に実行中です'}), 409

    data = request.get_json() or {}
    series = data.get('series', '').strip()

    t = threading.Thread(
        target=_run_image_cache_download,
        args=(series,),
        daemon=True,
    )
    t.start()
    msg = f'{series} の画像DLを開始しました' if series else '全画像DLを開始しました'
    return jsonify({'success': True, 'message': msg})


@app.route('/api/admin/image-cache/status')
@require_admin
def api_image_cache_status():
    """画像DLの進捗を返す"""
    with _img_cache_lock:
        return jsonify({
            'success': True,
            'running': _img_cache_status["running"],
            'stop_requested': _img_cache_status["stop_requested"],
            'processed_count': _img_cache_status["processed_count"],
            'downloaded_count': _img_cache_status["downloaded_count"],
            'cached_count': _img_cache_status["cached_count"],
            'failed_count': _img_cache_status["failed_count"],
            'total_target': _img_cache_status["total_target"],
            'current_card': _img_cache_status["current_card"],
            'log': list(_img_cache_status["log"][-100:]),
            'started_at': _img_cache_status["started_at"],
            'finished_at': _img_cache_status["finished_at"],
            'elapsed_seconds': _img_cache_status["elapsed_seconds"],
            'eta_seconds': _img_cache_status["eta_seconds"],
        })


@app.route('/api/admin/image-cache/stop', methods=['POST'])
@require_admin
def api_image_cache_stop():
    """画像DLの停止をリクエスト"""
    with _img_cache_lock:
        if not _img_cache_status["running"]:
            return jsonify({'success': False, 'error': '実行中のタスクがありません'}), 400
        _img_cache_status["stop_requested"] = True
        _img_cache_status["log"].append("停止リクエストを受信しました。")
    return jsonify({'success': True, 'message': '停止をリクエストしました'})


def _run_image_cache_download(series_filter):
    """バックグラウンドで画像をダウンロードするワーカー"""
    logger = logging.getLogger('image_cache_dl')

    CARD_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    with _img_cache_lock:
        _img_cache_status["running"] = True
        _img_cache_status["stop_requested"] = False
        _img_cache_status["processed_count"] = 0
        _img_cache_status["downloaded_count"] = 0
        _img_cache_status["cached_count"] = 0
        _img_cache_status["failed_count"] = 0
        _img_cache_status["total_target"] = 0
        _img_cache_status["current_card"] = ""
        _img_cache_status["log"] = []
        _img_cache_status["started_at"] = time.strftime('%Y-%m-%dT%H:%M:%S')
        _img_cache_status["finished_at"] = None
        _img_cache_status["elapsed_seconds"] = 0
        _img_cache_status["eta_seconds"] = 0

    start_time = time.time()

    try:
        with _img_cache_lock:
            _img_cache_status["log"].append("カード一覧を読み込み中...")

        cards = ocr_load_unique_cards()
        if series_filter:
            cards = [c for c in cards if c["card_number"].startswith(series_filter)]
            with _img_cache_lock:
                _img_cache_status["log"].append(f"シリーズ {series_filter} に絞り込み: {len(cards)}枚")

        # 全DL対象をリスト化 (表+裏)
        items = []
        for card in cards:
            num = card["card_number"]
            front_url = card.get("front_url")
            back_url = card.get("back_url")
            if front_url:
                items.append((num, front_url, CARD_IMAGES_DIR / f"{num}.jpg"))
            if back_url:
                items.append((num, back_url, CARD_IMAGES_DIR / f"{num}_b.jpg"))

        total = len(items)
        with _img_cache_lock:
            _img_cache_status["total_target"] = total
            _img_cache_status["log"].append(f"DL対象: {total} 枚 (カード: {len(cards)})")

        if total == 0:
            with _img_cache_lock:
                _img_cache_status["log"].append("対象画像がありません。")
            return

        done = 0
        downloaded = 0
        cached = 0
        failed = 0

        for num, url, filepath in items:
            with _img_cache_lock:
                if _img_cache_status["stop_requested"]:
                    _img_cache_status["log"].append("停止リクエストにより処理を中断しました。")
                    break

            result = _dl_image(url, filepath, logger)
            done += 1
            if result == "downloaded":
                downloaded += 1
                time.sleep(DEFAULT_DELAY)
            elif result == "cached":
                cached += 1
            else:
                failed += 1

            with _img_cache_lock:
                _img_cache_status["processed_count"] = done
                _img_cache_status["downloaded_count"] = downloaded
                _img_cache_status["cached_count"] = cached
                _img_cache_status["failed_count"] = failed
                _img_cache_status["current_card"] = num

                elapsed = time.time() - start_time
                _img_cache_status["elapsed_seconds"] = int(elapsed)
                if done > 0 and done < total:
                    _img_cache_status["eta_seconds"] = int(elapsed / done * (total - done))
                else:
                    _img_cache_status["eta_seconds"] = 0

            # 50枚ごとにログ
            if done % 50 == 0:
                with _img_cache_lock:
                    _img_cache_status["log"].append(
                        f"[{done}/{total}] DL:{downloaded} キャッシュ済:{cached} 失敗:{failed}"
                    )

        with _img_cache_lock:
            _img_cache_status["log"].append(
                f"完了: 合計{done}件 — DL:{downloaded}, キャッシュ済:{cached}, 失敗:{failed}"
            )

    except Exception as e:
        with _img_cache_lock:
            _img_cache_status["log"].append(f"エラー: {str(e)}")
    finally:
        with _img_cache_lock:
            _img_cache_status["running"] = False
            _img_cache_status["finished_at"] = time.strftime('%Y-%m-%dT%H:%M:%S')
            _img_cache_status["elapsed_seconds"] = int(time.time() - start_time)
            _img_cache_status["current_card"] = ""


# ====================================================
# OCR バリデーション＆補正画面
# ====================================================

# --- バリデーション用カードデータキャッシュ ---
_validate_cards_cache = None
_validate_cards_cache_lock = threading.Lock()
_card_number_re = re.compile(r'([A-Z]{2,4}\d{1,2}-\d{2,4})')


def _validate_fingerprint():
    """_basic.json ファイルの個数と更新時刻合計からフィンガープリントを計算。
    os.scandir を使いファイル内容を読まずに高速判定する。"""
    ocr_dir = ocr_test.RESULTS_DIR
    count = 0
    mtime_sum = 0.0
    try:
        with os.scandir(ocr_dir) as entries:
            for entry in entries:
                if entry.name.endswith('_basic.json') and entry.is_file(follow_symlinks=False):
                    count += 1
                    mtime_sum += entry.stat().st_mtime
    except OSError:
        pass
    return (count, mtime_sum)


def _get_validate_cards(series_filter=None):
    """キャッシュされたカードデータを返す。
    ファイル追加/変更/削除を検知した場合のみ再読み込みする。"""
    global _validate_cards_cache
    fp = _validate_fingerprint()

    if _validate_cards_cache is None or _validate_cards_cache['fingerprint'] != fp:
        with _validate_cards_cache_lock:
            # Double-check after lock acquisition
            fp = _validate_fingerprint()
            if _validate_cards_cache is None or _validate_cards_cache['fingerprint'] != fp:
                cards = ocr_test.load_basic_files(ocr_test.RESULTS_DIR, series_filter=None)
                _validate_cards_cache = {'cards': cards, 'fingerprint': fp}

    cards = _validate_cards_cache['cards']

    if series_filter:
        return [
            item for item in cards
            if (m := _card_number_re.search(item[0])) and m.group(1).startswith(series_filter)
        ]
    return cards


def _invalidate_validate_cache():
    global _validate_cards_cache
    _validate_cards_cache = None


@app.route('/ocr-validate')
@require_admin
def ocr_validate():
    return render_template('ocr_validate.html')


@app.route('/api/ocr-validate/report')
@require_admin
def api_ocr_validate_report():
    """バリデーションレポートを JSON で返す。"""
    checks_param = request.args.get('checks', '')
    series = request.args.get('series', '').strip() or None

    if checks_param:
        check_keys = [c.strip() for c in checks_param.split(',') if c.strip()]
    else:
        check_keys = list(ocr_test.CHECK_FUNCTIONS.keys())

    # 不明なチェック名を弾く
    valid_keys = set(ocr_test.CHECK_FUNCTIONS.keys())
    invalid = [k for k in check_keys if k not in valid_keys]
    if invalid:
        return jsonify({'success': False, 'error': f'不明なチェック名: {", ".join(invalid)}', 'valid': sorted(valid_keys)}), 400

    cards = _get_validate_cards(series_filter=series)
    if not cards:
        return jsonify({'success': True, 'total_cards': 0, 'checks': {}, 'summary': {'warnings': 0, 'errors': 0}})

    total_warnings = 0
    total_errors = 0
    checks_result = {}

    for key in check_keys:
        title, func = ocr_test.CHECK_FUNCTIONS[key]
        raw_results = func(cards)

        # suggestion を付加: WARNING で「類似候補」が含まれる場合
        enriched = []
        for r in raw_results:
            item = dict(r)
            if item['level'] == 'WARNING' and item.get('detail', '').startswith('類似候補:'):
                detail = item['detail']
                # 類似候補: "正解名" (出現: N回, 編集距離: M) のパターンから抽出
                m = re.search(r'類似候補:\s*"(.+?)"', detail)
                if m:
                    suggested_value = m.group(1)
                    # メッセージから誤読名を抽出
                    msg = item['message']
                    m2 = re.search(r'"(.+?)"', msg)
                    if m2:
                        wrong_name = m2.group(1)
                        # カテゴリを推定
                        if key == 'link_names':
                            cat = 'link_ability_names'
                        elif key == 'pilot_skills':
                            cat = 'pilot_skill_names'
                        elif key == 'ms_abilities':
                            cat = 'ms_ability_names'
                        else:
                            cat = None
                        if cat:
                            item['suggestion'] = {'category': cat, 'key': wrong_name, 'value': suggested_value}

            if item['level'] == 'WARNING':
                total_warnings += 1
            elif item['level'] == 'ERROR':
                total_errors += 1
            enriched.append(item)

        checks_result[key] = {'title': title, 'results': enriched}

    return jsonify({
        'success': True,
        'total_cards': len(cards),
        'checks': checks_result,
        'summary': {'warnings': total_warnings, 'errors': total_errors},
    })


@app.route('/api/ocr-validate/corrections')
@require_admin
def api_ocr_validate_corrections_get():
    """補正辞書の内容を返す。"""
    corrections = ocr_test.load_corrections()
    entry_count = sum(len(v) for v in corrections.values())
    return jsonify({'success': True, 'corrections': corrections, 'entry_count': entry_count})


@app.route('/api/ocr-validate/corrections', methods=['POST'])
@require_admin
def api_ocr_validate_corrections_post():
    """補正辞書にエントリを追加/削除する。"""
    data = request.get_json(force=True)
    action = data.get('action')
    category = data.get('category')
    key = data.get('key')

    valid_categories = {'link_ability_names', 'pilot_skill_names', 'ms_ability_names', 'link_effects'}
    if category not in valid_categories:
        return jsonify({'success': False, 'error': f'不正なカテゴリ: {category}'}), 400

    corrections = ocr_test.load_corrections()

    if action == 'add':
        value = data.get('value')
        if not key or not value:
            return jsonify({'success': False, 'error': 'key と value は必須です'}), 400
        corrections[category][key] = value
    elif action == 'remove':
        if not key:
            return jsonify({'success': False, 'error': 'key は必須です'}), 400
        corrections[category].pop(key, None)
    else:
        return jsonify({'success': False, 'error': f'不正なアクション: {action}'}), 400

    # 書き込み
    with open(ocr_test.CORRECTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(corrections, f, ensure_ascii=False, indent=2)

    entry_count = sum(len(v) for v in corrections.values())
    return jsonify({'success': True, 'corrections': corrections, 'entry_count': entry_count})


@app.route('/api/ocr-validate/fix', methods=['POST'])
@require_admin
def api_ocr_validate_fix():
    """補正辞書に基づく自動修正を適用する。"""
    data = request.get_json(force=True)
    dry_run = data.get('dry_run', True)
    series = data.get('series', '').strip() or None

    corrections = ocr_test.load_corrections()
    entry_count = sum(len(v) for v in corrections.values())
    if entry_count == 0:
        return jsonify({'success': True, 'dry_run': dry_run, 'changes': [], 'total_files': 0, 'total_changes': 0, 'message': '補正辞書が空です'})

    cards = ocr_test.load_basic_files(ocr_test.RESULTS_DIR, series_filter=series)
    if not cards:
        return jsonify({'success': True, 'dry_run': dry_run, 'changes': [], 'total_files': 0, 'total_changes': 0, 'message': '対象ファイルなし'})

    all_changes = ocr_test.apply_corrections(cards, corrections, dry_run=dry_run)

    # 実適用時はファイルが書き換わるのでキャッシュを無効化
    if not dry_run:
        _invalidate_validate_cache()

    changes_list = []
    for basename, fpath, file_changes in all_changes:
        changes_list.append({'file': basename, 'changes': file_changes})

    total_change_count = sum(len(c) for _, _, c in all_changes)

    return jsonify({
        'success': True,
        'dry_run': dry_run,
        'changes': changes_list,
        'total_files': len(all_changes),
        'total_changes': total_change_count,
    })


# --- 起動時キャッシュ事前構築 ---
# gunicorn --preload やローカル実行時に、最初のリクエスト前にインデックスを構築する
def _warmup_cache():
    """起動時にカードインデックスを構築して初回リクエストのブロックを回避する"""
    import time as _t
    _start = _t.time()
    try:
        get_card_index()
        elapsed = _t.time() - _start
        count = len(_card_index_cache) if _card_index_cache else 0
        print(f"[WARMUP] カードインデックス構築完了: {count}枚 ({elapsed:.1f}秒)")
    except Exception as e:
        print(f"[WARMUP] キャッシュ構築エラー（リクエスト時にリトライします）: {e}")

_warmup_cache()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host='0.0.0.0', port=port, threaded=True)