"""
GAB デッキシミュレーター リンクバフ計算

リンクアビリティのバフ解析・倍率適用を行う。
tests/test_comprehensive.py TestLinkBuffCalculation / TestApplyBuff から移植。
"""

import re
from typing import Optional, List

from .constants import BUFF_MULTIPLIER, BUFF_PATTERNS, BuffSize
from .types import LinkBuffResult
from .utils import get_link_abilities, parse_link_condition, count_for_condition


def get_link_buffs(ocr: Optional[dict], all_ocr_data: List[Optional[dict]]) -> LinkBuffResult:
    """対象カードの発動済みリンクバフカウントを集計する。

    Args:
        ocr: 対象カードのOCRデータ
        all_ocr_data: デッキ全10枚のOCRデータリスト

    Returns:
        各ステータスの小/中バフ発動回数
    """
    buffs: LinkBuffResult = {
        'mobility': {'small': 0, 'medium': 0},
        'ranged': {'small': 0, 'medium': 0},
        'melee': {'small': 0, 'medium': 0},
        'hp': {'small': 0, 'medium': 0},
    }
    if not ocr:
        return buffs

    links = get_link_abilities(ocr)

    for link in links:
        eff = link.get('effect', '')
        condition_str = link.get('condition', '')
        cond = parse_link_condition(condition_str)
        if cond is None:
            continue

        link_name = link.get('name', '')
        count = count_for_condition(cond, link_name, all_ocr_data)

        if count < cond['required']:
            continue

        # エフェクト解析
        for (stat, size), pattern in BUFF_PATTERNS.items():
            if re.search(pattern, eff):
                buffs[stat][size] += 1

    return buffs


def apply_buff(val: int, small: int, medium: int) -> int:
    """ステータス値にバフ倍率を適用する。

    計算式: round(val * 1.1^small * 1.2^medium)

    Args:
        val: ベースステータス値
        small: 小バフの発動回数
        medium: 中バフの発動回数

    Returns:
        バフ適用後のステータス値（四捨五入）
    """
    return round(
        val
        * (BUFF_MULTIPLIER[BuffSize.SMALL] ** small)
        * (BUFF_MULTIPLIER[BuffSize.MEDIUM] ** medium)
    )
