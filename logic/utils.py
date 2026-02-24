"""
GAB デッキシミュレーター ユーティリティ

OCRデータの安全な取得、型変換、キー揺れ吸収を担う。
app.py の _safe_int / get_nested を移植。
"""

import re
from typing import Any, List, Optional

from .constants import OCR_STAT_KEY_MAP, LINK_CONDITION_CATEGORY_MAP
from .types import LinkCondition


def safe_int(val: Any, default: int = 0) -> int:
    """値を安全にintに変換する。変換不可時はdefaultを返す。"""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_nested(d: dict, keys: List[str], default: Any = None) -> Any:
    """dictから多段キーで安全に値を取得する。"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def extract_stats(ocr: Optional[dict]) -> dict:
    """OCRデータからステータス値を正規化して取得する。

    OCRキーの揺れ (ranged_attack/ranged, melee_attack/melee) を吸収し、
    統一された {mobility, ranged, melee, hp} の形式で返す。
    """
    if not ocr or not ocr.get('stats'):
        return {'mobility': 0, 'ranged': 0, 'melee': 0, 'hp': 0}
    s = ocr['stats']
    return {
        'mobility': safe_int(s.get('mobility')),
        'ranged': safe_int(s.get('ranged_attack', s.get('ranged'))),
        'melee': safe_int(s.get('melee_attack', s.get('melee'))),
        'hp': safe_int(s.get('hp')),
    }


def get_link_abilities(ocr: Optional[dict]) -> list:
    """OCRデータからリンクアビリティリストを取得する。

    link_abilities / link_ability の両キーに対応。
    """
    if not ocr:
        return []
    links = ocr.get('link_abilities') or ocr.get('link_ability') or []
    if not isinstance(links, list):
        return []
    return links


def parse_link_condition(condition: str) -> Optional[LinkCondition]:
    """リンク条件文字列から必要枚数とカテゴリフィルタを抽出する。

    対応パターン:
      - "デッキにN枚以上" / "デッキにN体以上" → {required: N, category_filter: None}
      - "デッキに{category}(が)N枚以上" → {required: N, category_filter: "機動"等}
    パースできない場合はNoneを返す。
    """
    m = re.search(r'(?:デッキに)?(.+?)(?:が|の)?(\d+)(?:枚|体)以上', condition)
    if not m:
        return None
    prefix = m.group(1).strip()
    required = int(m.group(2))
    category_filter = LINK_CONDITION_CATEGORY_MAP.get(prefix)
    return {'required': required, 'category_filter': category_filter}


def get_card_style(ocr: Optional[dict]) -> Optional[str]:
    """カードの有効カテゴリ/戦闘スタイルを返す。

    MS: category フィールド (機動/遠距離/近距離)
    PL: card_label.class フィールド (殲滅/制圧/防衛), fallback to category
    """
    if not ocr:
        return None
    if ocr.get('type') == 'PL':
        cls = get_nested(ocr, ['card_label', 'class'])
        if cls in ('殲滅', '制圧', '防衛'):
            return cls
        cat = ocr.get('category')
        if cat in ('殲滅', '制圧', '防衛'):
            return cat
        return None
    return ocr.get('category') or None


def count_for_condition(
    cond: LinkCondition,
    link_name: str,
    ocr_data_list: List[Optional[dict]],
) -> int:
    """リンク条件に応じたカウントを返す。

    category_filter がある場合: デッキ内の該当カテゴリ枚数でカウント
    category_filter がない場合: 同名リンク名を持つカード枚数でカウント
    """
    if cond.get('category_filter'):
        return sum(
            1 for d in ocr_data_list
            if d and get_card_style(d) == cond['category_filter']
        )
    count = 0
    for d in ocr_data_list:
        if not d:
            continue
        d_links = get_link_abilities(d)
        if any(l.get('name') == link_name for l in d_links):
            count += 1
    return count
