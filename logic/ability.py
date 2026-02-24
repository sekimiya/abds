"""
GAB デッキシミュレーター MSアビリティ分類・SP計算

MSアビリティの分類とSP攻撃情報の取得を行う。
Wiki (gundamab.swiki.jp) のゲームメカニクス情報に基づく。
"""

import re
from typing import Optional, List

from .constants import AbilityActivationType
from .types import MSAbilityInfo, SPAttackInfo
from .utils import safe_int, get_nested


def classify_ability(ms_ocr: Optional[dict]) -> Optional[MSAbilityInfo]:
    """MSアビリティを分類する。

    発動タイプ（任意発動/出撃時発動）とカテゴリを判定する。

    Args:
        ms_ocr: MSカードのOCRデータ

    Returns:
        MSアビリティ情報。アビリティが無い場合はNone。
    """
    if not ms_ocr:
        return None

    ability = ms_ocr.get('ms_ability')
    if not ability:
        return None

    if isinstance(ability, str):
        ability_text = ability
    elif isinstance(ability, dict):
        ability_text = ability.get('name', '') or ability.get('description', '')
    else:
        return None

    if not ability_text:
        return None

    # 発動タイプの判定
    if '出撃時' in ability_text:
        activation_type = AbilityActivationType.ON_DEPLOY.value
    else:
        activation_type = AbilityActivationType.MANUAL.value

    # カテゴリの推定
    category = _detect_ability_category(ability_text)

    info: MSAbilityInfo = {
        'name': ability_text if isinstance(ability, str) else ability.get('name', ability_text),
        'activation_type': activation_type,
        'category': category,
    }

    if isinstance(ability, dict) and ability.get('description'):
        info['description'] = ability['description']

    return info


def _detect_ability_category(text: str) -> str:
    """アビリティテキストからカテゴリを推定する。"""
    if re.search(r'(攻撃力|ダメージ).*アップ', text):
        return 'attack_buff'
    if re.search(r'(防御|ダメージ軽減|HP回復)', text):
        return 'defense'
    if re.search(r'(機動力|移動速度).*アップ', text):
        return 'mobility_buff'
    if re.search(r'(範囲|全体)', text):
        return 'area'
    return 'other'


def get_sp_attack_info(ocr: Optional[dict]) -> Optional[SPAttackInfo]:
    """SP攻撃情報を取得する。

    Args:
        ocr: カードのOCRデータ

    Returns:
        SP攻撃情報。SP攻撃が無い場合はNone。
    """
    if not ocr:
        return None

    sa = ocr.get('special_attack')
    if not sa or not isinstance(sa, dict):
        return None

    info: SPAttackInfo = {}

    if sa.get('name'):
        info['name'] = sa['name']

    if sa.get('power'):
        info['power'] = sa['power']

    if sa.get('description'):
        info['description'] = sa['description']

    cost = sa.get('cost')
    if cost is not None:
        info['cost'] = safe_int(cost)

    return info if info else None


def calc_deck_sp_costs(ocr_data_list: List[Optional[dict]]) -> List[Optional[SPAttackInfo]]:
    """デッキ全カードのSP攻撃情報を一覧で取得する。

    Args:
        ocr_data_list: デッキ全カードのOCRデータリスト

    Returns:
        各スロットのSP攻撃情報リスト
    """
    return [get_sp_attack_info(ocr) for ocr in ocr_data_list]
