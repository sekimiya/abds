"""
GAB デッキシミュレーター 地形適性集計

MSスロット(0-4)のみの地形適性を集計する。
tests/test_comprehensive.py TestTerrainAggregation から移植。
"""

from typing import Optional, List

from .constants import TERRAIN_RANK_VALUE, MS_SLOT_COUNT
from .types import TerrainResult


def calc_terrain(ocr_data_list: List[Optional[dict]]) -> TerrainResult:
    """MSスロットの地形適性を集計する。

    Args:
        ocr_data_list: デッキ全カードのOCRデータリスト (0-4がMSスロット)

    Returns:
        各地形の表示文字列と最高ランク
    """
    terrains = {'ground': [], 'space': [], 'desert': [], 'water': []}

    for i in range(MS_SLOT_COUNT):
        if i >= len(ocr_data_list):
            break
        ocr = ocr_data_list[i]
        if not ocr or not ocr.get('terrain_compatibility'):
            continue
        tc = ocr['terrain_compatibility']
        for t in ['ground', 'space', 'desert', 'water']:
            if tc.get(t):
                terrains[t].append(tc[t])

    result = {}
    for t, vals in terrains.items():
        if not vals:
            result[t] = {'display': '-', 'best': None}
        else:
            best = sorted(
                set(vals),
                key=lambda x: TERRAIN_RANK_VALUE.get(x, 0),
                reverse=True,
            )[0]
            result[t] = {'display': '/'.join(vals), 'best': best}

    return result
