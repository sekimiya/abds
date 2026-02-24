"""
GAB デッキシミュレーター デッキバリデーション

デッキ構成の妥当性検証を行う。
"""

from typing import Optional, List

from .constants import DECK_SIZE, MS_SLOT_COUNT, PL_SLOT_COUNT
from .types import DeckValidationResult, DeckValidationError


def validate_deck(ocr_data_list: List[Optional[dict]]) -> DeckValidationResult:
    """デッキ構成をバリデーションする。

    チェック項目:
    - 10枚構成であること
    - MS/PLスロット配置が正しいこと (0-4: MS, 5-9: PL)
    - パイロットの重複がないこと

    Args:
        ocr_data_list: デッキ全カードのOCRデータリスト

    Returns:
        バリデーション結果
    """
    errors: List[DeckValidationError] = []

    # 枚数チェック
    if len(ocr_data_list) != DECK_SIZE:
        errors.append({
            'code': 'INVALID_SIZE',
            'message': f'デッキは{DECK_SIZE}枚で構成してください（現在: {len(ocr_data_list)}枚）',
            'slot': None,
        })

    # MS/PLスロット配置チェック
    for i in range(min(MS_SLOT_COUNT, len(ocr_data_list))):
        ocr = ocr_data_list[i]
        if ocr and ocr.get('type') == 'PL':
            errors.append({
                'code': 'WRONG_SLOT_TYPE',
                'message': f'スロット{i+1}はMSスロットですが、PLカードが配置されています',
                'slot': i,
            })

    for i in range(MS_SLOT_COUNT, min(DECK_SIZE, len(ocr_data_list))):
        ocr = ocr_data_list[i]
        if ocr and ocr.get('type') == 'MS':
            errors.append({
                'code': 'WRONG_SLOT_TYPE',
                'message': f'スロット{i+1}はPLスロットですが、MSカードが配置されています',
                'slot': i,
            })

    # パイロット重複チェック
    duplicates = check_pilot_duplicates(ocr_data_list)
    for dup_name, slots in duplicates.items():
        slot_str = ', '.join(str(s + 1) for s in slots)
        errors.append({
            'code': 'DUPLICATE_PILOT',
            'message': f'パイロット「{dup_name}」がスロット{slot_str}で重複しています',
            'slot': slots[0],
        })

    return {
        'valid': len(errors) == 0,
        'errors': errors,
    }


def check_pilot_duplicates(
    ocr_data_list: List[Optional[dict]],
) -> dict:
    """同名パイロットの重複を検出する。

    Args:
        ocr_data_list: デッキ全カードのOCRデータリスト

    Returns:
        重複パイロット名→スロットインデックスリストの辞書
    """
    pilot_slots = {}
    for i, ocr in enumerate(ocr_data_list):
        if not ocr:
            continue
        if ocr.get('type') != 'PL':
            continue
        name = ocr.get('name', '').strip()
        if not name:
            continue
        pilot_slots.setdefault(name, []).append(i)

    return {name: slots for name, slots in pilot_slots.items() if len(slots) > 1}
