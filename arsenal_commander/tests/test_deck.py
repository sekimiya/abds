"""デッキロジックのテスト。"""

import json
import os
import sys

# テスト実行時に親ディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logic.color_buff import compute_unit_buffs, has_color_buff
from logic.deck_code import decode_deck, encode_deck
from logic.deck_validation import validate_deck
from logic.stats import compute_deck_stats

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "card_index.json")


def load_cards():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        index = json.load(f)
    return {c["number"]: c for c in index}


card_by_number = load_cards()


def test_color_buff_match():
    cmd = "AC01-CMD-001"  # 赤, 緑
    assert has_color_buff("AC01-001", {"赤", "緑"}, card_by_number) is True  # 赤を含む
    assert has_color_buff("AC01-004", {"赤", "緑"}, card_by_number) is True  # 緑を含む
    assert has_color_buff("AC01-005", {"赤", "緑"}, card_by_number) is False  # 青のみ


def test_color_buff_no_commander():
    assert has_color_buff("AC01-001", set(), card_by_number) is False


def test_unit_buffs():
    deck = ["AC01-001", "AC01-004", None, None, None, "AC01-007", "AC01-009", None, None, None]
    cmd = "AC01-CMD-001"  # 赤, 緑
    units = compute_unit_buffs(deck, cmd, card_by_number)
    assert units[0]["ms_buff"] is True   # ガンダムは赤を含む
    assert units[0]["pl_buff"] is False  # アムロは青のみ
    assert units[0]["unit_buff"] is True
    assert units[1]["ms_buff"] is True   # νガンダムは緑を含む
    assert units[1]["pl_buff"] is True   # マツナガは緑


def test_deck_validation_valid():
    deck = ["AC01-001", "AC01-004", "AC01-005", "AC01-006", "AC01-003",
            "AC01-007", "AC01-008", "AC01-009", "AC01-010", "AC01-011"]
    result = validate_deck(deck, "AC01-CMD-001", card_by_number)
    assert result["valid"] is True
    assert result["cost"] == 36


def test_deck_validation_duplicate_pilot():
    # 同じパイロット名を重複させる
    deck = ["AC01-001", "AC01-004", None, None, None,
            "AC01-007", "AC01-007", None, None, None]
    result = validate_deck(deck, None, card_by_number)
    assert result["valid"] is False
    assert any("重複" in e for e in result["errors"])


def test_deck_validation_wrong_slot():
    deck = [None, None, None, None, None,
            "AC01-001", None, None, None, None]  # MS を PL スロットに
    result = validate_deck(deck, None, card_by_number)
    assert result["valid"] is False
    assert any("PL 専用" in e for e in result["errors"])


def test_deck_code_roundtrip():
    deck = ["AC01-001", None, "AC01-003", None, None,
            None, "AC01-007", None, None, None]
    code = encode_deck(deck, "AC01-CMD-002", "テストデッキ")
    decoded = decode_deck(code)
    assert decoded["deck"] == deck
    assert decoded["cmd"] == "AC01-CMD-002"
    assert decoded["name"] == "テストデッキ"


def test_stats_computation():
    deck = ["AC01-001", "AC01-004", None, None, None,
            "AC01-007", "AC01-009", None, None, None]
    stats = compute_deck_stats(deck, "AC01-CMD-001", card_by_number)
    assert stats["total_cost"] == 15
    assert stats["commander_colors"] == ["赤", "緑"]
    assert stats["units"][0]["buff"] is True


def test_colorless_arsenal_base_card():
    """アーセナルベースカードは色が無く、バフはかからない。"""
    cmd = "AC01-CMD-001"  # 赤, 緑
    assert has_color_buff("AB01-001", {"赤", "緑"}, card_by_number) is False
    stats = compute_deck_stats(["AB01-001", None, None, None, None, "AB01-003", None, None, None, None], cmd, card_by_number)
    assert stats["units"][0]["buff"] is False
    assert stats["units"][0]["ms"]["atk"] == 370
    assert stats["total_cost"] == 7
