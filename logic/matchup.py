"""
GAB デッキシミュレーター タイプ相性

殲滅/制圧/防衛の3すくみダメージ倍率を計算する。

出典:
  - 初心者用ガイド (gundamab.swiki.jp): 防衛軽減「あらゆる受けるダメージが0.2倍」
  - タイプ相性倍率: 公式に未公開（プランの仮値を使用）
"""

from typing import Optional, List

from .constants import CombatStyle, TYPE_MATCHUP, DEFENSE_BASE_DAMAGE_MULTIPLIER


def get_type_multiplier(attacker: str, defender: str) -> float:
    """攻撃側・防御側のタイプ相性からダメージ倍率を返す。

    Args:
        attacker: 攻撃側タイプ ('殲滅', '制圧', '防衛')
        defender: 防御側タイプ ('殲滅', '制圧', '防衛')

    Returns:
        ダメージ倍率 (1.0 = 等倍, 2.0 = 有利, 0.7 = 不利)
    """
    try:
        atk = CombatStyle(attacker)
        dfd = CombatStyle(defender)
    except ValueError:
        return 1.0
    return TYPE_MATCHUP.get((atk, dfd), 1.0)


def calc_defense_base_damage(base_damage: float) -> float:
    """防衛ユニット付近の拠点/戦艦が受けるダメージを計算する。

    出典: 「防衛タイプのユニットが拠点/戦艦付近にいる場合、
    あらゆる受けるダメージが0.2倍になる」

    Args:
        base_damage: 元のダメージ値

    Returns:
        軽減後のダメージ値（元の0.2倍）
    """
    return base_damage * DEFENSE_BASE_DAMAGE_MULTIPLIER


def analyze_deck_matchup(
    my_ocr_list: List[Optional[dict]],
    enemy_style: str,
) -> dict:
    """デッキの対戦タイプ相性を分析する。

    自デッキの各ユニットが敵タイプに対してどの倍率で攻撃できるかを算出する。

    Args:
        my_ocr_list: 自デッキのOCRデータリスト
        enemy_style: 敵のタイプ ('殲滅', '制圧', '防衛')

    Returns:
        分析結果 {'units': [...], 'advantage_count': int, 'disadvantage_count': int}
    """
    units = []
    advantage_count = 0
    disadvantage_count = 0

    for i, ocr in enumerate(my_ocr_list):
        if not ocr:
            units.append(None)
            continue

        my_style = ocr.get('category', '')
        multiplier = get_type_multiplier(my_style, enemy_style)

        if multiplier > 1.0:
            advantage_count += 1
            relation = 'advantage'
        elif multiplier < 1.0:
            disadvantage_count += 1
            relation = 'disadvantage'
        else:
            relation = 'neutral'

        units.append({
            'slot': i,
            'style': my_style,
            'multiplier': multiplier,
            'relation': relation,
        })

    return {
        'units': units,
        'advantage_count': advantage_count,
        'disadvantage_count': disadvantage_count,
        'enemy_style': enemy_style,
    }
