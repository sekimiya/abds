#!/usr/bin/env python3
"""
normalize_ocr.py - OCRデータのフィールド名を正規スキーマに統一

Usage:
  python normalize_ocr.py              # 全ファイル正規化
  python normalize_ocr.py --dry-run    # 変更内容の表示のみ
  python normalize_ocr.py --check      # CI用: 非正規ファイルがあればexit 1
  python normalize_ocr.py --series VEB02  # 特定シリーズのみ
"""

import argparse
import json
import os
import sys

from schema import normalize_ocr_data, validate_ocr_basic

OCR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ocr_results_debug')


def normalize_all_files(ocr_dir, series_filter=None, dry_run=False, check_mode=False):
    total = 0
    modified = 0
    all_changes = []
    validation_errors = []

    for fname in sorted(os.listdir(ocr_dir)):
        if not fname.endswith('_basic.json'):
            continue
        fpath = os.path.join(ocr_dir, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        cn = data.get('card_number', '')
        if series_filter and not cn.startswith(series_filter):
            continue

        total += 1
        data, changes = normalize_ocr_data(data)

        errors = validate_ocr_basic(data)
        if errors:
            validation_errors.extend(errors)

        if changes:
            modified += 1
            all_changes.append((cn, changes))
            if not dry_run and not check_mode:
                with open(fpath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)

    return {
        'total': total,
        'modified': modified,
        'changes': all_changes,
        'validation_errors': validation_errors,
    }


def main():
    parser = argparse.ArgumentParser(description='OCRデータ正規化')
    parser.add_argument('--dry-run', action='store_true', help='変更内容を表示のみ')
    parser.add_argument('--check', action='store_true', help='CI用: 非正規ファイルがあればexit 1')
    parser.add_argument('--series', type=str, default=None, help='対象シリーズ (例: VEB02)')
    args = parser.parse_args()

    print('=== OCRデータ正規化 ===')
    if args.dry_run:
        print('(dry-run: 書き込みなし)')
    if args.check:
        print('(check mode: 非正規ファイルの検出)')

    result = normalize_all_files(
        OCR_DIR,
        series_filter=args.series,
        dry_run=args.dry_run,
        check_mode=args.check,
    )

    print(f'対象ファイル: {result["total"]}')
    print(f'要正規化: {result["modified"]}')

    if result['changes']:
        print('\n変更内容:')
        for cn, changes in result['changes']:
            for c in changes:
                print(f'  {cn}: {c}')

    if result['validation_errors']:
        print(f'\nバリデーションエラー ({len(result["validation_errors"])}件):')
        for e in result['validation_errors']:
            print(f'  {e}')

    if args.check and result['modified'] > 0:
        print(f'\n非正規ファイルが{result["modified"]}件あります。normalize_ocr.py を実行してください。')
        sys.exit(1)

    if args.check and result['validation_errors']:
        print(f'\nバリデーションエラーが{len(result["validation_errors"])}件あります。'
              'エイリアスで自動変換できない値は手動で修正してください。')
        sys.exit(1)

    if not args.dry_run and not args.check and result['modified'] > 0:
        print(f'\n{result["modified"]}ファイルを正規化しました。')

    print('完了')


if __name__ == '__main__':
    main()
