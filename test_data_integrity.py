#!/usr/bin/env python3
"""データ整合性テスト - 各変更後に実行して問題がないことを確認する"""

import json
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

ERRORS = []
WARNINGS = []

def error(msg):
    ERRORS.append(msg)
    print(f"  ERROR: {msg}")

def warn(msg):
    WARNINGS.append(msg)
    print(f"  WARN: {msg}")


def load(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def test_card_index():
    print("=== card_index.json ===")
    index = load('data/card_index.json')
    if not isinstance(index, list):
        error("card_index is not a list")
        return

    print(f"  count: {len(index)}")
    if len(index) < 3700:
        error(f"card_index count too low: {len(index)}")

    required_fields = ['number', 'name', 'type', 'category', 'cost', 'series',
                        'rarity', 'front_url', 'back_url', 'mobility', 'ranged',
                        'melee', 'hp', 'has_ocr', 'search_text']
    for i, entry in enumerate(index):
        for f in required_fields:
            if f not in entry:
                error(f"card_index[{i}] ({entry.get('number','?')}): missing field '{f}'")
        if not isinstance(entry.get('number'), str) or not entry['number']:
            error(f"card_index[{i}]: number empty or not str")
        if not isinstance(entry.get('name'), str) or not entry['name']:
            error(f"card_index[{i}] ({entry.get('number','?')}): name empty")
        for stat in ('mobility', 'ranged', 'melee', 'hp'):
            if not isinstance(entry.get(stat), (int, float)):
                error(f"card_index ({entry.get('number','?')}): {stat} not numeric: {entry.get(stat)}")
        cost = entry.get('cost')
        if not isinstance(cost, int):
            error(f"card_index ({entry.get('number','?')}): cost not int: {cost}")

    numbers = [e['number'] for e in index]
    if len(numbers) != len(set(numbers)):
        dupes = [n for n in numbers if numbers.count(n) > 1]
        error(f"card_index has duplicate numbers: {set(dupes)}")

    sorted_nums = sorted(numbers)
    if numbers != sorted_nums:
        warn("card_index is not sorted by number")

    print(f"  OK: {len(index)} entries validated")


def test_card_details():
    print("=== card_details.json ===")
    details = load('data/card_details.json')
    if not isinstance(details, dict):
        error("card_details is not a dict")
        return

    print(f"  count: {len(details)}")
    if len(details) < 3700:
        error(f"card_details count too low: {len(details)}")

    for num, entry in details.items():
        if not entry.get('name'):
            error(f"card_details[{num}]: name empty")
        if not entry.get('ocr_data'):
            error(f"card_details[{num}]: ocr_data missing")
        ocr = entry.get('ocr_data', {})
        if not ocr.get('type'):
            error(f"card_details[{num}]: ocr_data.type missing")
        if not isinstance(ocr.get('stats'), dict):
            error(f"card_details[{num}]: ocr_data.stats missing or not dict")

    print(f"  OK: {len(details)} entries validated")


def test_cross_consistency():
    print("=== cross-file consistency ===")
    index = load('data/card_index.json')
    details = load('data/card_details.json')

    idx_nums = {e['number'] for e in index}
    det_nums = set(details.keys())

    if idx_nums != det_nums:
        only_idx = idx_nums - det_nums
        only_det = det_nums - idx_nums
        if only_idx:
            error(f"in card_index but not card_details: {only_idx}")
        if only_det:
            error(f"in card_details but not card_index: {only_det}")
    else:
        print(f"  OK: {len(idx_nums)} cards match between index and details")

    for entry in index:
        num = entry['number']
        det = details.get(num, {})
        if entry['name'] != det.get('name', ''):
            error(f"{num}: name mismatch index='{entry['name']}' details='{det.get('name')}'")


def test_link_index():
    print("=== link_index.json ===")
    links = load('data/link_index.json')
    details = load('data/card_details.json')

    if not isinstance(links, dict):
        error("link_index is not a dict")
        return

    print(f"  count: {len(links)} links")
    for name, data in links.items():
        if not isinstance(data.get('ms_cards'), list):
            error(f"link '{name}': ms_cards not a list")
        if not isinstance(data.get('pl_cards'), list):
            error(f"link '{name}': pl_cards not a list")
        for cn in data.get('ms_cards', []) + data.get('pl_cards', []):
            if cn not in details:
                warn(f"link '{name}' references non-existent card: {cn}")

    print(f"  OK: {len(links)} links validated")


def test_null_consistency():
    """null/空文字列/空リストの使い分けが統一されているかチェック"""
    print("=== null/empty consistency ===")
    index = load('data/card_index.json')

    int_or_null_fields = ['eb_level', 'eb_trigger_level']
    for entry in index:
        num = entry.get('number', '?')
        for f in int_or_null_fields:
            val = entry.get(f)
            if val is not None and not isinstance(val, int):
                error(f"{num}: {f} should be int|null, got {type(val).__name__}: {val}")

    str_fields = ['pilot', 'model', 'illustrator', 'skill_name', 'ability_name',
                  'eb_text', 'eb_skill_text', 'eb_trigger_cond', 'eb_type',
                  'sq_rush_effect', 'sqsp_text', 'sq_skill_text', 'sq_trigger',
                  'sq_gauge_rate', 'ocr_timestamp']
    for entry in index:
        num = entry.get('number', '?')
        for f in str_fields:
            val = entry.get(f)
            if val is not None and not isinstance(val, str):
                error(f"{num}: {f} should be str|null, got {type(val).__name__}: {val}")

    list_fields = ['sp_effect_tags', 'sqsp_effect_tags', 'ebsp_effect_tags',
                   'sq_skill_effect_tags', 'skill_effect_tags']
    for entry in index:
        num = entry.get('number', '?')
        for f in list_fields:
            val = entry.get(f)
            if val is not None and not isinstance(val, list):
                error(f"{num}: {f} should be list|null, got {type(val).__name__}: {val}")

    print(f"  OK: null/empty consistency checked")


def test_all_cards_list_field_names():
    """all_cards_listのフィールド名統一チェック"""
    print("=== all_cards_list field names ===")
    acl_dir = 'all_cards_list'
    if not os.path.isdir(acl_dir):
        warn("all_cards_list/ not found")
        return
    bad = []
    for fn in os.listdir(acl_dir):
        if not fn.endswith('.json'):
            continue
        with open(os.path.join(acl_dir, fn)) as f:
            d = json.load(f)
        if 'card_number' in d and 'number' not in d:
            bad.append(fn)
    if bad:
        error(f"all_cards_list: {len(bad)} files use 'card_number' instead of 'number': {bad[:3]}...")
    else:
        print(f"  OK: all files use 'number' field")


def test_no_dummy_entries():
    """card_index/card_detailsにdummyエントリがないか"""
    print("=== no dummy entries ===")
    index = load('data/card_index.json')
    dummies = [e for e in index if e.get('number') == 'dummy']
    if dummies:
        error(f"card_index has {len(dummies)} dummy entries")
    else:
        print("  OK: no dummy entries")


def test_ocr_data_types():
    """card_details内のocr_data型整合チェック"""
    print("=== ocr_data type consistency ===")
    details = load('data/card_details.json')

    for num, entry in details.items():
        ocr = entry.get('ocr_data', {})
        if not ocr:
            continue

        aff = ocr.get('affiliation')
        if aff == 'ー':
            error(f"{num}: affiliation is 'ー' (should be null or empty)")

        phys = ocr.get('physical')
        if isinstance(phys, dict):
            age = phys.get('age')
            if isinstance(age, str) and age != '':
                try:
                    int(age)
                    warn(f"{num}: physical.age is numeric string '{age}' (should be int)")
                except ValueError:
                    pass

    print("  OK: ocr_data types checked")


if __name__ == '__main__':
    test_card_index()
    test_card_details()
    test_cross_consistency()
    test_link_index()
    test_null_consistency()
    test_all_cards_list_field_names()
    test_no_dummy_entries()
    test_ocr_data_types()

    print()
    print(f"=== RESULTS ===")
    print(f"Errors: {len(ERRORS)}")
    print(f"Warnings: {len(WARNINGS)}")
    if ERRORS:
        print("\nFAILED - errors found:")
        for e in ERRORS[:20]:
            print(f"  {e}")
        if len(ERRORS) > 20:
            print(f"  ... and {len(ERRORS) - 20} more")
        sys.exit(1)
    else:
        print("\nPASSED")
        sys.exit(0)
