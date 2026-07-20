"""
GAB デッキシミュレーター 指揮官レベル・経験値計算

指揮官の経験値獲得・レベルアップ・拠点/戦艦HP上昇を計算する。
出典: 指揮官レベル (gundamab.swiki.jp)
"""

from typing import Optional

from .constants import (
    COMMANDER_EXP,
    COMMANDER_LEVEL_CAP,
    COMMANDER_HP_BONUS_INTERVAL,
    COMMANDER_HP_BONUS_PER_STEP,
)


def calc_exp_gain(result: str) -> int:
    """勝敗に応じた経験値獲得量を返す。

    出典: 「勝利時+20、引き分けで+15、敗北時+10」

    Args:
        result: 勝敗結果 ('win', 'draw', 'loss')

    Returns:
        獲得経験値
    """
    return COMMANDER_EXP.get(result, 0)


def get_level_cap(season: str) -> int:
    """シーズンごとの指揮官レベル上限を返す。

    出典: S01-S02=40, S03=45, S04=50, LXS01=55, LXS02=60, LXS03=65, LXS04=70

    Args:
        season: シーズン略称 ('S01', 'S02', ..., 'LXS01', ...)

    Returns:
        レベル上限。未知のシーズンは70を返す。
    """
    return COMMANDER_LEVEL_CAP.get(season, 70)


def calc_hp_bonus(level: int) -> int:
    """指揮官レベルによる拠点/戦艦HP上昇量を計算する。

    出典: 「5レベルごとに+5」（自軍拠点または戦艦のHPが上昇）
    NOTE: ユニットのHPではなく、拠点/戦艦のHPが上昇する。

    Args:
        level: 指揮官レベル

    Returns:
        拠点/戦艦HP上昇量
    """
    if level < COMMANDER_HP_BONUS_INTERVAL:
        return 0
    steps = level // COMMANDER_HP_BONUS_INTERVAL
    return steps * COMMANDER_HP_BONUS_PER_STEP
