#!/usr/bin/env python3
"""
デプロイ前検証ワークフロー

gh-pages へ push する前にこのスクリプトを実行し、
全チェックが PASS であることを確認する。

使い方:
  python pre_deploy_check.py           # 全チェック実行
  python pre_deploy_check.py --quick   # データ検証のみ(高速)
  python pre_deploy_check.py --fix     # 自動修正可能な問題を修正して再検証
"""

import json
import os
import re
import subprocess
import sys
import argparse
import time
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# Config
# ============================================================

DATA_FILES = [
    'data/card_index.json',
    'data/card_details.json',
    'data/link_index.json',
    'data/tactics_cards.json',
    'data/version.json',
]

APP_SHELL_FILES = [
    'index.html',
    'mobile.html',
    'decks.html',
    'decks_mobile.html',
    'corrections.html',
    'guide.html',
    'manifest.json',
    'sw.js',
]

OPTIONAL_FILES = [
    'data/card_numbers.json',
    'front_cards.json',
    'back_cards.json',
]

# ============================================================
# Result tracking
# ============================================================

class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warned = 0
        self.sections = []
        self._current = None

    def section(self, name):
        self._current = {'name': name, 'checks': [], 'status': 'PASS'}
        self.sections.append(self._current)
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")

    def ok(self, msg):
        self.passed += 1
        self._current['checks'].append(('PASS', msg))
        print(f"  PASS  {msg}")

    def fail(self, msg):
        self.failed += 1
        self._current['checks'].append(('FAIL', msg))
        self._current['status'] = 'FAIL'
        print(f"  FAIL  {msg}")

    def warn(self, msg):
        self.warned += 1
        self._current['checks'].append(('WARN', msg))
        print(f"  WARN  {msg}")

    def summary(self):
        print(f"\n{'='*60}")
        print(f"  SUMMARY")
        print(f"{'='*60}")
        for s in self.sections:
            icon = 'PASS' if s['status'] == 'PASS' else 'FAIL'
            print(f"  [{icon}] {s['name']}")
        print()
        print(f"  Passed: {self.passed}")
        print(f"  Failed: {self.failed}")
        print(f"  Warnings: {self.warned}")
        print()
        if self.failed > 0:
            print("  DEPLOY BLOCKED - 問題を修正してから再実行してください")
            return False
        else:
            print("  ALL CLEAR - デプロイ可能です")
            return True


R = Results()


# ============================================================
# 1. ファイル存在チェック
# ============================================================

def check_files():
    R.section("1. デプロイ対象ファイル存在チェック")

    for f in DATA_FILES:
        if os.path.exists(f):
            size = os.path.getsize(f)
            if size < 100:
                R.fail(f"{f}: サイズが異常に小さい ({size} bytes)")
            else:
                R.ok(f"{f} ({size:,} bytes)")
        else:
            R.fail(f"{f}: 見つからない")

    for f in APP_SHELL_FILES:
        if os.path.exists(f):
            R.ok(f"{f}")
        else:
            R.fail(f"{f}: 見つからない")

    for f in OPTIONAL_FILES:
        if os.path.exists(f):
            R.ok(f"{f} (optional)")
        else:
            R.warn(f"{f}: 見つからない (optional)")


# ============================================================
# 2. JSON妥当性
# ============================================================

def check_json_validity():
    R.section("2. JSON妥当性チェック")

    all_json = DATA_FILES + [f for f in OPTIONAL_FILES if f.endswith('.json')]
    for f in all_json:
        if not os.path.exists(f):
            continue
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                json.load(fh)
            R.ok(f"{f}: valid JSON")
        except json.JSONDecodeError as e:
            R.fail(f"{f}: JSON parse error: {e}")


# ============================================================
# 3. データ整合性 (test_data_integrity.py)
# ============================================================

