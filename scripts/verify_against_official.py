#!/usr/bin/env python3
"""OCR結果を公式検索のファセット表と突き合わせて、読み取り誤りを機械検出する。

  python3 scripts/fetch_official_facets.py --series 529309 --prefix BP09 \
      -o series_data/facets_BP09.json
  python3 scripts/verify_against_official.py series_data/facets_BP09.json

ファセット表に載らない数値(4ステータス・戦術技威力)は、OCR値を仮説として
公式検索に min=max=OCR値 で問い合わせ、そのカードがヒットするかで検証する。
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.fetch_official_facets import fetch, card_numbers  # noqa: E402

OCR_DIR = 'ocr_results_debug'
# ファセットキー → ocr_data 内のパス
SCALAR_FIELDS = {
    'cost': ('cost',),
    'rarity': ('rarity',),
    'category': ('category',),
    'ms_ability.cost': ('ms_ability', 'cost'),
    'ms_ability.activation': ('ms_ability', 'activation'),
    'ms_ability.name': ('ms_ability', 'name'),
    'ms_ability.target': ('ms_ability', 'target'),
    'special_attack.sp_cost': ('special_attack', 'sp_cost'),
    'special_attack.target': ('special_attack', 'target'),
    'weapon.main.type': ('weapon', 'main', 'type'),
    'weapon.sub.type': ('weapon', 'sub', 'type'),
    'terrain.ground': ('terrain_compatibility', 'ground'),
    'terrain.space': ('terrain_compatibility', 'space'),
    'terrain.desert': ('terrain_compatibility', 'desert'),
    'terrain.water': ('terrain_compatibility', 'water'),
}
# 公式の数値検索パラメータ → ocr_data 内のパス
NUMERIC_FIELDS = {
    'paramMobilities': ('stats', 'mobility'),
    'paramRangePowers': ('stats', 'ranged_attack'),
    'paramShortRangePowers': ('stats', 'melee_attack'),
    'paramHps': ('stats', 'hp'),
    'tacticPowers': ('special_attack', 'power'),
}
LINK_PREFIXES = {'[EB]': 'is_eb_link', '[SQ]': 'is_sq_link', '[AB]': 'is_ab_link'}


def dig(obj, path):
    for k in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def load_ocr(numbers):
    """ocr_results_debug/*_basic.json を card_number で引けるように読む"""
    out = {}
    for path in sorted(glob.glob(os.path.join(OCR_DIR, '*_basic.json'))):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f'  読み込み失敗: {path}: {e}', file=sys.stderr)
            continue
        num = data.get('card_number')
        if num in numbers and num not in out:
            out[num] = (path, data.get('ocr_data') or {})
    return out


def same(official, ocr):
    """公式値(文字列)とOCR値を型を揃えて比較"""
    if ocr is None:
        return False
    return str(official).strip() == str(ocr).strip()


def check_scalars(num, facet, ocr, issues):
    for key, path in SCALAR_FIELDS.items():
        if key not in facet:
            continue
        val = dig(ocr, path)
        if not same(facet[key], val):
            issues.append(f'{num} {key}: 公式={facet[key]!r} OCR={val!r}')
    # 公式にMSアビリティ名が無い = アビリティ自体が無いカード
    if 'ms_ability.name' not in facet and ocr.get('type') == 'MS':
        if dig(ocr, ('ms_ability', 'name')):
            issues.append(f'{num} ms_ability: 公式に登録が無いのにOCRは '
                          f'{dig(ocr, ("ms_ability", "name"))!r} を出している')


def check_links(num, facet, ocr, issues):
    official_names = facet.get('link_ability.name')
    if official_names is None:
        return
    links = ocr.get('link_ability') or []
    ocr_names = [(l.get('name') or '') for l in links]
    for oname in official_names:
        prefix = next((p for p in LINK_PREFIXES if oname.startswith(p)), '')
        bare = oname[len(prefix):]
        if bare not in ocr_names:
            issues.append(f'{num} link_ability: 公式の {bare!r} がOCRに無い (OCR={ocr_names})')
            continue
        link = links[ocr_names.index(bare)]
        for p, flag in LINK_PREFIXES.items():
            want = (p == prefix)
            if bool(link.get(flag)) != want:
                issues.append(f'{num} link_ability[{bare}].{flag}: 公式={want} OCR={link.get(flag)}')
    if len(ocr_names) != len(official_names):
        issues.append(f'{num} link_ability: 枚数不一致 公式{len(official_names)}件 OCR{len(ocr_names)}件')
    for effect in facet.get('link_ability.effect', []):
        if not any(effect in (l.get('effect') or '') for l in links):
            issues.append(f'{num} link_ability.effect: 公式の {effect!r} がどのリンクにも含まれない')


def check_numerics(series, prefix, ocr_map, cache, issues):
    """OCRの数値を仮説として公式検索で裏取りする(値ごとに1リクエスト)"""
    for param, path in NUMERIC_FIELDS.items():
        by_value = {}
        for num, (_, ocr) in ocr_map.items():
            v = dig(ocr, path)
            if isinstance(v, int):
                by_value.setdefault(v, []).append(num)
        for v, nums in sorted(by_value.items()):
            body = fetch([(f'{param}[min]', v), (f'{param}[max]', v)], series, cache)
            hits = set(card_numbers(body, prefix))
            for num in nums:
                if num not in hits:
                    issues.append(f'{num} {param}: OCR値 {v} で公式検索にヒットしない')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('facets', help='fetch_official_facets.py の出力JSON')
    ap.add_argument('--series', help='数値検証に使うシリーズID(省略時は数値検証をスキップ)')
    ap.add_argument('--prefix', help='カード番号プレフィックス(--series と併用)')
    ap.add_argument('--cache', default=None)
    args = ap.parse_args()

    with open(args.facets, encoding='utf-8') as f:
        facets = json.load(f)
    ocr_map = load_ocr(set(facets))

    issues = []
    for num in sorted(facets):
        if num not in ocr_map:
            issues.append(f'{num}: OCR結果 (_basic.json) が無い')
            continue
        _, ocr = ocr_map[num]
        check_scalars(num, facets[num], ocr, issues)
        check_links(num, facets[num], ocr, issues)
    if args.series:
        check_numerics(args.series, args.prefix, ocr_map, args.cache, issues)

    checked = len(ocr_map)
    if issues:
        print(f'{checked}枚を照合 / {len(issues)}件の不一致:')
        for i in issues:
            print('  NG ' + i)
        sys.exit(1)
    print(f'{checked}枚を照合 / 公式値と完全一致')


if __name__ == '__main__':
    main()
