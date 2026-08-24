#!/usr/bin/env python3
"""data/card_signatures.json を再生成する。

デッキ画像照合(index.html / mobile.html の DeckScan)が使う、
全カード表面の画像指紋(dHash 64bit + 4x4 色シグネチャ)の索引。

重要: 索引は必ず「端末側と同じコードパス」で作ること。
Pillow など別の縮小アルゴリズムで作ると、canvas で計算する照会側と
わずかにズレて誤認識が増える。そのため実際に Chrome を起動し、
index.html と同一の signature 関数(build_signatures.html に複製)で計算する。

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
SAVE_PORT = 8766

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
    sys.exit('Chrome / Chromium が見つかりません。デッキ画像照合の索引生成には必要です。')


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(directory, port, handler=None):
    h = handler or (lambda *a, **k: _Quiet(*a, directory=directory, **k))
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(('127.0.0.1', port), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    fronts = sorted(
        p.stem for p in (ROOT / 'images' / 'cards').glob('*.jpg')
        if not p.stem.endswith('_b')
    )
    if not fronts:
        sys.exit('images/cards/ にカード画像がありません。')
    print(f'対象カード: {len(fronts)}枚')

    tmp = Path(tempfile.mkdtemp())
    (tmp / 'fronts.json').write_text(json.dumps(fronts), encoding='utf-8')
    shutil.copy(ROOT / 'scripts' / 'build_signatures.html', tmp / 'index.html')

    result = {}

    class Save(http.server.SimpleHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers['Content-Length'])
            result.update(json.loads(self.rfile.read(n)))
            self.send_response(200); self.send_header('Content-Length', '2'); self.end_headers()
            self.wfile.write(b'ok')
        def log_message(self, *a):
            pass

    s1 = serve(str(ROOT), PORT)
    s2 = serve(str(tmp), SAVE_PORT, Save)
    try:
        # 生成ページは一時ディレクトリから配信し、カード画像は本体側から取りに行かせる
        shutil.copy(tmp / 'fronts.json', ROOT / '_fronts.tmp.json')
        shutil.copy(ROOT / 'scripts' / 'build_signatures.html', ROOT / '_build.tmp.html')
        profile = tmp / 'profile'
        subprocess.run([
            find_chrome(), '--headless=new', '--disable-gpu', '--no-sandbox',
            f'--user-data-dir={profile}', '--virtual-time-budget=900000',
            f'http://127.0.0.1:{PORT}/_build.tmp.html?save=http://127.0.0.1:{SAVE_PORT}/save',
        ], check=True, capture_output=True)
    finally:
        s1.shutdown(); s2.shutdown()
        for f in ('_fronts.tmp.json', '_build.tmp.html'):
            (ROOT / f).unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)

    if len(result) != len(fronts):
        sys.exit(f'生成できたのは {len(result)}/{len(fronts)} 枚。中断します。')

    OUT.write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
    print(f'書き出し: {OUT.relative_to(ROOT)}  {OUT.stat().st_size // 1024}KB  {len(result)}件')


if __name__ == '__main__':
    main()
