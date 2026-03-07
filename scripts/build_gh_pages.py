#!/usr/bin/env python3
"""
build_gh_pages.py — gh-pages 用の静的JSONを一括生成するスクリプト

generate_card_index.py + build_pwa.py の機能を統合。
Flask/dotenv 等の外部依存なし（stdlib + logic のみ）。
GitHub Actions からも直接実行可能。

生成ファイル:
  - card_index.json   (軽量インデックス配列)
  - card_details.json (全カード詳細)
  - link_index.json   (リンクアビリティ索引)
  - version.json      (ビルドメタデータ)

パラレルカード (_p1, _p2 等):
  --pages-dir を指定すると、既存の gh-pages データから _p カードを
  読み込んでマージする。_p カードの OCR データはベースカードからコピー。

Usage:
    python scripts/build_gh_pages.py --output-dir output/
    python scripts/build_gh_pages.py --output-dir output/ --pages-dir ../abds/data
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from logic.card_index_builder import build_card_index


def main():
    parser = argparse.ArgumentParser(description='Build static JSON for gh-pages')
    parser.add_argument('--output-dir', required=True, help='Output directory')
    parser.add_argument('--all-cards-dir', default='all_cards_list')
    parser.add_argument('--ocr-dir', default='ocr_results_debug')
    parser.add_argument('--pages-dir', default=None,
                        help='Existing gh-pages data/ dir to merge _p cards from')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print(f'Building from: all_cards={args.all_cards_dir}, ocr={args.ocr_dir}')

    index_list, detail_map, link_map = build_card_index(
        all_cards_dir=args.all_cards_dir,
        ocr_dir=args.ocr_dir,
        write_back_ocr_flags=False,
    )

    # --- パラレルカード (_p) マージ ---
    p_merged_index = 0
    p_merged_detail = 0
    if args.pages_dir:
        p_merged_index, p_merged_detail = _merge_parallel_cards(
            args.pages_dir, index_list, detail_map
        )

    # --- card_index.json ---
    index_list.sort(key=lambda x: x['number'])
    index_path = os.path.join(args.output_dir, 'card_index.json')
    index_json = json.dumps(index_list, ensure_ascii=False, separators=(',', ':'))
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_json)

    has_ocr_count = sum(1 for c in index_list if c.get('has_ocr'))
    print(f'card_index.json: {len(index_list)} cards, has_ocr={has_ocr_count}'
          + (f' (_p merged: {p_merged_index})' if p_merged_index else ''))

    # --- card_details.json (raw フィールド除去) ---
    cleaned_details = {}
    for num, detail in detail_map.items():
        d = dict(detail)
        ocr = d.get('ocr_data')
        if isinstance(ocr, dict):
            ocr = dict(ocr)
            ocr.pop('raw', None)
            d['ocr_data'] = ocr
        cleaned_details[num] = d

    details_path = os.path.join(args.output_dir, 'card_details.json')
    with open(details_path, 'w', encoding='utf-8') as f:
        json.dump(cleaned_details, f, ensure_ascii=False, separators=(',', ':'))
    det_ocr = sum(1 for c in cleaned_details.values() if c.get('ocr_data'))
    print(f'card_details.json: {len(cleaned_details)} cards, has_ocr_data={det_ocr}'
          + (f' (_p merged: {p_merged_detail})' if p_merged_detail else ''))

    # --- link_index.json ---
    link_path = os.path.join(args.output_dir, 'link_index.json')
    with open(link_path, 'w', encoding='utf-8') as f:
        json.dump(link_map, f, ensure_ascii=False, separators=(',', ':'))
    print(f'link_index.json: {len(link_map)} links')

    # --- tactics_cards.json (あればコピー) ---
    tactics_src = os.path.join(project_root, 'tactics_cards.json')
    tactics_dst = os.path.join(args.output_dir, 'tactics_cards.json')
    if os.path.exists(tactics_src):
        import shutil
        shutil.copy2(tactics_src, tactics_dst)
    elif args.pages_dir:
        # 既存のを維持
        existing = os.path.join(args.pages_dir, 'tactics_cards.json')
        if os.path.exists(existing):
            import shutil
            shutil.copy2(existing, tactics_dst)

    # --- version.json ---
    index_hash = hashlib.md5(index_json.encode('utf-8')).hexdigest()[:12]
    version_data = {
        'version': time.strftime('%Y%m%d-%H%M%S'),
        'card_count': len(index_list),
        'detail_count': len(cleaned_details),
        'link_count': len(link_map),
        'index_hash': index_hash,
        'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    version_path = os.path.join(args.output_dir, 'version.json')
    with open(version_path, 'w', encoding='utf-8') as f:
        json.dump(version_data, f, ensure_ascii=False, indent=2)
    print(f'version.json: v{version_data["version"]} hash={index_hash}')

    # --- review_candidates.md (あれば維持) ---
    if args.pages_dir:
        rc_src = os.path.join(args.pages_dir, 'review_candidates.md')
        rc_dst = os.path.join(args.output_dir, 'review_candidates.md')
        if os.path.exists(rc_src) and not os.path.exists(rc_dst):
            import shutil
            shutil.copy2(rc_src, rc_dst)

    print(f'\nDone! Output: {args.output_dir}')


def _merge_parallel_cards(pages_dir, index_list, detail_map):
    """既存の gh-pages データから _p カードを読み込んでマージする"""
    index_merged = 0
    detail_merged = 0
    new_numbers = {c['number'] for c in index_list}

    # card_index.json から _p カード読み込み
    idx_path = os.path.join(pages_dir, 'card_index.json')
    if os.path.exists(idx_path):
        with open(idx_path, 'r', encoding='utf-8') as f:
            existing = json.load(f)
        if isinstance(existing, dict):
            existing = existing.get('cards', [])
        for c in existing:
            num = c.get('number', '')
            if '_p' not in num or num in new_numbers:
                continue
            # ベースカードから has_ocr を引き継ぐ
            base = re.sub(r'_p\d+$', '', num)
            base_entry = next((x for x in index_list if x['number'] == base), None)
            if base_entry:
                c['has_ocr'] = base_entry.get('has_ocr', False)
                c['ocr_timestamp'] = base_entry.get('ocr_timestamp', '')
            index_list.append(c)
            new_numbers.add(num)
            index_merged += 1

    # card_details.json から _p カード読み込み
    det_path = os.path.join(pages_dir, 'card_details.json')
    if os.path.exists(det_path):
        with open(det_path, 'r', encoding='utf-8') as f:
            existing_det = json.load(f)
        for num, detail in existing_det.items():
            if '_p' not in num or num in detail_map:
                continue
            # ベースカードから ocr_data をコピー
            base = re.sub(r'_p\d+$', '', num)
            if base in detail_map and detail_map[base].get('ocr_data'):
                detail['ocr_data'] = detail_map[base]['ocr_data']
            detail_map[num] = detail
            detail_merged += 1

    return index_merged, detail_merged


if __name__ == '__main__':
    main()