def check_data_integrity():
    R.section("3. データ整合性テスト")

    result = subprocess.run(
        [sys.executable, 'test_data_integrity.py'],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode == 0:
        R.ok("test_data_integrity.py: ALL PASSED")
    else:
        lines = result.stdout.strip().split('\n')
        errors = [l for l in lines if 'ERROR:' in l]
        R.fail(f"test_data_integrity.py: {len(errors)} errors")
        for e in errors[:5]:
            R.fail(f"  {e.strip()}")
        if len(errors) > 5:
            R.fail(f"  ... and {len(errors) - 5} more")

    result = subprocess.run(
        [sys.executable, 'normalize_ocr.py', '--check'],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode == 0:
        R.ok("normalize_ocr.py --check: OCRソース正規形OK")
    else:
        lines = [l for l in result.stdout.strip().split('\n')
                 if l.strip().startswith(('要正規化', 'バリデーション')) or ': ' in l]
        R.fail("normalize_ocr.py --check: 非正規のOCRソースあり")
        for l in lines[:8]:
            R.fail(f"  {l.strip()}")


# ============================================================
# 4. フィルタテスト (test_filters.py)
# ============================================================

def check_filters():
    R.section("4. フィルタ機能テスト")

    result = subprocess.run(
        [sys.executable, 'test_filters.py'],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode == 0:
        lines = result.stdout.strip().split('\n')
        ok_count = sum(1 for l in lines if l.strip().startswith('OK:'))
        R.ok(f"test_filters.py: ALL PASSED ({ok_count} checks)")
    else:
        lines = result.stdout.strip().split('\n')
        fails = [l for l in lines if 'FAIL:' in l]
        R.fail(f"test_filters.py: {len(fails)} failures")
        for f in fails[:5]:
            R.fail(f"  {f.strip()}")


# ============================================================
# 5. version.json 整合性
# ============================================================

def check_version():
    R.section("5. version.json 整合性")

    with open('data/version.json', 'r') as f:
        ver = json.load(f)

    with open('data/card_index.json', 'r') as f:
        index = json.load(f)
    with open('data/card_details.json', 'r') as f:
        details = json.load(f)
    with open('data/link_index.json', 'r') as f:
        links = json.load(f)

    if ver.get('card_count') == len(index):
        R.ok(f"card_count: {ver['card_count']} == card_index length")
    else:
        R.fail(f"card_count: version={ver.get('card_count')} != card_index={len(index)}")

    if ver.get('detail_count') == len(details):
        R.ok(f"detail_count: {ver['detail_count']} == card_details length")
    else:
        R.fail(f"detail_count: version={ver.get('detail_count')} != card_details={len(details)}")

    if ver.get('link_count') == len(links):
        R.ok(f"link_count: {ver['link_count']} == link_index length")
    else:
        R.fail(f"link_count: version={ver.get('link_count')} != link_index={len(links)}")

    built = ver.get('built_at', '')
    if built:
        try:
            dt = datetime.fromisoformat(built)
            age = datetime.now() - dt
            if age.days > 7:
                R.warn(f"built_at: {built} ({age.days}日前) - rebuild_index.py --full の実行を検討")
            else:
                R.ok(f"built_at: {built}")
        except ValueError:
            R.warn(f"built_at: パース不能 '{built}'")
    else:
        R.warn("built_at: 未設定")


# ============================================================
# 6. card_index / card_details 相互整合
# ============================================================

def check_cross_consistency():
    R.section("6. card_index / card_details 相互整合")

    with open('data/card_index.json', 'r') as f:
        index = json.load(f)
    with open('data/card_details.json', 'r') as f:
        details = json.load(f)

    idx_nums = {c['number'] for c in index}
    det_nums = set(details.keys())

    only_idx = idx_nums - det_nums
    only_det = det_nums - idx_nums
    if only_idx:
        R.fail(f"card_indexにのみ存在: {len(only_idx)}件 (例: {list(only_idx)[:3]})")
    if only_det:
        R.fail(f"card_detailsにのみ存在: {len(only_det)}件 (例: {list(only_det)[:3]})")
    if not only_idx and not only_det:
        R.ok(f"card_index と card_details のカード番号が完全一致 ({len(idx_nums)}件)")

    mismatch = 0
    for entry in index:
        det = details.get(entry['number'], {})
        if entry['name'] != det.get('name', ''):
            mismatch += 1
    if mismatch:
        R.fail(f"名前不一致: {mismatch}件")
    else:
        R.ok("全カードの名前が一致")

    dup_nums = [n for n in [c['number'] for c in index]
                if [c['number'] for c in index].count(n) > 1]
    if dup_nums:
        R.fail(f"card_index に番号重複: {set(dup_nums)}")
    else:
        R.ok("card_index に番号重複なし")


# ============================================================
# 7. link_index 整合性
# ============================================================

def check_link_index():
    R.section("7. link_index 整合性")

    with open('data/link_index.json', 'r') as f:
        links = json.load(f)
    with open('data/card_details.json', 'r') as f:
        details = json.load(f)

    orphan_count = 0
    for name, data in links.items():
        for cn in data.get('ms_cards', []) + data.get('pl_cards', []):
            if cn not in details:
                orphan_count += 1

    if orphan_count:
        R.warn(f"link_indexが参照するカードがcard_detailsに存在しない: {orphan_count}件")
    else:
        R.ok(f"link_index の全カード参照が有効 ({len(links)} links)")

    empty_links = [n for n, d in links.items()
                   if not d.get('ms_cards') and not d.get('pl_cards')]
    if empty_links:
        R.warn(f"所属カード0件のリンク: {empty_links[:5]}")
    else:
        R.ok("全リンクに所属カードあり")

    check_link_ocr_confusions(links, details)


# OCRが取り違えやすい字形ペア(濁点/半濁点、漢字とカタカナの同形)
OCR_CONFUSABLE_PAIRS = [
    ('ハ', 'パ'), ('ハ', 'バ'), ('バ', 'パ'), ('ヒ', 'ピ'), ('ヒ', 'ビ'), ('ビ', 'ピ'),
    ('フ', 'プ'), ('フ', 'ブ'), ('ブ', 'プ'), ('ヘ', 'ペ'), ('ヘ', 'ベ'), ('ベ', 'ペ'),
    ('ホ', 'ポ'), ('ホ', 'ボ'), ('ボ', 'ポ'),
    ('カ', 'ガ'), ('キ', 'ギ'), ('ク', 'グ'), ('ケ', 'ゲ'), ('コ', 'ゴ'),
    ('サ', 'ザ'), ('シ', 'ジ'), ('ス', 'ズ'), ('セ', 'ゼ'), ('ソ', 'ゾ'),
    ('タ', 'ダ'), ('チ', 'ヂ'), ('ツ', 'ヅ'), ('テ', 'デ'), ('ト', 'ド'),
    ('カ', '力'), ('ロ', '口'), ('エ', '工'), ('ニ', '二'), ('ハ', '八'),
    ('ト', '卜'), ('タ', '夕'), ('モ', '乇'), ('ー', '一'), ('ミ', '三'),
]
OCR_CONFUSABLE = {frozenset(p) for p in OCR_CONFUSABLE_PAIRS}


def _confusable_typo(a, b):
    """a と b が1文字だけ違い、その1文字がOCR誤読ペアなら True"""
    if len(a) != len(b) or a == b:
        return False
    diffs = [(x, y) for x, y in zip(a, b) if x != y]
    return len(diffs) == 1 and frozenset(diffs[0]) in OCR_CONFUSABLE


def check_link_ocr_confusions(links, details):
    """リンク名/リンク効果に紛れ込んだOCR誤読を検出する。

    - リンク名: 字形が紛らわしい1文字違いの別リンクが併存していないか
      (例: プラフスキー粒子 / ブラフスキー粒子 → リンクが分断され不発になる)
    - リンク効果: 同名リンクなのに 遠距離⇔近距離 だけが逆の少数派がいないか
      (例: 肉薄する戦い が [機動力][遠距離攻撃力] になっている → 伸びるステータスが逆になる)
    """
    size = {n: len(d.get('ms_cards', [])) + len(d.get('pl_cards', []))
            for n, d in links.items()}
    names = sorted(links)
    name_issues = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if _confusable_typo(a, b):
                minor, major = sorted((a, b), key=lambda n: size[n])
                name_issues.append(
                    f"{minor!r}({size[minor]}枚) は {major!r}({size[major]}枚) の"
                    f"OCR誤読の可能性: {links[minor].get('ms_cards', [])[:5]}")
    if name_issues:
        for msg in name_issues:
            R.fail(f"リンク名にOCR誤読の疑い: {msg}")
    else:
        R.ok("リンク名にOCR誤読(1文字違いの重複)なし")

    def norm_effect(s):
        return re.sub(r'[\[\]【】「」［］\s]', '', s or '')

    variants = {}
    holders = {}
    for num, card in details.items():
        for la in (card.get('ocr_data') or {}).get('link_ability') or []:
            if not isinstance(la, dict):
                continue
            name = (la.get('name') or '').strip()
            if not name:
                continue
            eff = norm_effect(la.get('effect'))
            variants.setdefault(name, {}).setdefault(eff, 0)
            variants[name][eff] += 1
            holders.setdefault((name, eff), []).append(num)

    eff_issues = []
    for name, counts in variants.items():
        total = sum(counts.values())
        if total < 10:
            continue
        major = max(counts, key=lambda e: counts[e])
        for eff, cnt in counts.items():
            if eff == major or cnt * 5 > total:
                continue
            # 遠⇔近を揃えると多数派と一致 = ステータス取り違え
            if eff.replace('遠距離', '近距離') == major.replace('遠距離', '近距離'):
                eff_issues.append(
                    f"{name!r}: {cnt}/{total}枚だけ {eff!r} (多数派 {major!r}) "
                    f"→ {sorted(holders[(name, eff)])[:5]}")
    if eff_issues:
        for msg in eff_issues:
            R.fail(f"リンク効果の遠/近が多数派と逆: {msg}")
    else:
        R.ok("同名リンクの遠/近攻撃力アップに食い違いなし")


# ============================================================
# 8. フロント参照ファイルの一貫性
# ============================================================

def check_frontend_refs():
    R.section("8. フロント参照チェック")

    sw_data_files = []
    with open('sw.js', 'r') as f:
        sw_content = f.read()
    for m in re.findall(r"'\./([^']+\.json)'", sw_content):
        sw_data_files.append(m)

    for f in sw_data_files:
        if os.path.exists(f):
            R.ok(f"sw.js参照 {f}: 存在")
        else:
            R.fail(f"sw.js参照 {f}: ファイル不在")

    sw_html_files = []
    for m in re.findall(r"'\./([^']+\.html)'", sw_content):
        sw_html_files.append(m)
    for f in sw_html_files:
        if os.path.exists(f):
            R.ok(f"sw.js参照 {f}: 存在")
        else:
            R.fail(f"sw.js参照 {f}: ファイル不在")

    for html_file in ['index.html', 'mobile.html']:
        with open(html_file, 'r') as f:
            content = f.read()
        data_refs = re.findall(r"fetch\(['\"]\./(data/[^'\"]+\.json)['\"]", content)
        for ref in data_refs:
            if os.path.exists(ref):
                R.ok(f"{html_file} -> {ref}: 存在")
            else:
                R.fail(f"{html_file} -> {ref}: ファイル不在")


# ============================================================
# 9. データサイズ異常検知
# ============================================================

def check_data_sizes():
    R.section("9. データサイズ異常検知")

    sizes = {
        'data/card_index.json': (3_000_000, 15_000_000),
        'data/card_details.json': (3_000_000, 15_000_000),
        'data/link_index.json': (50_000, 500_000),
        'data/tactics_cards.json': (5_000, 100_000),
        'data/version.json': (100, 1_000),
    }

    for f, (min_size, max_size) in sizes.items():
        if not os.path.exists(f):
            continue
        size = os.path.getsize(f)
        if size < min_size:
            R.fail(f"{f}: {size:,} bytes (最小 {min_size:,} を下回る - データ欠損の疑い)")
        elif size > max_size:
            R.warn(f"{f}: {size:,} bytes (最大 {max_size:,} を超過 - 肥大化の疑い)")
        else:
            R.ok(f"{f}: {size:,} bytes")


# ============================================================
# 10. schema.py バリデーション
# ============================================================

def check_schema_validation():
    R.section("10. schema.py バリデーション")

    try:
        from schema import validate_card_index_entry, validate_card_details_entry
    except ImportError:
        R.warn("schema.py のインポート失敗 - スキップ")
        return

    with open('data/card_index.json', 'r') as f:
        index = json.load(f)
    with open('data/card_details.json', 'r') as f:
        details = json.load(f)

    idx_errors = 0
    for entry in index:
        errs = validate_card_index_entry(entry)
        idx_errors += len(errs)
    if idx_errors:
        R.fail(f"card_index validation: {idx_errors} errors")
    else:
        R.ok(f"card_index validation: {len(index)} entries OK")

    det_errors = 0
    for num, entry in details.items():
        errs = validate_card_details_entry(num, entry)
        det_errors += len(errs)
    if det_errors:
        R.fail(f"card_details validation: {det_errors} errors")
    else:
        R.ok(f"card_details validation: {len(details)} entries OK")


# ============================================================
# 11. Git状態チェック
# ============================================================

def check_git_status():
    R.section("11. Git状態チェック")

    result = subprocess.run(['git', 'branch', '--show-current'],
                            capture_output=True, text=True)
    branch = result.stdout.strip()
    if branch == 'gh-pages':
        R.ok(f"ブランチ: {branch}")
    else:
        R.warn(f"ブランチ: {branch} (gh-pages以外)")

    result = subprocess.run(['git', 'status', '--porcelain',
                             '--', 'data/', '*.html', 'sw.js', 'schema.py', 'rebuild_index.py'],
                            capture_output=True, text=True)
    changed = [l for l in result.stdout.strip().split('\n') if l.strip()]
    if changed:
        R.warn(f"未コミットの変更 {len(changed)} files:")
        for c in changed[:5]:
            R.warn(f"  {c}")
    else:
        R.ok("デプロイ対象に未コミットの変更なし")

    result = subprocess.run(['git', 'log', '-1', '--format=%H %ci'],
                            capture_output=True, text=True)
    if result.stdout.strip():
        R.ok(f"最新コミット: {result.stdout.strip()}")


# ============================================================
# 12. 画像ディレクトリ確認
# ============================================================

def check_images():
    R.section("12. 画像ディレクトリ確認")

    img_dir = 'images/cards'
    if not os.path.isdir(img_dir):
        R.warn(f"{img_dir}/: ディレクトリなし (GitHub Pagesで画像配信できない)")
        return

    jpg_files = [f for f in os.listdir(img_dir) if f.endswith('.jpg')]
    R.ok(f"{img_dir}/: {len(jpg_files)} images")

    with open('data/card_index.json', 'r') as f:
        index = json.load(f)

    expected = set()
    for c in index:
        num = c['number'].split('_p')[0] if '_p' in c['number'] else c['number']
        expected.add(f"{c['number']}.jpg")
        expected.add(f"{c['number']}_b.jpg")

    existing = set(jpg_files)
    missing_front = [c['number'] for c in index if f"{c['number']}.jpg" not in existing]

    if missing_front:
        pct = len(missing_front) / len(index) * 100
        if pct > 10:
            R.warn(f"表面画像欠落: {len(missing_front)}/{len(index)} ({pct:.0f}%)")
        else:
            R.ok(f"画像カバー率: {len(index) - len(missing_front)}/{len(index)} ({100-pct:.0f}%)")
    else:
        R.ok(f"全カード表面画像あり ({len(index)}枚)")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='ABDS デプロイ前検証')
    parser.add_argument('--quick', action='store_true', help='データ検証のみ(高速)')
    parser.add_argument('--fix', action='store_true', help='自動修正 + 再検証')
    args = parser.parse_args()

    start = time.time()

    print()
    print("  ABDS Pre-Deploy Verification")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    if args.fix:
        print("  --fix: 自動修正を実行中...")
        fix_result = subprocess.run(
            [sys.executable, 'rebuild_index.py', '--full'],
            capture_output=True, text=True, timeout=120
        )
        if fix_result.returncode != 0:
            print(f"  rebuild_index.py 失敗:\n{fix_result.stderr}")
            sys.exit(1)
        lines = fix_result.stdout.strip().split('\n')
        for l in lines[-5:]:
            print(f"    {l}")
        print()

    # Phase 1: ファイル・JSON検証 (必須)
    check_files()
    check_json_validity()

    # Phase 2: データ整合性 (必須)
    check_data_integrity()
    check_version()
    check_cross_consistency()
    check_link_index()
    check_schema_validation()
    check_data_sizes()

    if not args.quick:
        # Phase 3: フィルタ機能テスト
        check_filters()

        # Phase 4: フロントエンド整合
        check_frontend_refs()
        check_images()

        # Phase 5: Git状態
        check_git_status()

    elapsed = time.time() - start

    print(f"\n  Elapsed: {elapsed:.1f}s")
    success = R.summary()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
