import os
import json
import re

def parse_ms_raw(raw, fallback):
    r = {}
    def find(pattern, cast=None, default=None):
        m = re.search(pattern, raw)
        if not m:
            return default
        v = m.group(1)
        return cast(v) if cast else v
    r['type'] = 'MS'
    r['name'] = find(r' ([^ ]+) 頭頂高| ([^ ]+) 全高| ([^ ]+) 本体重量')
    r['model'] = find(r'([A-Z0-9\-]+ [A-Z ]+)')
    r['cost'] = find(r'コスト(\d+)', int)
    r['pilot'] = find(r'パイロット ([^ ]+)')
    r['stats'] = {
        'mobility': find(r'機動力 (\d+)', int),
        'ranged_attack': find(r'遠距離攻撃 (\d+)', int),
        'melee_attack': find(r'近距離攻撃 (\d+)', int),
        'hp': find(r'HP (\d+)', int)
    }
    r['terrain_compatibility'] = {
        'ground': find(r'地上 ?([A-Z])'),
        'space': find(r'宇宙 ?([A-Z])'),
        'desert': find(r'砂漠 ?([A-Z])'),
        'water': find(r'水中 ?([A-Z])')
    }
    r['weapon'] = {
        'main': {
            'name': find(r'MAIN ([^ ]+)'),
            'range': find(r'MAIN [^ ]+ 射程(\d+)', int),
            'type': find(r'MAIN [^ ]+ 射程\d+ ([^ ]+)')
        },
        'sub': {
            'name': find(r'SUB ([^ ]+)'),
            'range': find(r'SUB [^ ]+ 射程(\d+)', int),
            'type': find(r'SUB [^ ]+ 射程\d+ ([^ ]+)')
        }
    }
    r['ms_ability'] = {
        'name': find(r'MS ABILITY ([^ ]+)'),
        'type': find(r'MS ABILITY [^ ]+ ([^ ]+)'),
        'range': find(r'射程(\d+)', int),
        'cost': find(r'コスト(\d+)', int),
        'description': find(r'コスト\d+ ([^\n]+)')
    }
    r['illustrator'] = find(r'illust ([^ ]+)')
    return {**fallback, **{k: v for k, v in r.items() if v}}

def main():
    os.makedirs('from_raw', exist_ok=True)
    files = [f for f in os.listdir('ocr_results_debug') if f.endswith('_basic.json')]
    for f in files:
        with open(f'ocr_results_debug/{f}', encoding='utf-8') as fin:
            data = json.load(fin)
        ocr = data.get('ocr_data', {})
        if ocr.get('type') != 'MS' or 'raw' not in ocr:
            continue
        raw = ocr['raw']
        result = parse_ms_raw(raw, {'card_number': data.get('card_number'), 'card_name': data.get('card_name')})
        outname = f"from_raw/{data.get('card_number')}_{data.get('card_name')}.json"
        with open(outname, 'w', encoding='utf-8') as fout:
            json.dump(result, fout, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    main() 