#!/usr/bin/env python3
"""アーセナルコマンダー(AC)版デッキシミュレータのデータを生成する。

  python3 scripts/build_commander_data.py

入力: commander/ocr/<カード番号>.json(仕様は docs/OCR_AC_LAYOUT.md)
      commander/images/ の PARA 画像(パラレルはベースのデータをコピー)
出力: commander/data/card_index.json / card_details.json / version.json /
      link_index.json(ACにリンクは無いので空) / tactics_cards.json(同じく空)

アーセナルベース側の data/ と rebuild_index.py には一切触れない。
UIはAB版のコードを流用しているので、AB互換のフィールド名(pilot_skill.effect など)も併せて出力する。
"""
import glob
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AC_DIR = os.path.join(ROOT, 'commander')
OCR_DIR = os.path.join(AC_DIR, 'ocr')
IMG_DIR = os.path.join(AC_DIR, 'images')
DATA_DIR = os.path.join(AC_DIR, 'data')
IMG_URL = './images/'

TYPES = {'MS', 'PL', 'CMD'}
COLORS = {'赤', '緑', '青'}
CATEGORIES = {'MS': {'遠距離', '近距離'}, 'PL': {'殲滅', '制圧', '防衛'}, 'CMD': {'遠距離', '近距離'}}
SERIES_LABEL = {'TEST': 'オープンβ', 'PR': 'PR NEXT'}


def validate(num, o):
    errs = []
    t = o.get('type')
    if t not in TYPES:
        errs.append(f'type {t!r}')
    for c in o.get('colors') or []:
        if c not in COLORS:
            errs.append(f'color {c!r}')
    cat = o.get('category')
    if t in CATEGORIES and cat not in CATEGORIES[t]:
        errs.append(f'category {cat!r}')
    if t in ('MS', 'PL'):
        if not isinstance(o.get('cost'), int):
            errs.append('cost が整数でない')
        st = o.get('stats') or {}
        if not isinstance(st.get('atk'), int) or not isinstance(st.get('hp'), int):
            errs.append('stats.atk/hp が整数でない')
    if t == 'MS' and not o.get('special_attack'):
        errs.append('special_attack が無い')
    if t == 'PL' and not o.get('pilot_skill'):
        errs.append('pilot_skill が無い')
    if t == 'CMD' and not (o.get('commander_skill') and o.get('commander_system')):
        errs.append('commander_skill/system が無い')
    return [f'{num}: {e}' for e in errs]


def to_app_ocr(o):
    """ACのOCRデータにAB版UIが読むフィールド名を足す"""
    a = json.loads(json.dumps(o))
    ps = a.get('pilot_skill')
    if ps:
        ps.setdefault('effect', ps.get('description', ''))
    ab = a.get('ms_ability')
    if ab and ab.get('shape'):
        ab.setdefault('condition', ab['shape'])
    sp = a.get('special_attack')
    if sp and sp.get('shape'):
        sp.setdefault('attack_type', sp['shape'])
    a['color'] = a.get('colors') or []
    a['link_ability'] = []
    return a


def index_entry(num, card, o, front, back):
    st = o.get('stats') or {}
    series = num.split('-')[0]
    ms_ab = o.get('ms_ability') or {}
    sp = o.get('special_attack') or {}
    ps = o.get('pilot_skill') or {}
    cs = o.get('commander_skill') or {}
    csys = o.get('commander_system') or {}
    text = ' '.join(str(x) for x in [
        num, o.get('name'), o.get('english_name'), o.get('model'), ' '.join(o.get('traits') or []),
        ' '.join(o.get('colors') or []), ms_ab.get('name'), ms_ab.get('description'),
        sp.get('name'), sp.get('description'), ps.get('name'), ps.get('description'),
        cs.get('description'), csys.get('name'), csys.get('description'), o.get('illustrator'),
    ] if x)
    return {
        'number': num,
        'name': o.get('name') or card.get('card_name', ''),
        'type': o['type'],
        'category': o.get('category') or '',
        'cost': o.get('cost') or 0,
        'series': SERIES_LABEL.get(series, series),
        'rarity': o.get('rarity') or '',
        'color': o.get('colors') or [],
        'traits': o.get('traits') or [],
        'atk': st.get('atk') or 0,
        'hp': st.get('hp') or 0,
        'front_url': IMG_URL + front,
        'back_url': IMG_URL + back,
        'has_back_image': True,
        'has_ocr': True,
        'illustrator': o.get('illustrator') or '',
        'model': o.get('model') or '',
        'skill_name': ps.get('name') or '',
        'skill_trigger': ps.get('trigger') or '',
        'ability_name': ms_ab.get('name') or '',
        'sp_name': sp.get('name') or '',
        'search_text': text.lower(),
        # AB版UIが参照する項目(ACでは常に無し)
        'mobility': 0, 'ranged': 0, 'melee': 0,
        'terrain': {}, 'has_sqsp': False, 'has_sq_skill': False, 'has_sq_link': False,
        'has_eb': False, 'has_eb_skill': False, 'has_eb_link': False, 'has_ab_link': False,
        'has_skip_sp': False, 'sp_effect_tags': [], 'skill_effect_tags': [],
        'sq_skill_effect_tags': [], 'sqsp_effect_tags': [], 'ebsp_effect_tags': [],
    }


