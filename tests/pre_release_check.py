#!/usr/bin/env python3
"""
ABDS プリリリースデータチェッカー

リリース前にcard_index.json / card_details.json / link_index.jsonの
整合性・品質を自動検証するスクリプト。

Usage:
    python tests/pre_release_check.py
    python tests/pre_release_check.py --data-dir data/
    python tests/pre_release_check.py -c C        # リンク検証のみ
    python tests/pre_release_check.py -v           # 全警告表示
    python tests/pre_release_check.py --json       # JSON出力
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Result accumulator
# ---------------------------------------------------------------------------

class CheckResult:
    def __init__(self):
        self.errors: list[tuple[str, str, str]] = []
        self.warnings: list[tuple[str, str, str]] = []
        self._category_labels: dict[str, str] = {}

    def error(self, category: str, card: str, msg: str):
        self.errors.append((category, card, msg))

    def warning(self, category: str, card: str, msg: str):
        self.warnings.append((category, card, msg))

    def set_label(self, cat_id: str, label: str):
        self._category_labels[cat_id] = label

    @property
    def has_errors(self):
        return len(self.errors) > 0

    def _group(self, items):
        grouped = defaultdict(list)
        for cat, card, msg in items:
            grouped[cat].append((card, msg))
        return grouped

    def print_report(self, verbose=False, as_json=False, card_count=0, detail_count=0, link_count=0):
        if as_json:
            self._print_json(card_count, detail_count, link_count)
            return

        print("=" * 60)
        print("  ABDS Pre-Release Check")
        print("=" * 60)
        print(f"Cards: {card_count} (index) / {detail_count} (details) / {link_count} (links)")
        print()

        all_cats = sorted(set(
            [c for c, _, _ in self.errors] + [c for c, _, _ in self.warnings]
        ))
        err_g = self._group(self.errors)
        warn_g = self._group(self.warnings)

        for cat in sorted(self._category_labels.keys()):
            label = self._category_labels[cat]
            e = len(err_g.get(cat, []))
            w = len(warn_g.get(cat, []))
            status = "FAIL" if e > 0 else ("WARN" if w > 0 else "OK")
            mark = {"FAIL": "x", "WARN": "!", "OK": "o"}[status]
            print(f"  [{mark}] [{cat}] {label:30s}  {e} errors, {w} warnings")
        print()

        if self.errors:
            print("-" * 60)
            print(f"  ERRORS ({len(self.errors)})")
            print("-" * 60)
            for cat in sorted(err_g.keys()):
                label = self._category_labels.get(cat, cat)
                print(f"\n  [{cat}] {label}:")
                for card, msg in err_g[cat]:
                    print(f"    {card}: {msg}")
            print()

        if self.warnings and (verbose or len(self.warnings) <= 30):
            print("-" * 60)
            print(f"  WARNINGS ({len(self.warnings)})")
            print("-" * 60)
            for cat in sorted(warn_g.keys()):
                label = self._category_labels.get(cat, cat)
                items = warn_g[cat]
                print(f"\n  [{cat}] {label} ({len(items)}):")
                show = items if verbose else items[:10]
                for card, msg in show:
                    print(f"    {card}: {msg}")
                if not verbose and len(items) > 10:
                    print(f"    ... (+{len(items) - 10} more, use -v to show all)")
        elif self.warnings:
            print(f"  {len(self.warnings)} warnings (use -v to show details)")

        print()
        print("=" * 60)
        if self.has_errors:
            print(f"  RESULT: FAIL  ({len(self.errors)} errors, {len(self.warnings)} warnings)")
        else:
            print(f"  RESULT: PASS  ({len(self.warnings)} warnings)")
        print("=" * 60)

    def _print_json(self, card_count, detail_count, link_count):
        out = {
            "status": "fail" if self.has_errors else "pass",
            "counts": {
                "index": card_count, "details": detail_count, "links": link_count,
                "errors": len(self.errors), "warnings": len(self.warnings),
            },
            "errors": [{"category": c, "card": n, "message": m} for c, n, m in self.errors],
            "warnings": [{"category": c, "card": n, "message": m} for c, n, m in self.warnings],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(data_dir: str):
    d = Path(data_dir)
    with open(d / "card_index.json", encoding="utf-8") as f:
        index = json.load(f)
    with open(d / "card_details.json", encoding="utf-8") as f:
        details = json.load(f)
    link_path = d / "link_index.json"
    link_index = {}
    if link_path.exists():
        with open(link_path, encoding="utf-8") as f:
            link_index = json.load(f)
    return index, details, link_index


# ---------------------------------------------------------------------------
# [A] Cross-File Consistency
# ---------------------------------------------------------------------------

def check_cross_file_consistency(index, details, r: CheckResult):
    cat = "A"
    r.set_label(cat, "Cross-File Consistency")

    idx_map = {c["number"]: c for c in index}
    idx_numbers = set(idx_map.keys())
    det_numbers = set(details.keys())

    for num in sorted(idx_numbers - det_numbers):
        r.error(cat, num, "index に存在するが details に存在しない")

    for num in sorted(det_numbers - idx_numbers):
        r.error(cat, num, "details に存在するが index に存在しない")

    dups = [n for n, cnt in defaultdict(int, {c["number"]: sum(1 for x in index if x["number"] == c["number"]) for c in index}).items() if cnt > 1]
    # Efficient duplicate check
    seen = {}
    for c in index:
        num = c["number"]
        if num in seen:
            if num not in [d[1] for d in r.errors if "重複" in d[2]]:
                r.error(cat, num, "card_index に重複エントリ")
        seen[num] = True

    for num in sorted(idx_numbers & det_numbers):
        ic = idx_map[num]
        ocr = details[num].get("ocr_data") or {}
        if not ocr:
            continue

        if ic.get("has_ocr") and not ocr:
            r.error(cat, num, "has_ocr=true だが ocr_data が空")

        idx_type = ic.get("type", "")
        ocr_type = ocr.get("type", "")
        if idx_type and ocr_type and idx_type != ocr_type:
            r.error(cat, num, f"type 不一致: index={idx_type}, details={ocr_type}")

        idx_cost = ic.get("cost")
        ocr_cost = ocr.get("cost")
        if idx_cost is not None and ocr_cost is not None and idx_cost != ocr_cost:
            r.error(cat, num, f"cost 不一致: index={idx_cost}, details={ocr_cost}")

        idx_rarity = ic.get("rarity")
        ocr_rarity = ocr.get("rarity")
        if idx_rarity and ocr_rarity and idx_rarity != ocr_rarity:
            r.warning(cat, num, f"rarity 不一致: index={idx_rarity}, details={ocr_rarity}")


# ---------------------------------------------------------------------------
# [B] OCR Completeness
# ---------------------------------------------------------------------------

def check_ocr_completeness(index, details, r: CheckResult):
    cat = "B"
    r.set_label(cat, "OCR Completeness")

    idx_map = {c["number"]: c for c in index}
    no_ocr_cards = []

    for num, d in sorted(details.items()):
        ic = idx_map.get(num, {})
        ocr = d.get("ocr_data") or {}
        has_ocr_flag = ic.get("has_ocr", False)

        if has_ocr_flag and not ocr:
            r.error(cat, num, "has_ocr=true だが ocr_data が空")
        elif not has_ocr_flag and not ocr:
            no_ocr_cards.append(num)
            continue
        elif not has_ocr_flag and ocr:
            r.warning(cat, num, "has_ocr=false だが ocr_data が存在する")

        if not ocr:
            continue

        if not ocr.get("type"):
            r.error(cat, num, "ocr_data に type が未設定")
        if not ocr.get("name"):
            r.error(cat, num, "ocr_data に name が未設定")
        if ocr.get("cost") is None:
            r.error(cat, num, "ocr_data に cost が未設定")

        stats = ocr.get("stats") or {}
        stat_vals = [stats.get(k, 0) or 0 for k in ("mobility", "ranged_attack", "ranged", "melee_attack", "melee", "hp")]
        if all(v == 0 for v in stat_vals):
            r.error(cat, num, "stats が全て0またはnull")

        if not ocr.get("rarity"):
            r.warning(cat, num, "rarity が未設定")

    if no_ocr_cards:
        for nc in no_ocr_cards:
            r.error(cat, nc, "has_ocr=false: OCR未実施")
        r.error(cat, "-", f"OCR未実施カード合計 {len(no_ocr_cards)}枚")


# ---------------------------------------------------------------------------
# [C] Link Ability Validation
# ---------------------------------------------------------------------------

EFFECT_PATTERN = re.compile(r"\[.+?\].*(?:アップ|ダウン)")
CONDITION_PATTERN = re.compile(r"デッキに|同じ|以上|装備")

KNOWN_GENERIC_LINKS = {
    "的確な一撃", "多彩な戦術", "肉薄する戦い", "戦況を変える力",
    "堅牢な守り", "不屈の闘志", "鉄壁の防御", "電光石火",
    "間合いを詰めた接近戦", "距離をとった射撃戦", "優れた射撃センス",
    "優れた格闘センス", "揺るがぬ意志", "その名はガンダム",
    "圧倒する殲滅力", "迫撃の近距離戦", "実弾の突破力", "固めた装甲",
    "トランザムの真価", "ニュータイプの潜在能力", "可変機ファイター",
    "巧みな連携戦術", "万全の制圧態勢", "撃ち倒す遠距離戦",
    "数奇な運命", "陸戦特化の戦い", "赤のプライド", "専用機の実力",
    "最優先の任務", "漆黒の戦士", "機動で制する射撃戦", "優秀な士官",
    "高速機動の接近戦", "徹底した防衛陣",
}


def check_link_abilities(details, link_index, r: CheckResult):
    cat = "C"
    r.set_label(cat, "Link Ability Validation")

    for num, d in sorted(details.items()):
        ocr = d.get("ocr_data") or {}
        la = ocr.get("link_abilities") or ocr.get("link_ability") or []
        if not la:
            continue

        for i, link in enumerate(la):
            if not isinstance(link, dict):
                r.error(cat, num, f"link[{i}] が dict でない: {type(link).__name__}")
                continue

            name = link.get("name", "")
            cond = link.get("condition", "")
            effect = link.get("effect", "")

            if not name:
                r.error(cat, num, f"link[{i}] name が空")
            if not cond:
                r.warning(cat, num, f"link[{i}] condition が空")
            if not effect:
                r.warning(cat, num, f"link[{i}] effect が空")

            # Field rotation detection
            if EFFECT_PATTERN.search(name):
                r.error(cat, num, f'link[{i}] name にエフェクト値: "{name}" (name/condition/effect入替)')
            if cond and not CONDITION_PATTERN.search(cond) and EFFECT_PATTERN.search(cond):
                r.error(cat, num, f'link[{i}] condition にエフェクト値: "{cond}"')
            if effect and CONDITION_PATTERN.search(effect) and not EFFECT_PATTERN.search(effect):
                r.error(cat, num, f'link[{i}] effect にコンディション値: "{effect}"')

        # Link order: pos0=series link, pos1=generic link
        if len(la) >= 2 and isinstance(la[0], dict) and isinstance(la[1], dict):
            name0 = la[0].get("name", "")
            name1 = la[1].get("name", "")
            if name0 in KNOWN_GENERIC_LINKS and name1 not in KNOWN_GENERIC_LINKS:
                r.warning(cat, num, f"リンク順序が逆: [{name0}] / [{name1}] (汎用が先)")

    # link_index cross-reference
    all_detail_numbers = set(details.keys())
    for link_name, link_data in link_index.items():
        for card_num in link_data.get("ms_cards", []) + link_data.get("pl_cards", []):
            if card_num not in all_detail_numbers:
                r.warning(cat, card_num, f'link_index "{link_name}" が参照するが details に存在しない')


# ---------------------------------------------------------------------------
# [D] MS Field Validation
# ---------------------------------------------------------------------------

VALID_MS_CATEGORIES = {"機動", "遠距離", "近距離"}
VALID_TERRAIN = {"", "S", "A", "B", "C", "D", None}


def check_ms_fields(details, r: CheckResult):
    cat = "D"
    r.set_label(cat, "MS Field Validation")

    for num, d in sorted(details.items()):
        ocr = d.get("ocr_data") or {}
        if ocr.get("type") != "MS":
            continue

        cost = ocr.get("cost") or 0

        # Weapon
        weapon = ocr.get("weapon")
        if not weapon:
            r.warning(cat, num, "weapon が未設定")
        elif not isinstance(weapon, dict):
            r.error(cat, num, f"weapon が dict でない: {type(weapon).__name__}")
        else:
            main_w = weapon.get("main") or {}
            if not main_w.get("name"):
                r.warning(cat, num, "weapon.main.name が未設定")

        # Terrain
        terrain = ocr.get("terrain_compatibility")
        if not terrain:
            r.warning(cat, num, "terrain_compatibility が未設定")
        elif isinstance(terrain, dict):
            for k in ("ground", "space"):
                val = terrain.get(k)
                if val not in VALID_TERRAIN:
                    r.warning(cat, num, f"terrain.{k} が不正値: {val}")

        # MS Ability
        ms_ab = ocr.get("ms_ability")
        if not ms_ab and cost >= 4:
            r.warning(cat, num, f"コスト{cost}だが ms_ability が未設定")
        elif isinstance(ms_ab, dict):
            if not ms_ab.get("name"):
                r.warning(cat, num, "ms_ability.name が未設定")
            if not ms_ab.get("description"):
                r.warning(cat, num, "ms_ability.description が未設定")

        # Category
        ms_cat = ocr.get("category", "")
        if ms_cat and ms_cat not in VALID_MS_CATEGORIES:
            r.warning(cat, num, f'MS category が不正: "{ms_cat}"')

        # Stat range check
        stats = ocr.get("stats") or {}
        for k in ("mobility", "ranged_attack", "melee_attack", "hp"):
            v = stats.get(k)
            if v is None:
                continue
            if not isinstance(v, (int, float)):
                continue
            if v < 0:
                r.error(cat, num, f"stats.{k} が負の値: {v}")
            if v > 999:
                r.warning(cat, num, f"stats.{k} が異常に大きい: {v}")


# ---------------------------------------------------------------------------
# [E] PL Field Validation
# ---------------------------------------------------------------------------

VALID_PL_STYLES = {"殲滅", "制圧", "防衛"}


def check_pl_fields(details, r: CheckResult):
    cat = "E"
    r.set_label(cat, "PL Field Validation")

    for num, d in sorted(details.items()):
        ocr = d.get("ocr_data") or {}
        if ocr.get("type") != "PL":
            continue

        # Pilot Skill
        ps = ocr.get("pilot_skill") or ocr.get("pl_skill")
        if not ps:
            r.warning(cat, num, "pilot_skill が未設定")
        elif isinstance(ps, dict):
            if not ps.get("name"):
                r.warning(cat, num, "pilot_skill.name が未設定")
            eff = ps.get("effect") or ps.get("description") or ""
            if not eff:
                r.warning(cat, num, "pilot_skill.effect が未設定")

        # Category / combat style
        pl_cat = ocr.get("category", "")
        card_label = ocr.get("card_label") or {}
        pl_class = card_label.get("class", "")
        effective_style = pl_class or pl_cat
        if effective_style and effective_style not in VALID_PL_STYLES:
            # series name in category is a known pattern, only warn if class is also wrong
            if pl_class and pl_class not in VALID_PL_STYLES:
                r.warning(cat, num, f'PL combat style が不正: class="{pl_class}"')

        # Stat range check
        stats = ocr.get("stats") or {}
        for k in ("mobility", "ranged_attack", "melee_attack", "hp"):
            v = stats.get(k)
            if v is None:
                continue
            if isinstance(v, (int, float)) and v < 0:
                r.error(cat, num, f"stats.{k} が負の値: {v}")


# ---------------------------------------------------------------------------
# [F] Parallel Card & Suspicious OCR
# ---------------------------------------------------------------------------

def check_suspicious_ocr(index, details, r: CheckResult):
    cat = "F"
    r.set_label(cat, "Suspicious OCR / Parallel Cards")

    idx_map = {c["number"]: c for c in index}
    p_re = re.compile(r"^(.+?)_p\d+$")

    for num, d in sorted(details.items()):
        ocr = d.get("ocr_data") or {}

        # Parallel card checks
        m = p_re.match(num)
        if m:
            base_num = m.group(1)
            base_d = details.get(base_num)
            if not base_d:
                r.warning(cat, num, f"ベースカード {base_num} が details に存在しない（コラボ限定等）")
                continue
            base_ocr = base_d.get("ocr_data") or {}

            if base_ocr and not ocr:
                r.error(cat, num, "ベースカードにOCRデータがあるがパラレルにはない")
            if ocr.get("type") and base_ocr.get("type") and ocr["type"] != base_ocr["type"]:
                r.error(cat, num, f"type がベースと不一致: {ocr['type']} vs {base_ocr['type']}")

            base_la = base_ocr.get("link_abilities") or base_ocr.get("link_ability") or []
            para_la = ocr.get("link_abilities") or ocr.get("link_ability") or []
            if base_la and not para_la:
                r.warning(cat, num, "ベースカードにリンクがあるがパラレルにはない")

        if not ocr:
            continue

        # Cost range
        cost = ocr.get("cost")
        if cost is not None:
            if isinstance(cost, (int, float)):
                if cost < 0 or cost > 13:
                    r.error(cat, num, f"cost が範囲外: {cost}")

        # Negative stats
        stats = ocr.get("stats") or {}
        for k, v in stats.items():
            if isinstance(v, (int, float)) and v < 0:
                r.error(cat, num, f"stats.{k} が負の値: {v}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ABDS pre-release data checker")
    parser.add_argument("--data-dir", default="data/", help="Path to data directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all warnings")
    parser.add_argument("--category", "-c", choices=["A", "B", "C", "D", "E", "F", "all"],
                        default="all", help="Run specific check category")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        index, details, link_index = load_data(args.data_dir)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    r = CheckResult()

    checks = {
        "A": (check_cross_file_consistency, (index, details, r)),
        "B": (check_ocr_completeness, (index, details, r)),
        "C": (check_link_abilities, (details, link_index, r)),
        "D": (check_ms_fields, (details, r)),
        "E": (check_pl_fields, (details, r)),
        "F": (check_suspicious_ocr, (index, details, r)),
    }

    for cat_id, (fn, fn_args) in checks.items():
        if args.category == "all" or args.category == cat_id:
            fn(*fn_args)

    r.print_report(
        verbose=args.verbose,
        as_json=args.json,
        card_count=len(index),
        detail_count=len(details),
        link_count=len(link_index),
    )
    sys.exit(1 if r.has_errors else 0)


if __name__ == "__main__":
    main()
