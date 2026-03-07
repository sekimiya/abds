"""
OCR管理アプリ（デッキシミュレーターとは別プロセスで実行）
Usage: python ocr_app.py
Port: 5002 (環境変数 OCR_PORT で変更可能)
"""
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect
import os
import re
import json
import threading
import time
import logging

from dotenv import load_dotenv
load_dotenv()

from fetch_series_ids import fetch_all_series_ids
from fetch_cards import fetch_cards_for_series, save_card_data

from card_ocr_cc import (
    load_unique_cards as ocr_load_unique_cards,
    process_card as ocr_process_card,
    get_existing_raw_numbers,
    get_existing_ocr_numbers,
)
import card_ocr_cc
import ocr_test

app = Flask(__name__)


def _card_series(card_number):
    """カード番号からシリーズコードを返す（PRは100枚ごとに分割）"""
    if card_number.startswith('PR-'):
        m = re.search(r'PR-(\d+)', card_number)
        if m:
            pr_num = int(m.group(1))
            g = (pr_num - 1) // 100
            return f'PR-{g*100+1:03d}~{(g+1)*100}'
    m = re.match(r'([A-Z]{2,3}\d{0,2})', card_number)
    return m.group(1) if m else ''


# ====================================================
# カードインデックスキャッシュ（app.py と同じロジック）
# ====================================================
_card_index_cache = None
_card_detail_cache = {}
_link_index_cache = None
_card_cache_lock = threading.Lock()


def _build_card_index():
    """全カードデータのインデックスを構築する（OCR管理に必要な最小限）"""
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

    index_list = []
    detail_cache = {}
    for card in all_cards:
        number = card.get('number', '')
        if not number:
            continue
        series = _card_series(number)
        front_url = card.get('front', {}).get('image_url', '')
        back_url = card.get('back', {}).get('image_url', '')
        name = card.get('name', '')
        card_type = card.get('type', '')

        entry = {
            'number': number,
            'name': name,
            'series': series,
            'type': card_type,
            'front_url': front_url,
            'back_url': back_url,
            'has_back_image': bool(back_url),
        }
        index_list.append(entry)
        detail_cache[number] = card

    index_list.sort(key=lambda x: x['number'])
    _card_index_cache = index_list
    _card_detail_cache = detail_cache


def get_card_index():
    global _card_index_cache
    if _card_index_cache is None:
        with _card_cache_lock:
            if _card_index_cache is None:
                _build_card_index()
    return _card_index_cache


def get_card_detail(number):
    global _card_detail_cache
    if not _card_detail_cache:
        get_card_index()
    return _card_detail_cache.get(number)


# ====================================================
# OCRファイルマップキャッシュ
# ====================================================
_ocr_file_map_cache = None
_ocr_file_map_lock = threading.Lock()


def _build_ocr_file_map():
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
    # _pバリアントはベース番号のOCRがあれば処理済みとみなす
    all_cards_dir = 'all_cards_list'
    if file_map and os.path.exists(all_cards_dir):
        import glob as _glob
        for json_path in _glob.glob(os.path.join(all_cards_dir, '*_p[0-9]*.json')):
            fn = os.path.basename(json_path)
            m = re.search(r'([A-Z0-9\-]+-[A-Z]?\d+_p\d+)', fn)
            if m:
                p_num = m.group(1)
                base_num = re.sub(r'_p\d+$', '', p_num)
                if base_num in file_map and file_map[base_num].get('basic') and p_num not in file_map:
                    file_map[p_num] = {
                        'raw': file_map[base_num]['raw'],
                        'basic': True,
                        'sp': file_map[base_num]['sp'],
                        'sq': file_map[base_num]['sq'],
                    }
    _ocr_file_map_cache = file_map
    return file_map


def _get_ocr_file_map():
    global _ocr_file_map_cache
    if _ocr_file_map_cache is None:
        with _ocr_file_map_lock:
            if _ocr_file_map_cache is None:
                _build_ocr_file_map()
    return _ocr_file_map_cache


_needs_reocr_cache = None
_needs_reocr_lock = threading.Lock()

_PL_VALID_CATS = {'殲滅', '制圧', '防衛'}
_MS_VALID_CATS = {'機動', '近距離', '遠距離'}


def _build_needs_reocr_set():
    """OCR済みカードのうちデータ品質に問題があるカード番号のセットを構築"""
    global _needs_reocr_cache
    ocr_dir = 'ocr_results_debug'
    result = set()
    if not os.path.exists(ocr_dir):
        _needs_reocr_cache = result
        return result
    number_pattern = re.compile(r'([A-Z0-9\-]{2,}-\d{2,4})(?:_p\d+)?')
    for fn in os.listdir(ocr_dir):
        if not fn.endswith('_basic.json'):
            continue
        m = number_pattern.search(fn)
        if not m:
            continue
        card_number = m.group(1)
        try:
            fpath = os.path.join(ocr_dir, fn)
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ocr = data.get('ocr_data', {})
            if not ocr:
                continue
            ctype = ocr.get('type', '')
            category = ocr.get('category', '')
            cost = ocr.get('cost')
            terrain = ocr.get('terrain_compatibility') or {}
            needs = False
            if ctype == 'PL' and category not in _PL_VALID_CATS:
                needs = True
            if ctype == 'MS' and category not in _MS_VALID_CATS:
                needs = True
            if cost is None:
                needs = True
            if ctype == 'MS' and terrain and all(v == '' or v is None for v in terrain.values()):
                needs = True
            if needs:
                result.add(card_number)
        except Exception:
            continue
    _needs_reocr_cache = result
    return result


def _get_needs_reocr_set():
    global _needs_reocr_cache
    if _needs_reocr_cache is None:
        with _needs_reocr_lock:
            if _needs_reocr_cache is None:
                _build_needs_reocr_set()
    return _needs_reocr_cache


def _get_no_ocr_numbers():
    """OCR未実施（basic結果なし）のカード番号セットを返す"""
    ocr_map = _get_ocr_file_map()
    idx = get_card_index()
    result = set()
    for c in idx:
        num = c['number']
        if num not in ocr_map or not ocr_map[num].get('basic'):
            result.add(num)
    return result


def _get_failed_numbers():
    progress_file = 'ocr_cc_progress.json'
    if not os.path.exists(progress_file):
        return set()
    try:
        with open(progress_file, 'r', encoding='utf-8') as f:
            pdata = json.load(f)
        failed_raw = pdata.get('failed', [])
        normalized = set()
        for item in failed_raw:
            clean = re.sub(r'_p\d+$', '', item)
            if clean:
                normalized.add(clean)
        return normalized
    except Exception:
        return set()


def _is_safe_filename(filename):
    return '..' not in filename and not filename.startswith('/')


# ====================================================
# バックグラウンド収集タスク
# ====================================================
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


def _run_collection():
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

        os.makedirs('series_data', exist_ok=True)
        with open('series_data/series_list.json', 'w', encoding='utf-8') as f:
            json.dump(series_list, f, ensure_ascii=False, indent=2)

        with _collect_lock:
            _collect_status["total_series"] = len(series_list)
            _collect_status["log"].append(f"{len(series_list)}個のシリーズを取得しました")

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

            if i < len(series_list) - 1:
                time.sleep(1)

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


