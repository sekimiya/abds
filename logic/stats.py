"""
GAB デッキシミュレーター ステータス計算

ユニットステータスの合算、コスト計算を行う。
tests/test_comprehensive.py TestUnitStatCalculation / TestTotalCostCalculation から移植。
"""

from typing import Optional, List

from .types import UnitStatResult
from .utils import safe_int, extract_stats
from .buff import get_link_buffs, apply_buff


def calc_unit_stats(
    ms_ocr: Optional[dict],
    pl_ocr: Optional[dict],
    all_ocr_data: List[Optional[dict]],
) -> UnitStatResult:
    """MS+PLの合算ステータスを計算する（バフ適用込み）。

    Args:
        ms_ocr: MSカードのOCRデータ
        pl_ocr: PLカードのOCRデータ
        all_ocr_data: デッキ全10枚のOCRデータリスト

    Returns:
        各ステータスの base/total/buff を含む辞書
    """
    ms = extract_stats(ms_ocr)
    pl = extract_stats(pl_ocr)

    ms_buffs = get_link_buffs(ms_ocr, all_ocr_data)
    pl_buffs = get_link_buffs(pl_ocr, all_ocr_data)

    result = {}
    for stat in ['mobility', 'ranged', 'melee', 'hp']:
        ms_buffed = apply_buff(ms[stat], ms_buffs[stat]['small'], ms_buffs[stat]['medium'])
        pl_buffed = apply_buff(pl[stat], pl_buffs[stat]['small'], pl_buffs[stat]['medium'])
        base = ms[stat] + pl[stat]
        total = ms_buffed + pl_buffed
        buff = total - base
        result[stat] = {'base': base, 'total': total, 'buff': buff}

    return result


def calc_all_unit_stats(
    all_ocr_data: List[Optional[dict]],
) -> List[UnitStatResult]:
    """全5ユニットのステータスを一括計算する。

    Args:
        all_ocr_data: デッキ全10枚のOCRデータリスト (0-4: MS, 5-9: PL)

    Returns:
        5ユニット分のステータス結果リスト
    """
    results = []
    for i in range(5):
        ms_ocr = all_ocr_data[i] if i < len(all_ocr_data) else None
        pl_ocr = all_ocr_data[i + 5] if (i + 5) < len(all_ocr_data) else None
        results.append(calc_unit_stats(ms_ocr, pl_ocr, all_ocr_data))
    return results


def calc_total_cost(ocr_data_list: List[Optional[dict]]) -> int:
    """デッキ総コストを計算する。

    Args:
        ocr_data_list: デッキのOCRデータリスト

    Returns:
        総コスト値
    """
    total = 0
    for ocr in ocr_data_list:
        if ocr and ocr.get('cost') is not None:
            total += safe_int(ocr['cost'])
    return total


def calc_cost_breakdown(ocr_data_list: List[Optional[dict]]) -> dict:
    """デッキのカテゴリ別コスト内訳を計算する。

    Args:
        ocr_data_list: デッキのOCRデータリスト

    Returns:
        {'ms_cost': int, 'pl_cost': int, 'total': int} 形式の辞書
    """
    ms_cost = 0
    pl_cost = 0
    for i, ocr in enumerate(ocr_data_list):
        if not ocr or ocr.get('cost') is None:
            continue
        cost = safe_int(ocr['cost'])
        if i < 5:
            ms_cost += cost
        else:
            pl_cost += cost

    return {
        'ms_cost': ms_cost,
        'pl_cost': pl_cost,
        'total': ms_cost + pl_cost,
    }
