"""デッキの表示用ステータス集計。"""

from typing import Dict, List, Optional
from .color_buff import compute_unit_buffs, get_commander_colors
from .constants import COLOR_ORDER, TYPE_MS, TYPE_PL, CATEGORY_SENMETSU, CATEGORY_SEIATSU, CATEGORY_BOUEI


def compute_deck_stats(
    deck: List[Optional[str]],
    cmd: Optional[str],
    card_by_number: Dict[str, dict],
) -> dict:
    """フロント表示用の集計情報を返す。"""
    total_cost = 0
    category_counts = {CATEGORY_SENMETSU: 0, CATEGORY_SEIATSU: 0, CATEGORY_BOUEI: 0}

    units = []
    cmd_colors = get_commander_colors(cmd, card_by_number)

    for i in range(5):
        ms_num = deck[i] if i < len(deck) else None
        pl_num = deck[i + 5] if i + 5 < len(deck) else None
        ms = card_by_number.get(ms_num) if ms_num else None
        pl = card_by_number.get(pl_num) if pl_num else None

        ms_atk = ms.get("atk") if ms and "atk" in ms else None
        ms_hp = ms.get("hp") if ms and "hp" in ms else None
        pl_atk = pl.get("atk") if pl and "atk" in pl else None
        pl_hp = pl.get("hp") if pl and "hp" in pl else None

        if ms:
            if "cost" in ms and ms["cost"] is not None:
                total_cost += ms["cost"]
            cat = ms.get("category")
            if cat in category_counts:
                category_counts[cat] += 1
        if pl:
            if "cost" in pl and pl["cost"] is not None:
                total_cost += pl["cost"]
            cat = pl.get("category")
            if cat in category_counts:
                category_counts[cat] += 1

        ms_match = ms and set(ms.get("color") or []) & cmd_colors
        pl_match = pl and set(pl.get("color") or []) & cmd_colors

        def _sum(a, b):
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        units.append(
            {
                "index": i,
                "ms": {"number": ms_num, "name": ms.get("name") if ms else None, "atk": ms_atk, "hp": ms_hp, "buff": bool(ms_match)},
                "pl": {"number": pl_num, "name": pl.get("name") if pl else None, "atk": pl_atk, "hp": pl_hp, "buff": bool(pl_match)},
                "total_atk": _sum(ms_atk, pl_atk),
                "total_hp": _sum(ms_hp, pl_hp),
                "buff": bool(ms_match or pl_match),
            }
        )

    return {
        "total_cost": total_cost,
        "category_counts": category_counts,
        "commander_colors": [c for c in COLOR_ORDER if c in cmd_colors],
        "units": units,
    }