def main():
    sources = sorted(glob.glob(os.path.join(OCR_DIR, '*.json')))
    if not sources:
        sys.exit(f'{OCR_DIR} にOCRソースが無い')
    index, details, errors = [], {}, []
    for path in sources:
        card = json.load(open(path, encoding='utf-8'))
        num = card['card_number']
        o = card['ocr_data']
        errors += validate(num, o)
        entries = [(num, card['front_image'], card['back_image'])]
        # パラレル: TEST_001CMD_duumy.webp -> TEST_001CMDPARA_duumy.webp
        m = re.match(r'^(.*?)(_du+m+y\.webp)$', card['front_image'])
        mb = re.match(r'^(.*?)b(_du+m+y\.webp)$', card['back_image'])
        if m and mb:
            pf = f'{m.group(1)}PARA{m.group(2)}'
            pb = f'{mb.group(1)}PARAb{mb.group(2)}'
            if os.path.exists(os.path.join(IMG_DIR, pf)) and os.path.exists(os.path.join(IMG_DIR, pb)):
                entries.append((f'{num}_p1', pf, pb))
        for n, front, back in entries:
            # パラレルは券面を読んだ commander/ocr/parallel/<番号>.json があればそちらを使う
            po = os.path.join(OCR_DIR, 'parallel', f'{n}.json')
            if n != num and os.path.exists(po):
                pc = json.load(open(po, encoding='utf-8'))
                o_n = pc['ocr_data']
                errors += validate(n, o_n)
            else:
                o_n = o
            for f in (front, back):
                if not os.path.exists(os.path.join(IMG_DIR, f)):
                    errors.append(f'{n}: 画像 {f} が無い')
            index.append(index_entry(n, card, o_n, front, back))
            details[n] = {
                'number': n,
                'name': o_n.get('name', ''),
                'url': IMG_URL + front,
                'category': o_n.get('category', ''),
                'series': index[-1]['series'],
                'front': {'image_url': IMG_URL + front},
                'back': {'image_url': IMG_URL + back},
                'ocr_data': to_app_ocr(o_n),
            }

    if errors:
        print('検証エラー:')
        for e in errors:
            print('  ' + e)
        sys.exit(1)

    index.sort(key=lambda c: c['number'])
    now = datetime.now()
    version = {
        'version': now.strftime('%Y%m%d-%H%M%S'),
        'card_count': len(index),
        'detail_count': len(details),
        'link_count': 0,
        'index_hash': f'ac_{now.strftime("%Y%m%d")}',
        'built_at': now.isoformat(timespec='seconds'),
    }
    out = {
        'card_index.json': index,
        'card_details.json': details,
        'version.json': version,
        'link_index.json': {},
        'tactics_cards.json': {'main': [], 'sub': []},
    }
    for name, data in out.items():
        with open(os.path.join(DATA_DIR, name), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    kinds = {}
    for c in index:
        kinds[c['type']] = kinds.get(c['type'], 0) + 1
    print(f'{len(index)}枚を書き出し {kinds}')


if __name__ == '__main__':
    main()
