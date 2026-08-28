"""デッキコードのエンコード/デコード。

形式:
    <slot0>,<slot1>,...,<slot9>|cmd=<cmd>|name=<name>

空スロットは空文字で表現。URL 共有用。
"""

from typing import List, Optional
from urllib.parse import quote, unquote


def encode_deck(deck: List[Optional[str]], cmd: Optional[str], name: str = "") -> str:
    parts = [n or "" for n in deck]
    code = ",".join(parts)
    if cmd:
        code += f"|cmd={cmd}"
    if name:
        code += f"|name={quote(name, safe='')}"  # type: ignore[arg-type]
    return code


def decode_deck(code: str) -> dict:
    deck: List[Optional[str]] = [None] * 10
    cmd: Optional[str] = None
    name = ""

    sections = code.split("|")
    card_part = sections[0] if sections else ""
    nums = card_part.split(",")
    for i, n in enumerate(nums[:10]):
        deck[i] = n if n else None

    for section in sections[1:]:
        if section.startswith("cmd="):
            cmd = section[4:] or None
        elif section.startswith("name="):
            name = unquote(section[5:])

    return {"deck": deck, "cmd": cmd, "name": name}
