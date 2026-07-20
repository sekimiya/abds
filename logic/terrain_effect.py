"""
GAB デッキシミュレーター 地形戦闘効果

地形適性ランクに応じたステータス補正を計算する。
Wiki (gundamab.swiki.jp) のゲームメカニクス情報に基づく。
"""

from typing import Optional

from .constants import TerrainRank, TERRAIN_EFFECT_MULTIPLIER, TERRAIN_RANK_VALUE
from .utils import extract_stats


def apply_terrain_effect(ms_ocr: Optional[dict], terrain: str) -> dict:
    """地形効果を適用したステータスを計算する。

    MSの地形適性ランクに応じてステータスに倍率を適用する。
    S=1.15, A=1.05, B=1.0, C=0.90, D=0.80

    Args:
        ms_ocr: MSカードのOCRデータ
        terrain: 地形タイプ ('ground', 'space', 'desert', 'water')

    Returns:
        地形効果適用後のステータス辞書
    """
    base_stats = extract_stats(ms_ocr)
    rank = get_terrain_compatibility_rank(ms_ocr, terrain)

    if rank is None:
        return base_stats

    try:
        rank_enum = TerrainRank(rank)
    except ValueError:
        return base_stats

    multiplier = TERRAIN_EFFECT_MULTIPLIER.get(rank_enum, 1.0)

    return {
        stat: round(val * multiplier)
        for stat, val in base_stats.items()
    }


def get_terrain_compatibility_rank(ms_ocr: Optional[dict], terrain: str) -> Optional[str]:
    """MSの地形適性ランクを取得する。

    Args:
        ms_ocr: MSカードのOCRデータ
        terrain: 地形タイプ ('ground', 'space', 'desert', 'water')

    Returns:
        地形適性ランク ('S', 'A', 'B', 'C', 'D') またはNone
    """
    if not ms_ocr:
        return None
    tc = ms_ocr.get('terrain_compatibility')
    if not tc or not isinstance(tc, dict):
        return None
    rank = tc.get(terrain)
    if rank in ('S', 'A', 'B', 'C', 'D'):
        return rank
    return None
