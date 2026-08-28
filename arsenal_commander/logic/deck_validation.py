"""デッキ構築ルールの検証。"""

from typing import Dict, List, Optional
from .constants import DECK_SIZE, MS_SLOTS, PL_SLOTS, TYPE_MS, TYPE_PL, TYPE_CMD


def validate_deck(
    deck: List[Optional[str]],
    cmd: Optional[str],
    card_by_number: Dict[str, dict],
) -> dict:
    """デッキの合法性を検証する。

    Returns:
        {
            "valid": bool,
            "errors": [str],
            "warnings": [str],
            "cost": int,
        }
    """
    errors = []
    warnings = []

    if len(deck) != DECK_SIZE:
        errors.append(f"デッキは {DECK_SIZE} 枚である必要があります（現在 {len(deck)} 枚）")

    total_cost = 0
    ms_count = 0
    pl_count = 0
    pilot_names = []

    for i, num in enumerate(deck):
        if not num:
            continue
        card = card_by_number.get(num)
        if not card:
            errors.append(f"スロット {i + 1}: 存在しないカード {num}")
            continue

        ctype = card.get("type")
        cost = card.get("cost") or 0
        total_cost += cost

        if i < MS_SLOTS:
            if ctype != TYPE_MS:
                errors.append(f"スロット {i + 1} は MS 専用です（{ctype}）")
            else:
                ms_count += 1
        else:
            if ctype != TYPE_PL:
                errors.append(f"スロット {i + 1} は PL 専用です（{ctype}）")
            else:
                pl_count += 1

        # パイロット重複は AB と同じく禁止しておく
        pilot = card.get("pilot")
        if pilot:
            if pilot in pilot_names:
                errors.append(f"パイロット {pilot} が重複しています")
            pilot_names.append(pilot)

    if cmd:
        cmd_card = card_by_number.get(cmd)
        if not cmd_card:
            errors.append(f"コマンダーカード {cmd} が存在しません")
        elif cmd_card.get("type") != TYPE_CMD:
            errors.append("コマンダースロットには CMD タイプのカードを指定してください")

    empty_slots = sum(1 for n in deck if not n)
    if empty_slots:
        warnings.append(f"空きスロットが {empty_slots} あります")

    if ms_count > 0 and pl_count > 0 and ms_count != pl_count:
        warnings.append(f"MS ({ms_count}) と PL ({pl_count}) の数がペアになっていません")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "cost": total_cost,
        "ms_count": ms_count,
        "pl_count": pl_count,
    }