# ====================================================
# OCR実行タスク
# ====================================================
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
    def emit(self, record):
        msg = self.format(record)
        with _ocr_run_lock:
            _ocr_run_status["log"].append(msg)
            if len(_ocr_run_status["log"]) > 200:
                _ocr_run_status["log"] = _ocr_run_status["log"][-200:]


def _run_ocr_execution(series, stage, force, limit):
    global _ocr_file_map_cache, _card_index_cache, _card_detail_cache, _link_index_cache

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
        targets = [c for c in all_cards if _card_series(c["card_number"]) == series]

        if not force:
            existing_raw = get_existing_raw_numbers()
            existing_basic = get_existing_ocr_numbers()
            if stage == "structure":
                targets = [c for c in targets
                           if c["card_number"] in existing_raw
                           and c["card_number"] not in existing_basic]
            elif stage == "raw":
                targets = [c for c in targets if c["card_number"] not in existing_raw]
            else:
                targets = [c for c in targets if c["card_number"] not in existing_basic]

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

        with _ocr_run_lock:
            _ocr_run_status["log"].append("キャッシュをクリア中...")

        with _card_cache_lock:
            _card_index_cache = None
            _card_detail_cache = {}
            _link_index_cache = None
        with _ocr_file_map_lock:
            _ocr_file_map_cache = None
        with _needs_reocr_lock:
            _needs_reocr_cache = None

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
# ルート定義（認証なし）
# ====================================================

@app.route('/')
def index():
    return redirect('/admin')


@app.route('/admin')
def admin():
    return render_template('admin.html')


@app.route('/api/admin/stats')
def api_admin_stats():
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
            card_num = fn.replace('.json', '')
            series_set.add(_card_series(card_num))
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


