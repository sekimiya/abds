#!/usr/bin/env python3
"""VE01-004 の Stage 2 再構造化を実行するワンショットスクリプト"""
import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

print("=== Starting ===", flush=True)

from card_ocr_cc import load_unique_cards, load_raw_text, stage2_structure, setup_logging

logger = setup_logging(verbose=True)

all_cards = load_unique_cards()
card = next((c for c in all_cards if c['card_number'] == 'VE01-004'), None)
if not card:
    print('ERROR: VE01-004 not found', flush=True)
    sys.exit(1)

print(f'Card: {card["card_number"]} - {card["card_name"]}', flush=True)
raw_text = load_raw_text(card)
if not raw_text:
    print('ERROR: No raw text found', flush=True)
    sys.exit(1)

print(f'Raw text length: {len(raw_text)} chars', flush=True)
print('Running Stage 2 structuring (model=haiku)...', flush=True)
ok = stage2_structure(card, raw_text, model='haiku', force=True)
print(f'Result: {"SUCCESS" if ok else "FAILED"}', flush=True)

if ok:
    # 結果を表示
    import json
    from pathlib import Path
    from card_ocr_cc import make_file_prefix, OCR_RESULTS_DIR
    prefix = make_file_prefix(card['card_number'], card['card_name'], card.get('series', ''))
    basic_path = OCR_RESULTS_DIR / f"{prefix}_basic.json"
    with open(basic_path, 'r', encoding='utf-8') as f:
        result = json.load(f)
    ocr = result.get('ocr_data', {})
    print(f'\n=== 検証 ===', flush=True)
    print(f'ms_ability type: {type(ocr.get("ms_ability")).__name__}', flush=True)
    print(f'ms_ability: {json.dumps(ocr.get("ms_ability"), ensure_ascii=False, indent=2)}', flush=True)
    print(f'link_ability count: {len(ocr.get("link_ability", []))}', flush=True)
    print(f'link_ability: {json.dumps(ocr.get("link_ability"), ensure_ascii=False, indent=2)}', flush=True)
    print(f'\nTop-level keys: {sorted(ocr.keys())}', flush=True)
    print(f'has ocr_engine: {"ocr_engine" in result}', flush=True)
    print(f'has raw: {"raw" in ocr}', flush=True)
