"""
GAB デッキシミュレーター デッキコード

Base64 エンコード/デコードによるデッキ共有機能。
tests/test_comprehensive.py TestDeckCode から移植。
"""

import base64
from typing import Optional, List


def generate_code(deck: List[Optional[str]]) -> str:
    """デッキをBase64エンコードされたコード文字列に変換する。

    Args:
        deck: カード番号のリスト (Noneは空文字列として扱う)

    Returns:
        Base64エンコードされたデッキコード
    """
    numbers = [n or '' for n in deck]
    raw = ','.join(numbers)
    return base64.b64encode(raw.encode('utf-8')).decode('ascii')


def parse_code(code: str) -> Optional[List[str]]:
    """Base64デッキコードをカード番号リストにデコードする。

    Args:
        code: Base64エンコードされたデッキコード

    Returns:
        カード番号のリスト。デコード失敗時はNone。
    """
    try:
        decoded = base64.b64decode(code).decode('utf-8')
        return decoded.split(',')
    except Exception:
        return None