@app.route('/api/admin/collect', methods=['POST'])
def api_admin_collect():
    with _collect_lock:
        if _collect_status["running"]:
            return jsonify({'success': False, 'error': '収集タスクが既に実行中です'}), 409

    t = threading.Thread(target=_run_collection, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': '収集を開始しました'})


@app.route('/api/admin/collect/status')
def api_admin_collect_status():
    with _collect_lock:
        return jsonify({
            'success': True,
            'running': _collect_status["running"],
            'current_series': _collect_status["current_series"],
            'series_index': _collect_status["series_index"],
            'total_series': _collect_status["total_series"],
            'collected_cards': _collect_status["collected_cards"],
            'errors': list(_collect_status["errors"]),
            'log': list(_collect_status["log"][-50:]),
            'started_at': _collect_status["started_at"],
            'finished_at': _collect_status["finished_at"],
        })


@app.route('/api/admin/cards')
def api_admin_cards():
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


@app.route('/api/cache/clear', methods=['POST'])
def api_clear_cache():
    global _card_index_cache, _card_detail_cache, _link_index_cache, _ocr_file_map_cache
    with _card_cache_lock:
        _card_index_cache = None
        _card_detail_cache = {}
        _link_index_cache = None
    with _ocr_file_map_lock:
        _ocr_file_map_cache = None
    with _needs_reocr_lock:
        _needs_reocr_cache = None
    get_card_index()
    return jsonify({'success': True, 'message': 'キャッシュを再構築しました'})


# --- OCR管理 ---

@app.route('/ocr-admin')
def ocr_admin():
    return redirect('/admin')


@app.route('/api/ocr-admin/stats')
def api_ocr_admin_stats():
    ocr_map = _get_ocr_file_map()
    failed_numbers = _get_failed_numbers()

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
            card_num = fn.replace('.json', '')
            s = _card_series(card_num)
            if s:
                series_total[s] = series_total.get(s, 0) + 1
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

    image_no_ocr = len(back_image_numbers - set(ocr_map.keys()))
    failed_count = len(failed_numbers & all_card_numbers)

    series_ocr = {}
    for number, info in ocr_map.items():
        s = _card_series(number)
        if s and info['basic']:
            series_ocr[s] = series_ocr.get(s, 0) + 1

    series_failed = {}
    for num in (failed_numbers & all_card_numbers):
        s = _card_series(num)
        if s:
            series_failed[s] = series_failed.get(s, 0) + 1

    series_coverage = []
    for s in sorted(series_total.keys()):
        t = series_total[s]
        o = series_ocr.get(s, 0)
        series_coverage.append({
            'series': s,
            'total': t,
            'raw': sum(1 for num, info in ocr_map.items() if _card_series(num) == s and (info['raw'] or info['basic'])),
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
def api_ocr_admin_cards():
    ocr_map = _get_ocr_file_map()
    idx = get_card_index()
    failed_numbers = _get_failed_numbers()
    reocr_numbers = _get_needs_reocr_set()

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
        elif status_filter == 'needs_reocr':
            results = [c for c in results if c['number'] in reocr_numbers]

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
            'needs_reocr': c['number'] in reocr_numbers,
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
def api_ocr_admin_card_detail(number):
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


# --- OCR実行管理 ---

@app.route('/ocr-run')
def ocr_run():
    return render_template('ocr_run.html')


@app.route('/api/ocr-run/series-stats')
def api_ocr_run_series_stats():
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
        s = _card_series(num)
        if s:
            series_raw[s] = series_raw.get(s, 0) + 1

    series_basic = {}
    for num in existing_basic:
        s = _card_series(num)
        if s:
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
    no_ocr_numbers = _get_no_ocr_numbers()
    total_no_ocr = len(no_ocr_numbers)

    return jsonify({
        'success': True,
        'total_cards': total_cards,
        'total_raw': total_raw,
        'total_basic': total_basic,
        'total_no_ocr': total_no_ocr,
        'series': series_list,
    })


@app.route('/api/ocr-run/start', methods=['POST'])
def api_ocr_run_start():
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


@app.route('/api/ocr-run/start-single', methods=['POST'])
def api_ocr_run_start_single():
    with _ocr_run_lock:
        if _ocr_run_status["running"]:
            return jsonify({'success': False, 'error': 'OCRタスクが既に実行中です'}), 409

    data = request.get_json() or {}
    number = data.get('number', '').strip()
    if not number:
        return jsonify({'success': False, 'error': 'カード番号を指定してください'}), 400

    t = threading.Thread(
        target=_run_reocr_execution,
        args=({number},),
        daemon=True,
    )
    t.start()
    return jsonify({'success': True, 'message': f'{number} のOCR再実行を開始しました'})


@app.route('/api/ocr-run/start-reocr', methods=['POST'])
def api_ocr_run_start_reocr():
    with _ocr_run_lock:
        if _ocr_run_status["running"]:
            return jsonify({'success': False, 'error': 'OCRタスクが既に実行中です'}), 409

    reocr_numbers = _get_needs_reocr_set()
    if not reocr_numbers:
        return jsonify({'success': False, 'error': '要再OCRカードがありません'}), 400

    t = threading.Thread(
        target=_run_reocr_execution,
        args=(reocr_numbers,),
        daemon=True,
    )
    t.start()
    return jsonify({'success': True, 'message': f'要再OCR {len(reocr_numbers)}件 のOCR実行を開始しました'})


@app.route('/api/ocr-run/start-no-ocr', methods=['POST'])
def api_ocr_run_start_no_ocr():
    with _ocr_run_lock:
        if _ocr_run_status["running"]:
            return jsonify({'success': False, 'error': 'OCRタスクが既に実行中です'}), 409

    no_ocr_numbers = _get_no_ocr_numbers()
    if not no_ocr_numbers:
        return jsonify({'success': False, 'error': 'OCR未実施カードがありません'}), 400

    t = threading.Thread(
        target=_run_reocr_execution,
        args=(no_ocr_numbers,),
        kwargs={'label': 'OCR未実施'},
        daemon=True,
    )
    t.start()
    return jsonify({'success': True, 'message': f'OCR未実施 {len(no_ocr_numbers)}件 のOCR実行を開始しました'})


def _run_reocr_execution(reocr_numbers, label='要再OCR'):
    """指定カード番号セットを対象にOCR再実行する"""
    global _ocr_file_map_cache, _card_index_cache, _card_detail_cache, _link_index_cache, _needs_reocr_cache

    log_handler = OcrRunLogHandler()
    log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    card_ocr_cc.logger.addHandler(log_handler)

    with _ocr_run_lock:
        _ocr_run_status["running"] = True
        _ocr_run_status["stop_requested"] = False
        _ocr_run_status["series"] = label
        _ocr_run_status["stage"] = "both"
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
            _ocr_run_status["log"].append(f"{label}カードを読み込み中... ({len(reocr_numbers)}件)")

        all_cards = ocr_load_unique_cards()
        targets = [c for c in all_cards if c["card_number"] in reocr_numbers and c.get("back_url")]

        total = len(targets)
        with _ocr_run_lock:
            _ocr_run_status["total_target"] = total
            _ocr_run_status["log"].append(f"処理対象: {total} 件 (force=True, stage=both)")

        if total == 0:
            with _ocr_run_lock:
                _ocr_run_status["log"].append("処理対象カードがありません。")
            return

        done_count = 0
        fatal = False
        for card in targets:
            with _ocr_run_lock:
                if _ocr_run_status["stop_requested"]:
                    _ocr_run_status["log"].append("停止リクエストにより処理を中断しました。")
                    break

            card_number = card["card_number"]
            card_name = card["card_name"]
            try:
                ok = ocr_process_card(card, model=None, force=True, stage='both')
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

        with _ocr_run_lock:
            _ocr_run_status["log"].append("キャッシュをクリア中...")

        with _card_cache_lock:
            _card_index_cache = None
            _card_detail_cache = {}
            _link_index_cache = None
        with _ocr_file_map_lock:
            _ocr_file_map_cache = None
        with _needs_reocr_lock:
            _needs_reocr_cache = None

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
            elapsed = time.time() - start_time
            _ocr_run_status["elapsed_seconds"] = int(elapsed)


@app.route('/api/ocr-run/status')
def api_ocr_run_status():
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
def api_ocr_run_stop():
    with _ocr_run_lock:
        if not _ocr_run_status["running"]:
            return jsonify({'success': False, 'error': '実行中のタスクがありません'}), 400
        _ocr_run_status["stop_requested"] = True
        _ocr_run_status["log"].append("停止リクエストを受信しました。現在のカード処理完了後に停止します。")
    return jsonify({'success': True, 'message': '停止をリクエストしました'})


# ====================================================
# デプロイ（git commit & push → GitHub Actions が gh-pages 更新）
# ====================================================
_deploy_status = {
    "running": False,
    "log": [],
    "success": None,
    "started_at": None,
    "finished_at": None,
}
_deploy_lock = threading.Lock()


@app.route('/api/deploy/start', methods=['POST'])
def api_deploy_start():
    with _deploy_lock:
        if _deploy_status["running"]:
            return jsonify({'success': False, 'error': 'デプロイが既に実行中です'}), 409

    with _ocr_run_lock:
        if _ocr_run_status["running"]:
            return jsonify({'success': False, 'error': 'OCRタスク実行中はデプロイできません'}), 409

    t = threading.Thread(target=_run_deploy, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'デプロイを開始しました'})


@app.route('/api/deploy/status')
def api_deploy_status():
    with _deploy_lock:
        return jsonify({
            'success': True,
            'running': _deploy_status["running"],
            'log': list(_deploy_status["log"]),
            'deploy_success': _deploy_status["success"],
            'started_at': _deploy_status["started_at"],
            'finished_at': _deploy_status["finished_at"],
        })


def _run_deploy():
    import subprocess

    with _deploy_lock:
        _deploy_status["running"] = True
        _deploy_status["log"] = []
        _deploy_status["success"] = None
        _deploy_status["started_at"] = time.strftime('%Y-%m-%dT%H:%M:%S')
        _deploy_status["finished_at"] = None

    def log(msg):
        with _deploy_lock:
            _deploy_status["log"].append(msg)

    def run_cmd(cmd, cwd=None):
        log(f"$ {cmd}")
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=120,
        )
        if result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                log(f"  {line}")
        if result.returncode != 0 and result.stderr.strip():
            for line in result.stderr.strip().split('\n'):
                log(f"  [ERR] {line}")
        return result

    project_root = os.path.dirname(os.path.abspath(__file__))

    try:
        # 1. 変更チェック
        log("=== 変更チェック ===")
        r = run_cmd("git status --porcelain all_cards_list/ ocr_results_debug/", cwd=project_root)
        changed_files = [l for l in r.stdout.strip().split('\n') if l.strip()]
        if not changed_files:
            log("変更なし — デプロイ不要")
            with _deploy_lock:
                _deploy_status["success"] = True
            return

        log(f"変更ファイル数: {len(changed_files)}")

        # 2. git add & commit
        log("=== コミット ===")
        run_cmd("git add all_cards_list/ ocr_results_debug/", cwd=project_root)

        # 変更統計を取得
        r = run_cmd("git diff --cached --stat | tail -1", cwd=project_root)
        stat_summary = r.stdout.strip() or f"{len(changed_files)} files changed"

        commit_msg = f"data: OCR結果更新 ({stat_summary})"
        r = run_cmd(f'git commit -m "{commit_msg}"', cwd=project_root)
        if r.returncode != 0:
            log("コミット失敗（変更なし？）")
            with _deploy_lock:
                _deploy_status["success"] = True
            return

        # 3. git push
        log("=== Push ===")
        r = run_cmd("git push origin main", cwd=project_root)
        if r.returncode != 0:
            log("Push失敗!")
            with _deploy_lock:
                _deploy_status["success"] = False
            return

        log("Push完了 — GitHub Actions が gh-pages を自動更新します")
        with _deploy_lock:
            _deploy_status["success"] = True

    except subprocess.TimeoutExpired:
        log("タイムアウト!")
        with _deploy_lock:
            _deploy_status["success"] = False
    except Exception as e:
        log(f"エラー: {str(e)}")
        with _deploy_lock:
            _deploy_status["success"] = False
    finally:
        with _deploy_lock:
            _deploy_status["running"] = False
            _deploy_status["finished_at"] = time.strftime('%Y-%m-%dT%H:%M:%S')


@app.route('/ocr_results/<path:filename>')
def serve_ocr_results(filename):
    if not _is_safe_filename(filename):
        return jsonify({'error': 'Invalid filename'}), 400
    return send_from_directory('ocr_results', filename)


# --- OCR バリデーション＆補正 ---

_validate_cards_cache = None
_validate_cards_cache_lock = threading.Lock()
_card_number_re = re.compile(r'([A-Z]{2,4}\d{1,2}-\d{2,4})')


def _validate_fingerprint():
    ocr_dir = ocr_test.RESULTS_DIR
    count = 0
    mtime_sum = 0.0
    try:
        for fn in os.listdir(ocr_dir):
            if fn.endswith('_basic.json'):
                count += 1
                mtime_sum += os.path.getmtime(os.path.join(ocr_dir, fn))
    except OSError:
        pass
    return (count, mtime_sum)


def _get_validate_cards(series_filter=None):
    global _validate_cards_cache
    fp = _validate_fingerprint()
    if _validate_cards_cache is None or _validate_cards_cache['fingerprint'] != fp:
        with _validate_cards_cache_lock:
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
def ocr_validate():
    return render_template('ocr_validate.html')


@app.route('/api/ocr-validate/report')
def api_ocr_validate_report():
    checks_param = request.args.get('checks', '')
    series = request.args.get('series', '').strip() or None
    if checks_param:
        check_keys = [c.strip() for c in checks_param.split(',') if c.strip()]
    else:
        check_keys = list(ocr_test.CHECK_FUNCTIONS.keys())
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
        enriched = []
        for r in raw_results:
            item = dict(r)
            if item['level'] == 'WARNING' and item.get('detail', '').startswith('類似候補:'):
                detail = item['detail']
                m = re.search(r'類似候補:\s*"(.+?)"', detail)
                if m:
                    suggested_value = m.group(1)
                    msg = item['message']
                    m2 = re.search(r'"(.+?)"', msg)
                    if m2:
                        wrong_name = m2.group(1)
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
def api_ocr_validate_corrections_get():
    corrections = ocr_test.load_corrections()
    entry_count = sum(len(v) for v in corrections.values())
    return jsonify({'success': True, 'corrections': corrections, 'entry_count': entry_count})


@app.route('/api/ocr-validate/corrections', methods=['POST'])
def api_ocr_validate_corrections_post():
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
    with open(ocr_test.CORRECTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(corrections, f, ensure_ascii=False, indent=2)
    entry_count = sum(len(v) for v in corrections.values())
    return jsonify({'success': True, 'corrections': corrections, 'entry_count': entry_count})


@app.route('/api/ocr-validate/auto-correct')
def api_ocr_validate_auto_correct_get():
    """公式マスターデータとOCRデータを照合し、自動補正候補を生成する（dry_run的）。"""
    series = request.args.get('series', '').strip() or None
    force_refresh = request.args.get('force_refresh', '0') == '1'
    max_distance = request.args.get('max_distance', 2, type=int)

    try:
        master_data = ocr_test.fetch_official_master_data(force_refresh=force_refresh)
    except Exception as e:
        return jsonify({'success': False, 'error': f'マスターデータ取得失敗: {str(e)}'}), 500

    # マスターデータでABILITY_DATAを更新
    ocr_test.update_ability_data_from_master(master_data)

    cards = _get_validate_cards(series_filter=series)
    if not cards:
        return jsonify({
            'success': True,
            'candidates': [],
            'master_stats': {
                'ms_abilities': len(master_data.get('ms_abilities', [])),
                'link_names': len(master_data.get('link_names', [])),
            },
        })

    candidates = ocr_test.auto_generate_corrections(cards, master_data=master_data, max_distance=max_distance)

    return jsonify({
        'success': True,
        'candidates': candidates,
        'master_stats': {
            'ms_abilities': len(master_data.get('ms_abilities', [])),
            'link_names': len(master_data.get('link_names', [])),
            'fetched_at': master_data.get('fetched_at', ''),
        },
    })


@app.route('/api/ocr-validate/auto-correct', methods=['POST'])
def api_ocr_validate_auto_correct_post():
    """承認された自動補正候補を辞書に追加する。"""
    data = request.get_json(force=True)
    items = data.get('items', [])
    if not items:
        return jsonify({'success': False, 'error': '追加する候補がありません'}), 400

    valid_categories = {'link_ability_names', 'pilot_skill_names', 'ms_ability_names', 'link_effects'}
    corrections = ocr_test.load_corrections()
    added = 0

    for item in items:
        category = item.get('category', '')
        key = item.get('key', '')
        value = item.get('value', '')
        if category not in valid_categories or not key or not value:
            continue
        if key not in corrections[category]:
            corrections[category][key] = value
            added += 1

    with open(ocr_test.CORRECTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(corrections, f, ensure_ascii=False, indent=2)

    entry_count = sum(len(v) for v in corrections.values())
    return jsonify({
        'success': True,
        'added': added,
        'corrections': corrections,
        'entry_count': entry_count,
    })


@app.route('/api/ocr-validate/master-check')
def api_ocr_validate_master_check():
    """OCR結果を公式マスターデータと照合し、不一致をグルーピングして返す。"""
    series = request.args.get('series', '').strip() or None

    master_file = ocr_test.MASTER_DATA_FILE
    if not os.path.exists(master_file):
        return jsonify({'success': False, 'error': 'マスターデータが未取得です。先に「マスター更新」を実行してください。'}), 400

    try:
        with open(master_file, 'r', encoding='utf-8') as f:
            master_data = json.load(f)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    cards = _get_validate_cards(series_filter=series)
    if not cards:
        return jsonify({'success': True, 'groups': [], 'total_cards': 0, 'total_mismatches': 0,
                        'ms_ability_mismatches': 0, 'link_ability_mismatches': 0})

    mismatches = ocr_test.check_against_master(cards, master_data)

    # ユニーク値+カテゴリでグルーピング
    groups_map = {}
    for m in mismatches:
        key = (m['category'], m['ocr_value'])
        if key not in groups_map:
            groups_map[key] = {
                'category': m['category'],
                'ocr_value': m['ocr_value'],
                'closest_match': m['closest_match'],
                'distance': m['distance'],
                'count': 0,
                'cards': [],
            }
        groups_map[key]['count'] += 1
        groups_map[key]['cards'].append(m['card_id'])

    # 件数の多い順にソート
    groups = sorted(groups_map.values(), key=lambda g: -g['count'])

    return jsonify({
        'success': True,
        'groups': groups,
        'total_cards': len(cards),
        'total_mismatches': len(mismatches),
        'unique_mismatches': len(groups),
        'ms_ability_mismatches': sum(1 for m in mismatches if m['category'] == 'ms_ability'),
        'link_ability_mismatches': sum(1 for m in mismatches if m['category'] == 'link_ability'),
    })


@app.route('/api/ocr-validate/master-data/status')
def api_ocr_validate_master_data_status():
    """公式マスターデータの存在・内容を返す。"""
    master_file = ocr_test.MASTER_DATA_FILE
    if not os.path.exists(master_file):
        return jsonify({
            'success': True,
            'exists': False,
            'fetched_at': None,
            'ms_abilities_count': 0,
            'link_names_count': 0,
            'ability_data_count': len(ocr_test.ABILITY_DATA),
        })
    try:
        with open(master_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ms_abilities = data.get('ms_abilities', [])
        link_names = data.get('link_names', [])
        return jsonify({
            'success': True,
            'exists': True,
            'fetched_at': data.get('fetched_at'),
            'ms_abilities_count': len(ms_abilities),
            'link_names_count': len(link_names),
            'ability_data_count': len(ocr_test.ABILITY_DATA),
            'ms_abilities': ms_abilities,
            'link_names': link_names,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ocr-validate/master-data/fetch', methods=['POST'])
def api_ocr_validate_master_data_fetch():
    """公式サイトからマスターデータを再取得する。"""
    ability_data_before = len(ocr_test.ABILITY_DATA)
    try:
        master_data = ocr_test.fetch_official_master_data(force_refresh=True)
        ocr_test.update_ability_data_from_master(master_data)
        ability_data_after = len(ocr_test.ABILITY_DATA)
        return jsonify({
            'success': True,
            'fetched_at': master_data.get('fetched_at'),
            'ms_abilities_count': len(master_data.get('ms_abilities', [])),
            'link_names_count': len(master_data.get('link_names', [])),
            'ability_data_before': ability_data_before,
            'ability_data_after': ability_data_after,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'マスターデータ取得失敗: {str(e)}'}), 500


@app.route('/api/ocr-validate/fix/preview', methods=['POST'])
def api_ocr_validate_fix_preview():
    """構造化された変更候補を返す。"""
    data = request.get_json(force=True) if request.is_json else {}
    series = data.get('series', '').strip() or None

    corrections = ocr_test.load_corrections()
    entry_count = sum(len(v) for v in corrections.values())
    if entry_count == 0:
        return jsonify({'success': True, 'items': [], 'total_items': 0, 'total_files': 0, 'message': '補正辞書が空です'})

    cards = ocr_test.load_basic_files(ocr_test.RESULTS_DIR, series_filter=series)
    if not cards:
        return jsonify({'success': True, 'items': [], 'total_items': 0, 'total_files': 0, 'message': '対象ファイルなし'})

    items = ocr_test.generate_correction_preview(cards, corrections)

    # file_path はフロントに送らない
    safe_items = []
    for item in items:
        safe_items.append({
            'id': item['id'],
            'file': item['file'],
            'field': item['field'],
            'source': item['source'],
            'old_value': item['old_value'],
            'new_value': item['new_value'],
            'context': item['context'],
        })

    file_set = set(item['file'] for item in items)

    return jsonify({
        'success': True,
        'items': safe_items,
        'total_items': len(items),
        'total_files': len(file_set),
    })


@app.route('/api/ocr-validate/fix/apply', methods=['POST'])
def api_ocr_validate_fix_apply():
    """ユーザーの決定に基づき選択的にファイルを修正する。"""
    data = request.get_json(force=True)
    series = data.get('series', '').strip() or None
    user_items = data.get('items', [])

    if not user_items:
        return jsonify({'success': False, 'error': '適用するアイテムがありません'}), 400

    # 内部でpreview再生成→IDでマッチ（セキュリティ: file_pathはフロントに送らない）
    corrections = ocr_test.load_corrections()
    cards = ocr_test.load_basic_files(ocr_test.RESULTS_DIR, series_filter=series)
    if not cards:
        return jsonify({'success': False, 'error': '対象ファイルなし'}), 400

    preview_items = ocr_test.generate_correction_preview(cards, corrections)
    preview_by_id = {item['id']: item for item in preview_items}

    # ユーザーの決定を処理
    to_apply = []
    skipped = 0
    edited = 0

    for user_item in user_items:
        item_id = user_item.get('id')
        action = user_item.get('action', 'skip')

        if action == 'skip':
            skipped += 1
            continue

        preview = preview_by_id.get(item_id)
        if preview is None:
            continue

        if action == 'edit':
            new_value = user_item.get('new_value')
            if new_value is None:
                skipped += 1
                continue
            apply_item = dict(preview)
            apply_item['new_value'] = new_value
            to_apply.append(apply_item)
            edited += 1
        elif action == 'accept':
            to_apply.append(preview)

    if not to_apply:
        return jsonify({
            'success': True,
            'applied': 0,
            'skipped': skipped,
            'edited': edited,
            'files_modified': 0,
            'errors': [],
        })

    result = ocr_test.apply_selective_corrections(to_apply)
    _invalidate_validate_cache()

    return jsonify({
        'success': True,
        'applied': result['applied'],
        'skipped': skipped,
        'edited': edited,
        'files_modified': result['files_modified'],
        'errors': result['errors'],
    })


@app.route('/api/ocr-validate/direct-fix', methods=['POST'])
def api_ocr_validate_direct_fix():
    """OCRファイルを直接修正する（バックアップ付き）。

    リクエスト形式:
    { "fixes": [
        {"category": "ms_ability_names", "key": "断砕【広角】", "value": "断砕[広角]"}
    ]}
    """
    data = request.get_json(force=True)
    fixes = data.get('fixes', [])
    series = data.get('series', '').strip() or None
    if not fixes:
        return jsonify({'success': False, 'error': '修正対象がありません'}), 400

    # 修正マップを構築
    fix_map = {}  # category -> {key: value}
    for fix in fixes:
        cat = fix.get('category', '')
        key = fix.get('key', '')
        val = fix.get('value', '')
        if cat and key and val:
            fix_map.setdefault(cat, {})[key] = val

    cards = ocr_test.load_basic_files(ocr_test.RESULTS_DIR, series_filter=series)
    if not cards:
        return jsonify({'success': False, 'error': '対象ファイルなし'}), 400

    applied_count = 0
    modified_files = []

    for basename, fpath, ocr in cards:
        changes = []

        # MSアビリティ名の修正
        ms_map = fix_map.get('ms_ability_names', {})
        if ms_map and ocr.get('type') == 'MS':
            ms_ab = ocr.get('ms_ability')
            if ms_ab and ms_ab.get('name', '') in ms_map:
                old = ms_ab['name']
                new = ms_map[old]
                ms_ab['name'] = new
                changes.append(f'ms_ability.name: "{old}" → "{new}"')

        # リンクアビリティ名の修正
        link_map = fix_map.get('link_ability_names', {})
        if link_map:
            for link in ocr_test.get_link_abilities(ocr):
                name = link.get('name', '')
                if name in link_map:
                    old = name
                    new = link_map[old]
                    link['name'] = new
                    changes.append(f'link_ability.name: "{old}" → "{new}"')

        # パイロットスキル名の修正
        ps_map = fix_map.get('pilot_skill_names', {})
        if ps_map and ocr.get('type') == 'PL':
            ps = ocr.get('pilot_skill') or ocr.get('pl_skill')
            if ps and ps.get('name', '') in ps_map:
                old = ps['name']
                new = ps_map[old]
                ps['name'] = new
                changes.append(f'pilot_skill.name: "{old}" → "{new}"')

        if changes:
            # バックアップ作成
            back_path = fpath + '.back'
            if not os.path.exists(back_path):
                import shutil
                shutil.copy2(fpath, back_path)

            # ファイルに書き戻し（修正フラグ付き）
            with open(fpath, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            raw['ocr_data'] = ocr
            if '_fix_history' not in raw:
                raw['_fix_history'] = []
            raw['_fix_history'].append({
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'changes': changes,
            })
            raw['_fixed'] = True
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)

            applied_count += len(changes)
            modified_files.append({'file': basename, 'changes': changes})

    if modified_files:
        _invalidate_validate_cache()

    return jsonify({
        'success': True,
        'applied': applied_count,
        'files_modified': len(modified_files),
        'details': modified_files,
    })


@app.route('/api/ocr-validate/fix', methods=['POST'])
def api_ocr_validate_fix():
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


# ============================================================
# OCR品質チェック
# ============================================================

_CARD_DETAILS_PATH = os.path.join('data', 'card_details.json')

# 標準 ms_ability フィールド名
_MS_ABILITY_STANDARD_FIELDS = {'name', 'activation', 'target', 'range', 'cost', 'description', 'type'}

# 公式カテゴリ → カードタイプ対応表（マスターデータ基準）
_MS_CATEGORIES = {'近距離', '遠距離', '機動'}
_PL_CATEGORIES = {'殲滅', '制圧', '防衛'}


def _load_card_details():
    """data/card_details.json をロードして dict を返す"""
    if not os.path.exists(_CARD_DETAILS_PATH):
        return {}
    with open(_CARD_DETAILS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_card_details(data):
    """data/card_details.json を書き出す"""
    with open(_CARD_DETAILS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_official_master():
    """official_master_data.json をロードする（なければ空dict）"""
    master_file = getattr(ocr_test, 'MASTER_DATA_FILE', 'official_master_data.json')
    if os.path.exists(master_file):
        with open(master_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def run_quality_checks():
    """card_details.json を走査し品質問題を検出する。

    公式サイトから収集したデータ（トップレベルの name, category, series 等）を
    マスター（正）とし、OCRデータ（ocr_data 内）を検証対象として比較する。
    """
    all_cards = _load_card_details()

    # 公式マスターデータ（MSアビリティ名・リンク名の正式一覧）
    master = _load_official_master()
    official_ms_abilities = set(master.get('ms_abilities', []))
    official_link_names = set(master.get('link_names', []))
    problem_cards = []
    by_severity = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    rule_counts = {}  # rule_id -> count

    for number, card in all_cards.items():
        ocr = card.get('ocr_data')
        if not ocr:
            continue  # OCR未実行カードはスキップ

        # --- マスター（公式）データ ---
        official_name = card.get('name', '')
        official_category = card.get('category', '')  # 近距離/遠距離/機動/殲滅/制圧/防衛

        # 公式カテゴリからカードタイプを判定（マスター基準）
        if official_category in _MS_CATEGORIES:
            master_type = 'MS'
        elif official_category in _PL_CATEGORIES:
            master_type = 'PL'
        else:
            # 公式カテゴリが不明な場合のみ OCR type にフォールバック
            master_type = ocr.get('type', '')

        # --- OCR データ ---
        ocr_type = ocr.get('type', '')
        ocr_category = ocr.get('category', '')
        ocr_class = (ocr.get('card_label') or {}).get('class', '')
        ms_ab = ocr.get('ms_ability')

        issues = []

        # ============================================================
        # CRITICAL
        # ============================================================

        # Rule 1: 全ステータスゼロ
        stats = ocr.get('stats') or {}
        numeric_stats = [v for k, v in stats.items()
                         if k in ('mobility', 'ranged_attack', 'melee_attack', 'hp')
                         and isinstance(v, (int, float))]
        if numeric_stats and all(v == 0 for v in numeric_stats):
            issues.append({'rule_id': 1, 'severity': 'CRITICAL',
                           'message': '全ステータスがゼロ'})

        # Rule 2: リンクアビリティ数 != 2
        la = ocr.get('link_ability') or ocr.get('link_abilities') or []
        if not isinstance(la, list):
            la = []
        if len(la) != 2:
            issues.append({'rule_id': 2, 'severity': 'CRITICAL',
                           'message': f'リンクアビリティ数が{len(la)}（期待値: 2）'})

        # Rule 3: MS で ms_ability 欠落（公式カテゴリ基準でMS判定）
        if master_type == 'MS' and not ms_ab:
            issues.append({'rule_id': 3, 'severity': 'CRITICAL',
                           'message': f'MS: ms_ability欠落（公式: {official_category}）'})

        # Rule 4: ms_ability 内の非標準フィールド名
        if isinstance(ms_ab, dict):
            non_std = set(ms_ab.keys()) - _MS_ABILITY_STANDARD_FIELDS
            if non_std:
                issues.append({'rule_id': 4, 'severity': 'CRITICAL',
                               'message': f'ms_ability非標準フィールド: {", ".join(sorted(non_std))}'})

        # ============================================================
        # HIGH — 公式データとOCRの不一致
        # ============================================================

        # Rule 5: OCR type が公式カテゴリと矛盾
        #   例: 公式=殲滅(PL) なのに OCR type=MS
        if official_category:
            if official_category in _MS_CATEGORIES and ocr_type and ocr_type != 'MS':
                issues.append({'rule_id': 5, 'severity': 'HIGH',
                               'message': f'OCR type "{ocr_type}" != 公式カテゴリ "{official_category}" (MS)',
                               'fix': {'field': 'type', 'current': ocr_type, 'correct': 'MS'}})
            elif official_category in _PL_CATEGORIES and ocr_type and ocr_type != 'PL':
                issues.append({'rule_id': 5, 'severity': 'HIGH',
                               'message': f'OCR type "{ocr_type}" != 公式カテゴリ "{official_category}" (PL)',
                               'fix': {'field': 'type', 'current': ocr_type, 'correct': 'PL'}})

        # Rule 6: 公式 category vs OCR category / card_label.class 不一致
        if official_category:
            if ocr_category and ocr_category != official_category:
                issues.append({'rule_id': 6, 'severity': 'HIGH',
                               'message': f'OCR category "{ocr_category}" != 公式 "{official_category}"',
                               'fix': {'field': 'category', 'current': ocr_category, 'correct': official_category}})
            if ocr_class and ocr_class != official_category:
                issues.append({'rule_id': 6, 'severity': 'HIGH',
                               'message': f'OCR card_label.class "{ocr_class}" != 公式 "{official_category}"',
                               'fix': {'field': 'card_label.class', 'current': ocr_class, 'correct': official_category}})

        # Rule 7: レアリティ欠落
        if not ocr.get('rarity'):
            issues.append({'rule_id': 7, 'severity': 'HIGH',
                           'message': 'レアリティ欠落'})

        # Rule 8: MS で weapon 欠落（公式カテゴリ基準）
        if master_type == 'MS':
            weapon = ocr.get('weapon')
            if not weapon or not isinstance(weapon, dict):
                issues.append({'rule_id': 8, 'severity': 'HIGH',
                               'message': f'MS: weapon欠落（公式: {official_category}）'})

        # Rule 9: ms_ability の name/description が null
        if isinstance(ms_ab, dict):
            if not ms_ab.get('name'):
                issues.append({'rule_id': 9, 'severity': 'HIGH',
                               'message': 'ms_ability nameがnull'})
            if not ms_ab.get('description'):
                issues.append({'rule_id': 9, 'severity': 'HIGH',
                               'message': 'ms_ability descriptionがnull'})

        # ============================================================
        # MEDIUM
        # ============================================================

        # Rule 10: リンクアビリティ重複
        if len(la) >= 2:
            la_names = [x.get('name') for x in la if isinstance(x, dict) and x.get('name')]
            if len(la_names) != len(set(la_names)):
                issues.append({'rule_id': 10, 'severity': 'MEDIUM',
                               'message': 'リンクアビリティ名が重複'})

        # Rule 11: SP攻撃 sp_cost 欠落
        sp = ocr.get('special_attack')
        if isinstance(sp, dict):
            if sp.get('sp_cost') is None and sp.get('power') is not None:
                issues.append({'rule_id': 11, 'severity': 'MEDIUM',
                               'message': 'SP攻撃: sp_cost欠落'})

        # Rule 12: PL で physical 欠落（公式カテゴリ基準）
        if master_type == 'PL' and not ocr.get('physical'):
            issues.append({'rule_id': 12, 'severity': 'MEDIUM',
                           'message': f'PL: physical欠落（公式: {official_category}）'})

        # Rule 13: PL で units 欠落（公式カテゴリ基準）
        if master_type == 'PL' and not ocr.get('units'):
            issues.append({'rule_id': 13, 'severity': 'MEDIUM',
                           'message': f'PL: units欠落（公式: {official_category}）'})

        # Rule 14: ms_ability cost が null
        if isinstance(ms_ab, dict) and ms_ab.get('name'):
            if ms_ab.get('cost') is None:
                issues.append({'rule_id': 14, 'severity': 'MEDIUM',
                               'message': 'ms_ability costがnull'})

        # Rule 15: 公式名 vs OCR名 不一致（半角/全角括弧の正規化後も不一致）
        if official_name and ocr.get('name'):
            # 括弧を正規化して比較
            def _normalize_brackets(s):
                return s.replace('（', '(').replace('）', ')').replace('　', ' ')
            if _normalize_brackets(official_name) != _normalize_brackets(ocr['name']):
                issues.append({'rule_id': 15, 'severity': 'MEDIUM',
                               'message': f'名前不一致: 公式 "{official_name}" / OCR "{ocr["name"]}"',
                               'fix': {'field': 'name', 'current': ocr['name'], 'correct': official_name}})

        # Rule 19: MSアビリティ名がマスターと不一致
        if official_ms_abilities and isinstance(ms_ab, dict) and ms_ab.get('name'):
            ab_name = ms_ab['name']
            if ab_name not in official_ms_abilities:
                match, dist = ocr_test.find_closest_match(ab_name, official_ms_abilities, max_distance=3)
                msg = f'MSアビリティ名 "{ab_name}" がマスターに未登録'
                fix_data = None
                if match:
                    msg += f'（候補: "{match}" 距離{dist}）'
                    fix_data = {'field': 'ms_ability.name', 'current': ab_name, 'correct': match}
                iss = {'rule_id': 19, 'severity': 'MEDIUM', 'message': msg}
                if fix_data:
                    iss['fix'] = fix_data
                issues.append(iss)

        # Rule 20: リンクアビリティ名がマスターと不一致
        if official_link_names:
            for li, link in enumerate(la):
                if not isinstance(link, dict):
                    continue
                link_name = link.get('name', '')
                if not link_name or link_name in official_link_names:
                    continue
                match, dist = ocr_test.find_closest_match(link_name, official_link_names, max_distance=3)
                msg = f'リンク名 "{link_name}" がマスターに未登録'
                fix_data = None
                if match:
                    msg += f'（候補: "{match}" 距離{dist}）'
                    fix_data = {'field': f'link_ability[{li}].name', 'current': link_name, 'correct': match}
                iss = {'rule_id': 20, 'severity': 'MEDIUM', 'message': msg}
                if fix_data:
                    iss['fix'] = fix_data
                issues.append(iss)

        # ============================================================
        # LOW
        # ============================================================

        # Rule 16: 所属(affiliation)欠落
        if not ocr.get('affiliation'):
            issues.append({'rule_id': 16, 'severity': 'LOW',
                           'message': '所属(affiliation)欠落'})

        # Rule 17: MS でパイロット欠落（公式カテゴリ基準）
        if master_type == 'MS' and not ocr.get('pilot'):
            issues.append({'rule_id': 17, 'severity': 'LOW',
                           'message': f'MS: パイロット欠落（公式: {official_category}）'})

        # Rule 18: search_text に [?]
        search_text = ocr.get('search_text', '')
        if '[?]' in str(search_text):
            issues.append({'rule_id': 18, 'severity': 'LOW',
                           'message': 'search_textに[?]が含まれる'})

        if issues:
            front_url = (card.get('front') or {}).get('image_url', '')
            back_url = (card.get('back') or {}).get('image_url', '')
            problem_cards.append({
                'number': number,
                'name': official_name or ocr.get('name', ''),
                'type': master_type,
                'series': card.get('series', ''),
                'front_url': front_url,
                'back_url': back_url,
                'official': {
                    'name': official_name,
                    'category': official_category,
                },
                'ocr_data': ocr,
                'issues': issues,
            })
            for iss in issues:
                by_severity[iss['severity']] = by_severity.get(iss['severity'], 0) + 1
                rid = iss['rule_id']
                rule_counts[rid] = rule_counts.get(rid, 0) + 1

    # ルール定義テーブル
    rule_defs = {
        1:  ('全ステータスゼロ', 'CRITICAL'),
        2:  ('リンクアビリティ数!=2', 'CRITICAL'),
        3:  ('MS: ms_ability欠落', 'CRITICAL'),
        4:  ('ms_ability非標準フィールド', 'CRITICAL'),
        5:  ('OCR type/公式カテゴリ矛盾', 'HIGH'),
        6:  ('公式category vs OCR不一致', 'HIGH'),
        7:  ('レアリティ欠落', 'HIGH'),
        8:  ('MS: weapon欠落', 'HIGH'),
        9:  ('ms_ability name/desc null', 'HIGH'),
        10: ('リンクアビリティ重複', 'MEDIUM'),
        11: ('SP攻撃 sp_cost欠落', 'MEDIUM'),
        12: ('PL: physical欠落', 'MEDIUM'),
        13: ('PL: units欠落', 'MEDIUM'),
        14: ('ms_ability cost null', 'MEDIUM'),
        15: ('公式名 vs OCR名不一致', 'MEDIUM'),
        19: ('MSアビリティ名マスター不一致', 'MEDIUM'),
        20: ('リンク名マスター不一致', 'MEDIUM'),
        16: ('affiliation欠落', 'LOW'),
        17: ('MS: パイロット欠落', 'LOW'),
        18: ('search_textに[?]', 'LOW'),
    }

    by_rule = []
    for rid in sorted(rule_defs.keys()):
        name, sev = rule_defs[rid]
        by_rule.append({
            'id': rid,
            'name': name,
            'severity': sev,
            'count': rule_counts.get(rid, 0),
        })

    # 深刻度順にソート
    sev_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
    problem_cards.sort(key=lambda c: min(sev_order.get(i['severity'], 99) for i in c['issues']))

    total_with_ocr = sum(1 for v in all_cards.values() if v.get('ocr_data'))
    return {
        'success': True,
        'summary': {
            'total_checked': total_with_ocr,
            'problem_count': len(problem_cards),
            'by_severity': by_severity,
            'by_rule': by_rule,
        },
        'cards': problem_cards,
    }


@app.route('/ocr-quality')
def ocr_quality():
    return render_template('ocr_quality.html')


@app.route('/api/ocr-quality/report')
def api_ocr_quality_report():
    """品質チェック結果を JSON で返す"""
    result = run_quality_checks()
    return jsonify(result)


@app.route('/api/ocr-quality/reocr', methods=['POST'])
def api_ocr_quality_reocr():
    """指定カードの再OCRを実行する"""
    data = request.get_json(force=True)
    numbers = data.get('numbers', [])
    if not numbers:
        return jsonify({'success': False, 'error': 'カード番号を指定してください'}), 400

    all_source_cards = ocr_load_unique_cards()
    source_map = {c['card_number']: c for c in all_source_cards}

    results = []
    for num in numbers:
        card = source_map.get(num)
        if not card:
            results.append({'number': num, 'ok': False, 'error': 'カード未発見'})
            continue
        try:
            ok = ocr_process_card(card, model=None, force=True, stage='both')
            results.append({'number': num, 'ok': ok, 'error': None if ok else 'OCR処理失敗'})
        except Exception as e:
            results.append({'number': num, 'ok': False, 'error': str(e)})

    success_count = sum(1 for r in results if r['ok'])
    return jsonify({
        'success': True,
        'results': results,
        'total': len(numbers),
        'success_count': success_count,
        'failed_count': len(numbers) - success_count,
    })


@app.route('/api/ocr-quality/update-field', methods=['POST'])
def api_ocr_quality_update_field():
    """OCRデータの特定フィールドを手動編集する"""
    data = request.get_json(force=True)
    number = data.get('number', '').strip()
    ocr_json_str = data.get('ocr_data')

    if not number:
        return jsonify({'success': False, 'error': 'カード番号を指定してください'}), 400
    if ocr_json_str is None:
        return jsonify({'success': False, 'error': 'ocr_dataを指定してください'}), 400

    # JSON文字列の場合パース、dict ならそのまま
    if isinstance(ocr_json_str, str):
        try:
            new_ocr = json.loads(ocr_json_str)
        except json.JSONDecodeError as e:
            return jsonify({'success': False, 'error': f'JSON解析エラー: {e}'}), 400
    elif isinstance(ocr_json_str, dict):
        new_ocr = ocr_json_str
    else:
        return jsonify({'success': False, 'error': 'ocr_dataはJSONオブジェクトである必要があります'}), 400

    all_cards = _load_card_details()
    if number not in all_cards:
        return jsonify({'success': False, 'error': f'カード {number} が見つかりません'}), 404

    all_cards[number]['ocr_data'] = new_ocr
    _save_card_details(all_cards)

    return jsonify({'success': True, 'message': f'{number} のOCRデータを更新しました'})


def _resolve_field_path(obj, field_path):
    """ドット記法 + 配列インデックスでフィールドを解決する。

    例: 'card_label.class' → obj['card_label'], 'class'
        'link_ability[0].name' → obj['link_ability'][0], 'name'
    返却: (parent_obj, final_key) or (None, None)
    """
    # 配列インデックスを展開: 'link_ability[0].name' → ['link_ability', '[0]', 'name']
    import re as _re
    tokens = _re.split(r'\.', field_path)
    expanded = []
    for tok in tokens:
        m = _re.match(r'^(.+?)(\[\d+\])$', tok)
        if m:
            expanded.append(m.group(1))
            expanded.append(m.group(2))
        else:
            expanded.append(tok)

    target = obj
    for part in expanded[:-1]:
        if part.startswith('[') and part.endswith(']'):
            idx = int(part[1:-1])
            if isinstance(target, list) and 0 <= idx < len(target):
                target = target[idx]
            else:
                return None, None
        elif isinstance(target, dict) and part in target:
            target = target[part]
        else:
            return None, None

    final = expanded[-1]
    if final.startswith('[') and final.endswith(']'):
        idx = int(final[1:-1])
        return target, idx
    return target, final


@app.route('/api/ocr-quality/apply-fix', methods=['POST'])
def api_ocr_quality_apply_fix():
    """公式データに基づく修正を一括適用する（バックアップ＋修正フラグ付き）。

    リクエスト形式:
    { "fixes": [
        {"number": "AB01-001", "field": "category", "correct": "近距離"},
        {"number": "AB01-001", "field": "link_ability[0].name", "correct": "..."},
        ...
    ]}
    """
    data = request.get_json(force=True)
    fixes = data.get('fixes', [])
    if not fixes:
        return jsonify({'success': False, 'error': '修正対象がありません'}), 400

    all_cards = _load_card_details()

    # バックアップ作成（初回のみ）
    back_path = _CARD_DETAILS_PATH + '.back'
    if not os.path.exists(back_path):
        import shutil
        shutil.copy2(_CARD_DETAILS_PATH, back_path)

    applied = 0
    errors = []
    fix_log = []

    for fix in fixes:
        num = fix.get('number', '')
        field = fix.get('field', '')
        correct = fix.get('correct')

        if num not in all_cards:
            errors.append(f'{num}: カード未発見')
            continue
        ocr = all_cards[num].get('ocr_data')
        if not ocr:
            errors.append(f'{num}: OCRデータなし')
            continue

        parent, key = _resolve_field_path(ocr, field)
        if parent is None:
            errors.append(f'{num}: フィールド {field} にアクセスできません')
            continue

        old_val = parent[key] if isinstance(parent, (dict, list)) else None
        parent[key] = correct
        applied += 1
        fix_log.append({'number': num, 'field': field, 'old': old_val, 'new': correct})

    if applied > 0:
        _save_card_details(all_cards)

    return jsonify({
        'success': True,
        'applied': applied,
        'errors': errors,
        'fix_log': fix_log,
    })


if __name__ == '__main__':
    port = int(os.environ.get('OCR_PORT', 5002))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    print(f"[OCR Admin] http://localhost:{port}/admin")
    print(f"[OCR Admin] http://localhost:{port}/ocr-run")
    print(f"[OCR Admin] http://localhost:{port}/ocr-validate")
    print(f"[OCR Admin] http://localhost:{port}/ocr-quality")
    app.run(debug=debug, host='0.0.0.0', port=port)
