#!/usr/bin/env python3
"""data/card_signatures.json を再生成する。

デッキ画像照合(index.html / mobile.html の DeckScanUI)が使う、
全カード表面の画像指紋(dHash 64bit + 4x4 色シグネチャ)の索引。

重要: 索引は必ず「端末側と同じコードパス」で作ること。
deck_scan.js の cellSignature() をそのまま使う必要があるため、
Pillow ではなく実際に Chrome を起動して計算する。

新弾を追加して images/cards/ が増えたら必ず実行すること。

  python3 scripts/build_card_signatures.py
"""
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'card_signatures.json'
PORT = 8765

CHROME_CANDIDATES = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    shutil.which('google-chrome') or '',
    shutil.which('chromium') or '',
    shutil.which('chromium-browser') or '',
]


def find_chrome():
    for c in CHROME_CANDIDATES:
        if c and os.path.exists(c):
            return c
    sys.exit('Chrome / Chromium が見つかりません。索引生成には必要です。')


def main():
    fronts = sorted(
        p.stem for p in (ROOT / 'images' / 'cards').glob('*.jpg')
        if not p.stem.endswith('_b')
    )
    if not fronts:
        sys.exit('images/cards/ にカード画像がありません。')
    print(f'対象カード: {len(fronts)}枚')

    result = {}
    done = threading.Event()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

        def do_POST(self):
            n = int(self.headers['Content-Length'])
            result.update(json.loads(self.rfile.read(n)))
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')
            done.set()

        def log_message(self, *a):
            pass

    class Threaded(socketserver.ThreadingMixIn, socketserver.TCPServer):
        # 画像を並列で配れるようにする(単一スレッドだと3941枚の取得が詰まる)
        daemon_threads = True
        allow_reuse_address = True

    srv = Threaded(('127.0.0.1', PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    tmp = Path(tempfile.mkdtemp())
    (ROOT / '_fronts.tmp.json').write_text(json.dumps(fronts), encoding='utf-8')
    shutil.copy(ROOT / 'scripts' / 'build_signatures.html', ROOT / '_build.tmp.html')
    try:
        # ヘッドレスChromeはページが終わっても自分では終了しないので、
        # 結果のPOSTを受け取った時点でこちらから止める。
        proc = subprocess.Popen([
            find_chrome(), '--headless=new', '--disable-gpu', '--no-sandbox',
            f'--user-data-dir={tmp}',
            f'http://127.0.0.1:{PORT}/_build.tmp.html?save=http://127.0.0.1:{PORT}/save',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not done.wait(timeout=900):
            print('タイムアウト: 生成が終わりませんでした', file=sys.stderr)
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    finally:
        srv.shutdown()
        for f in ('_fronts.tmp.json', '_build.tmp.html'):
            (ROOT / f).unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)

    if len(result) != len(fronts):
        sys.exit(f'生成できたのは {len(result)}/{len(fronts)} 枚。中断します。')

    OUT.write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
    print(f'書き出し: {OUT.relative_to(ROOT)}  {OUT.stat().st_size // 1024}KB  {len(result)}件')


if __name__ == '__main__':
    main()
