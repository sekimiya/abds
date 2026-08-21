#!/usr/bin/env python3
"""公式カードリストの検索ファセットを総当たりして、弾ごとの「公式が持っている値」表を作る。

公式サイトの検索フォームは ARSENAL BASE(既存ゲーム)のパラメータで引けるので、
カード裏面のOCR結果を機械的に突き合わせる正解データとして使える。

  python3 scripts/fetch_official_facets.py --series 529309 --prefix BP09 \
      -o series_data/facets_BP09.json

出力: { "BP09-001": { "cost": 4, "type": "MS", "category": "遠距離", ... }, ... }
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = 'https://www.gundam-ab.com/cardlist/'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# チェックボックス系(name[]=値)。(パラメータ名, 出力キー, 複数値か)
CHECKBOX_FACETS = [
    ('costs[]', 'cost', False),
    ('rarities[]', 'rarity', False),
    ('msTypes[]', 'category', False),
    ('plTypes[]', 'category', False),
    ('msAbilityCosts[]', 'ms_ability.cost', False),
    ('msAbilityTriggerConditions[]', 'ms_ability.activation', False),
    ('tacticCosts[]', 'special_attack.sp_cost', False),
    ('mainWeaponTypes[]', 'weapon.main.type', False),
    ('subWeaponTypes[]', 'weapon.sub.type', False),
    ('terrainGrounds[]', 'terrain.ground', False),
    ('terrainUniverses[]', 'terrain.space', False),
    ('terrainDeserts[]', 'terrain.desert', False),
    ('terrainUnderwater[]', 'terrain.water', False),
]
# セレクト系(name=値)
SELECT_FACETS = [
    ('msAbilityName', 'ms_ability.name', False),
    ('msAbilityRange', 'ms_ability.target', False),
    ('tacticRange', 'special_attack.target', False),
    ('linkAbilityName', 'link_ability.name', True),
    ('linkAbilityEffect', 'link_ability.effect', True),
]
# 公式の表記 → リポジトリのcanonical語彙
WEAPON_TYPE_MAP = {'遠距離射撃': '遠距離', '遠距離攻撃': '遠距離', '近距離攻撃': '近距離'}


def fetch(params, series, cache_dir, sleep=0.4):
    """検索結果HTMLを取得(キャッシュ付き)"""
    query = [('series', str(series))] + list(params)
    url = BASE + '?' + urllib.parse.urlencode(query)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        key = re.sub(r'[^A-Za-z0-9]+', '_', urllib.parse.urlencode(query))[:150]
        path = os.path.join(cache_dir, key + '.html')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                return f.read()
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Referer': BASE + '?series=' + str(series),
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode('utf-8', 'replace')
    if cache_dir:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(body)
    time.sleep(sleep)
    return body


def card_numbers(body, prefix):
    """検索結果HTMLからカード番号を抽出(パラレルは同番号なので重複排除)"""
    return sorted(set(re.findall(
        r'<p class="cardNo">(' + re.escape(prefix) + r'-[0-9A-Za-z]+)</p>', body)))


def form_values(body, name, is_select):
    """検索フォームから指定パラメータの候補値を列挙"""
    if is_select:
        m = re.search(r'<select name="' + re.escape(name) + r'".*?</select>', body, re.S)
        if not m:
            return []
        vals = re.findall(r'<option value="([^"]*)"', m.group(0))
    else:
        vals = re.findall(r'name="' + re.escape(name) + r'"[^>]*value="([^"]*)"', body)
    return [html.unescape(v) for v in dict.fromkeys(vals) if v]


def sweep(series, prefix, cache_dir, verbose=True):
    seed = fetch([], series, cache_dir)
    all_cards = card_numbers(seed, prefix)
    if not all_cards:
        sys.exit(f'series={series} に {prefix}- のカードが見つからない')
    facets = {n: {} for n in all_cards}
    facets_multi = {n: {} for n in all_cards}

    for name, key, multi in CHECKBOX_FACETS + SELECT_FACETS:
        is_select = (name, key, multi) in SELECT_FACETS
        values = form_values(seed, name, is_select)
        if not values:
            continue
        hit_total = 0
        for v in values:
            param = (name, v)
            body = fetch([param], series, cache_dir)
            hits = card_numbers(body, prefix)
            hit_total += len(hits)
            if key.startswith('weapon.') and key.endswith('.type'):
                v = WEAPON_TYPE_MAP.get(v, v)
            for n in hits:
                if multi:
                    facets_multi[n].setdefault(key, []).append(v)
                elif key in facets[n] and facets[n][key] != v:
                    # 同一カードが複数値でヒット = 想定外(片方が誤り or 多値フィールド)
                    facets[n].setdefault('_conflicts', []).append(
                        f'{key}: {facets[n][key]} / {v}')
                else:
                    facets[n][key] = v
        if verbose:
            print(f'  {name}: {len(values)}値 → 延べ{hit_total}件ヒット', file=sys.stderr)

    for n in all_cards:
        for k, vs in facets_multi[n].items():
            facets[n][k] = sorted(set(vs))
    return facets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--series', required=True)
    ap.add_argument('--prefix', required=True)
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--cache', default=None, help='HTMLキャッシュディレクトリ')
    args = ap.parse_args()

    print(f'series={args.series} ({args.prefix}) のファセットを収集中...', file=sys.stderr)
    facets = sweep(args.series, args.prefix, args.cache)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(facets, f, ensure_ascii=False, indent=2)
    conflicts = {n: v['_conflicts'] for n, v in facets.items() if '_conflicts' in v}
    print(f'{len(facets)}枚を {args.out} に書き出し', file=sys.stderr)
    if conflicts:
        print('複数値ヒット(要確認):', json.dumps(conflicts, ensure_ascii=False), file=sys.stderr)


if __name__ == '__main__':
    main()
