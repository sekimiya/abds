#!/usr/bin/env python3
"""OCRデータの統計的異常検知＆レビューレポート生成。

確定的ルール(tests/test_ocr_validity.py)では拾えない「それっぽいが怪しい」
データ（読み違い候補）を統計手法で抽出し、人間のレビュー用レポートを
 data/ocr_quality_report.md に出力する。常に exit 0（CIを落とさない）。

使い方:
  python scripts/check_ocr_anomalies.py              # レポート生成
  python scripts/check_ocr_anomalies.py --stdout     # 標準出力に表示
  python scripts/check_ocr_anomalies.py --top 30     # 各項目の最大出力件数
"""

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DETAILS_PATH = ROOT / "data" / "card_details.json"
REPORT_PATH = ROOT / "data" / "ocr_quality_report.md"

STAT_KEYS = ("mobility", "ranged_attack", "melee_attack", "hp")
DESC_FIELDS = (
    ("ms_ability.description", lambda o: (o.get("ms_ability") or {}).get("description")),
    ("special_attack.description", lambda o: (o.get("special_attack") or {}).get("description")),
    ("pilot_skill.effect", lambda o: (o.get("pilot_skill") or {}).get("effect")),
)
MIN_DESC_LEN = 10


def iqr_bounds(values, k=1.5):
    """IQRベースの外れ値境界 (lower, upper) を返す"""
    if len(values) < 8:
        return None, None
    qs = statistics.quantiles(values, n=4)
    q1, q3 = qs[0], qs[2]
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def check_stat_outliers(cards):
    """ステータス・コストのIQR外れ値（type別）"""
    findings = []
    for ctype in ("MS", "PL"):
        subset = [(num, ocr) for num, ocr in cards if ocr.get("type") == ctype]
        for key in STAT_KEYS + ("cost",):
            values = [ocr.get("stats", {}).get(key) if key != "cost" else ocr.get("cost")
                      for _, ocr in subset]
            pairs = [(num, v) for (num, _), v in zip(subset, values)
                     if isinstance(v, int)]
            lo, hi = iqr_bounds([v for _, v in pairs])
            if lo is None:
                continue
            for num, v in pairs:
                if v < lo or v > hi:
                    findings.append(("warning", num, f"{key}={v} が {ctype} 分布の外れ値"
                                     f" (正常域 {lo:.0f}〜{hi:.0f})"))
    return findings


def check_cost_efficiency(cards):
    """コスト対ステータス合計の効率外れ値（MSのみ。読み違い候補）"""
    ratios = []
    for num, ocr in cards:
        if ocr.get("type") != "MS":
            continue
        cost, stats = ocr.get("cost"), ocr.get("stats") or {}
        total = sum(v for v in stats.values() if isinstance(v, int))
        if isinstance(cost, int) and cost > 0 and total > 0:
            ratios.append((num, cost, total, total / cost))
    lo, hi = iqr_bounds([r for *_, r in ratios])
    findings = []
    if lo is not None:
        for num, cost, total, r in ratios:
            if r < lo or r > hi:
                findings.append(("review", num,
                                 f"ステ合計{cost}コストあたり効率 {r:.0f} (合計{total})"
                                 f" が分布外 (正常域 {lo:.0f}〜{hi:.0f})"))
    return findings


def check_short_descriptions(cards):
    """説明文が空/極端に短いフィールド（読み落とし候補）"""
    findings = []
    for num, ocr in cards:
        for field, getter in DESC_FIELDS:
            desc = getter(ocr)
            parent = field.split(".")[0]
            if ocr.get(parent) is None:
                continue  # セクション自体が無いカードは対象外
            if desc is None:
                continue
            text = (desc or "").strip()
            if len(text) < MIN_DESC_LEN:
                findings.append(("review", num,
                                 f"{field} が短すぎ/空 ({len(text)}文字): {text!r}"))
    return findings


def check_parallel_stat_mismatch(cards):
    """パラレル/イラスト違いカード（同一ベース番号の _pN 版）で
    ステータスが異なるもの。同名の別シリーズカードは別物なので対象外。"""
    by_base = defaultdict(list)
    for num, ocr in cards:
        if ocr.get("stats"):
            by_base[num.split("_")[0]].append((num, ocr["stats"]))
    findings = []
    for base, group in by_base.items():
        if len(group) < 2:
            continue
        base_num, base_stats = group[0]
        for num, stats in group[1:]:
            if stats != base_stats:
                diffs = {k: (base_stats.get(k), stats.get(k)) for k in STAT_KEYS
                         if base_stats.get(k) != stats.get(k)}
                findings.append(("review", num,
                                 f"ベースカード {base_num} とステータス差異: {diffs}"))
    return findings


def check_link_count(cards):
    """リンクアビリティが2件でない実カード（品質レビュー対象）"""
    findings = []
    for num, ocr in cards:
        if num.startswith("TEST-"):
            continue
        la = ocr.get("link_ability") or []
        if len(la) != 2:
            findings.append(("review", num, f"リンクアビリティ {len(la)} 件"))
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stdout", action="store_true", help="ファイルに書かず標準出力へ")
    ap.add_argument("--top", type=int, default=20, help="各セクションの最大出力件数")
    ap.add_argument("--output", default=str(REPORT_PATH), help="出力先パス")
    args = ap.parse_args()

    with open(DETAILS_PATH, encoding="utf-8") as f:
        details = json.load(f)
    cards = sorted(((num, e.get("ocr_data") or {}) for num, e in details.items()),
                   key=lambda x: x[0])

    sections = [
        ("ステータス/コストの外れ値 (IQR)", check_stat_outliers(cards)),
        ("コスト効率の外れ値 (MS)", check_cost_efficiency(cards)),
        ("説明文の欠落・極短", check_short_descriptions(cards)),
        ("パラレルカードのステータス不整合", check_parallel_stat_mismatch(cards)),
        ("リンクアビリティ件数 != 2", check_link_count(cards)),
    ]

    lines = [
        "# OCR品質レビューレポート",
        "",
        f"生成: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        f" / 対象: {len(cards)} カード",
        "",
        "統計的異常検知によるレビュー候補一覧。"
        "確定的エラーは tests/test_ocr_validity.py (CI) が検出する。",
        "このファイルは scripts/check_ocr_anomalies.py で再生成される。",
        "",
        "| 重要度 | 意味 |",
        "|---|---|",
        "| warning | 分布から大きく外れた値。OCR読み違いの可能性が高い |",
        "| review | 軽微な異常。正しい可能性もあるが目視推奨 |",
        "",
    ]
    total = 0
    for title, findings in sections:
        total += len(findings)
        lines.append(f"## {title} ({len(findings)} 件)")
        lines.append("")
        if not findings:
            lines.append("なし")
        else:
            for sev, num, msg in findings[: args.top]:
                lines.append(f"- **[{sev}]** `{num}` — {msg}")
            if len(findings) > args.top:
                lines.append(f"- ... 他 {len(findings) - args.top} 件")
        lines.append("")
    lines.insert(4, f"**検出合計: {total} 件**")

    report = "\n".join(lines) + "\n"
    if args.stdout:
        print(report)
    else:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"レポート出力: {args.output} ({total} 件)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
