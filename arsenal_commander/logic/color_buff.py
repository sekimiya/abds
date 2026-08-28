"""コマンダーカードとユニットカードの色マッチングによるバフ判定。

実際のバフ値はまだ不明なため、色が一致するかどうか（有無）のみを返す。
"""

from typing import Dict, List, Optional, Set
from .constants import COLOR_ORDER, TYPE_CMD, TYPE_MS, TYPE_PL


def get_commander_colors(cmd_number: Optional[str], card_by_number: Dict[str, dict]) -> Set[str]:
    """コマンダーカードの色セットを返す。"""
    if not cmd_number:
        return set()
    card = card_by_number.get(cmd_number)
    if not card or card.get("type") != TYPE_CMD:
        return set()
    return set(card.get("color") or [])


def has_color_buff(
    card_number: Optional[str],
    cmd_colors: Set[str],
    card_by_number: Dict[str, dict],
) -> bool:
    """指定カードがコマンダーの色と 1 つ以上一致すれば True。"""
    if not card_number or not cmd_colors:
        return False
    card = card_by_number.get(card_number)
    if not card or card.get("type") not in (TYPE_MS, TYPE_PL):
        return False
    card_colors = set(card.get("color") or [])
    return bool(card_colors & cmd_colors)


def compute_unit_buffs(
    deck: List[Optional[str]],
    cmd: Optional[str],
    card_by_number: Dict[str, dict],
) -> List[dict]:
    """各ユニット（MS+PL のペア）のバフ状態を返す。"""
    cmd_colors = get_commander_colors(cmd, card_by_number)
    units = []
    for i in range(5):
        ms = deck[i] if i < len(deck) else None
        pl = deck[i + 5] if i + 5 < len(deck) else None
        ms_buff = has_color_buff(ms, cmd_colors, card_by_number)
        pl_buff = has_color_buff(pl, cmd_colors, card_by_number)
        units.append(
            {
                "index": i,
                "ms": ms,
                "pl": pl,
                "ms_buff": ms_buff,
                "pl_buff": pl_buff,
                "unit_buff": ms_buff or pl_buff,
                "matched_colors": [
                    c
                    for c in COLOR_ORDER
                    if c in (set((card_by_number.get(ms) or {}).get("color", [])) & cmd_colors if ms else set())
                ]
                + [
                    c
                    for c in COLOR_ORDER
                    if c in (set((card_by_number.get(pl) or {}).get("color", [])) & cmd_colors if pl else set())
                ],
            }
        )
    return units
