"""
GAB デッキシミュレーター リンク発動判定

デッキ全体のリンクアビリティ発動状態を集計する。
tests/test_comprehensive.py TestLinkActivation から移植。
"""

from typing import Optional, List, Dict

from .types import LinkActivationInfo
from .utils import get_link_abilities, parse_link_condition, count_for_condition


def calc_link_activation(
    ocr_data_list: List[Optional[dict]],
) -> Dict[str, LinkActivationInfo]:
    """デッキ全体のリンク発動状態を計算する。

    Args:
        ocr_data_list: デッキ全カードのOCRデータリスト

    Returns:
        リンク名をキーとした発動情報辞書
    """
    all_links = {}
    for ocr in ocr_data_list:
        if not ocr:
            continue
        links = get_link_abilities(ocr)
        for link in links:
            name = link.get('name', '')
            if not name:
                continue
            if name not in all_links:
                all_links[name] = {
                    'name': name,
                    'condition': link.get('condition', ''),
                    'effect': link.get('effect', ''),
                    'count': 0,
                }
            all_links[name]['count'] += 1

    result = {}
    for name, link in all_links.items():
        cond = parse_link_condition(link['condition'])
        if cond is not None:
            cnt = count_for_condition(cond, name, ocr_data_list)
            result[name] = {
                'count': cnt,
                'required': cond['required'],
                'active': cnt >= cond['required'],
                'effect': link['effect'],
            }
        else:
            result[name] = {
                'count': link['count'],
                'required': None,
                'active': False,
                'effect': link['effect'],
            }

    return result


def get_active_links(
    ocr_data_list: List[Optional[dict]],
) -> Dict[str, LinkActivationInfo]:
    """発動中のリンクのみを取得する。

    Args:
        ocr_data_list: デッキ全カードのOCRデータリスト

    Returns:
        発動中リンクのみの辞書
    """
    all_links = calc_link_activation(ocr_data_list)
    return {name: info for name, info in all_links.items() if info['active']}
