#!/bin/bash
# OCRデータ更新後のデプロイスクリプト
# 使い方: bash deploy_data.sh
#
# やること:
#   1. メインアプリ(5001)からAPIで最新データ取得 → gh-pages の data/ を更新
#   2. main ブランチの all_cards_list/ 変更をコミット
#   3. gh-pages ブランチの data/ 変更をコミット
#   4. 両方push

set -euo pipefail

MAIN_DIR="C:/Users/sekimiya/workspace/abds-main"
PAGES_DIR="C:/Users/sekimiya/workspace/abds"
API_BASE="http://localhost:5001"

# --- 前提チェック ---
echo "[1/5] サーバー稼働チェック..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API_BASE/" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" != "200" ]; then
  echo "ERROR: メインアプリ($API_BASE)が応答しません。先に起動してください。"
  echo "  cd $MAIN_DIR && py app.py"
  exit 1
fi

# --- APIからデータ取得（APIラッパーを剥がしてフロント用形式で保存） ---
echo "[2/5] APIから最新データ取得..."
py -c "
import json, urllib.request

api = '$API_BASE'
pages = '$PAGES_DIR'

# card_index: API { success, cards: [...] } → フロント [...]
with urllib.request.urlopen(f'{api}/api/card_index') as r:
    data = json.loads(r.read())
cards = data.get('cards', data)
with open(f'{pages}/data/card_index.json', 'w', encoding='utf-8') as f:
    json.dump(cards, f, ensure_ascii=False, separators=(',', ':'))
total = len(cards)
has_ocr = sum(1 for c in cards if c.get('has_ocr'))
print(f'  card_index: {total} cards, has_ocr: {has_ocr}/{total}')

# card_details: API { success, cards: { num: {...} } } → フロント { num: {...} }
with urllib.request.urlopen(f'{api}/api/cards/all_details') as r:
    data = json.loads(r.read())
details = data.get('cards', data)
with open(f'{pages}/data/card_details.json', 'w', encoding='utf-8') as f:
    json.dump(details, f, ensure_ascii=False, separators=(',', ':'))
print(f'  card_details: {len(details)} cards')

# link_index: API { success, links: {...} } → フロント {...}
with urllib.request.urlopen(f'{api}/api/link_index') as r:
    data = json.loads(r.read())
links = data.get('links', data)
with open(f'{pages}/data/link_index.json', 'w', encoding='utf-8') as f:
    json.dump(links, f, ensure_ascii=False, separators=(',', ':'))
print(f'  link_index: {len(links)} links')

# tactics_cards: API { success, main: [...], sub: [...] } → フロント { main: [...], sub: [...] }
with urllib.request.urlopen(f'{api}/api/tactics_cards') as r:
    data = json.loads(r.read())
tactics = {k: v for k, v in data.items() if k != 'success'}
with open(f'{pages}/data/tactics_cards.json', 'w', encoding='utf-8') as f:
    json.dump(tactics, f, ensure_ascii=False, separators=(',', ':'))
print(f'  tactics_cards: {sum(len(v) for v in tactics.values())} cards')
"
# version.json を更新（IDBキャッシュの再取得トリガー）
py -c "
import json, hashlib
from datetime import datetime

pages = '$PAGES_DIR'
with open(f'{pages}/data/card_index.json', encoding='utf-8') as f:
    raw = f.read()
    idx = json.loads(raw)
cards = idx if isinstance(idx, list) else idx.get('cards', [])
with open(f'{pages}/data/card_details.json', encoding='utf-8') as f:
    det = json.load(f)
with open(f'{pages}/data/link_index.json', encoding='utf-8') as f:
    links = json.load(f)

now = datetime.now()
version = {
    'version': now.strftime('%Y%m%d-%H%M%S'),
    'card_count': len(cards),
    'detail_count': len(det),
    'link_count': len(links),
    'index_hash': hashlib.md5(raw.encode()).hexdigest()[:12],
    'built_at': now.isoformat(timespec='seconds'),
}
with open(f'{pages}/data/version.json', 'w', encoding='utf-8') as f:
    json.dump(version, f, ensure_ascii=False, indent=2)
print(f'  version.json: {version[\"version\"]}')
"

OCR_COUNT=$(py -c "
import json
with open('$PAGES_DIR/data/card_index.json', encoding='utf-8') as f:
    d = json.load(f)
cards = d if isinstance(d, list) else d.get('cards', [])
total = len(cards)
has_ocr = sum(1 for c in cards if c.get('has_ocr'))
print(f'{has_ocr}/{total}')
")

# --- main ブランチ コミット ---
echo "[3/5] main ブランチ..."
cd "$MAIN_DIR"
if git diff --quiet all_cards_list/ 2>/dev/null; then
  echo "  変更なし（スキップ）"
else
  CHANGED=$(git diff --stat all_cards_list/ | tail -1)
  git add all_cards_list/
  git commit -m "data: OCRフラグ更新 ($CHANGED)"
  echo "  コミット完了"
fi

# --- gh-pages ブランチ コミット ---
echo "[4/5] gh-pages ブランチ..."
cd "$PAGES_DIR"

# リモートの最新を取り込む
git fetch origin gh-pages
LOCAL=$(git rev-parse gh-pages)
REMOTE=$(git rev-parse origin/gh-pages)
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "  リモートに新しい変更あり、pull中..."
  git pull origin gh-pages || true
fi

if git diff --quiet data/ 2>/dev/null; then
  echo "  変更なし（スキップ）"
else
  git add data/
  git commit -m "data: OCR静的JSON更新 (has_ocr: $OCR_COUNT)"
  echo "  コミット完了"
fi

# --- Push ---
echo "[5/5] Push..."
cd "$MAIN_DIR"
if ! git diff --quiet origin/main..main 2>/dev/null; then
  git push origin main
  echo "  main pushed"
else
  echo "  main: push不要"
fi

cd "$PAGES_DIR"
if ! git diff --quiet origin/gh-pages..gh-pages 2>/dev/null; then
  git push origin gh-pages
  echo "  gh-pages pushed"
else
  echo "  gh-pages: push不要"
fi

echo ""
echo "完了！"
