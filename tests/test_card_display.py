"""リリース前テスト: 全カードが正常に表示できることを検証"""


MIN_CARD_COUNT = 3500


def test_card_count_minimum(card_index):
    assert len(card_index) >= MIN_CARD_COUNT, (
        f"カード数が少なすぎます: {len(card_index)} < {MIN_CARD_COUNT}"
    )


def test_no_duplicate_numbers(card_index):
    numbers = [c["number"] for c in card_index]
    dupes = [n for n in numbers if numbers.count(n) > 1]
    assert not dupes, f"重複カード番号: {set(dupes)}"


def test_every_card_has_name(card_index):
    no_name = [c["number"] for c in card_index if not c.get("name")]
    assert not no_name, f"名前なしカード: {no_name}"


def test_every_card_has_ocr(card_index):
    no_ocr = [c["number"] for c in card_index if not c.get("has_ocr")]
    assert not no_ocr, f"has_ocr=Falseカード: {no_ocr}"


def test_every_card_has_front_url(card_index):
    no_url = [c["number"] for c in card_index if not c.get("front_url")]
    assert not no_url, f"front_url空カード: {no_url}"


def test_every_ms_has_valid_stats(card_index):
    bad = []
    for c in card_index:
        if c.get("type") != "MS":
            continue
        for field in ("mobility", "ranged", "melee", "hp"):
            val = c.get(field)
            if not isinstance(val, (int, float)) or val < 0:
                bad.append(f"{c['number']}.{field}={val}")
    assert not bad, f"不正なstats: {bad[:20]}"


def test_every_pl_has_valid_stats(card_index):
    bad = []
    for c in card_index:
        if c.get("type") != "PL":
            continue
        for field in ("mobility", "ranged", "melee", "hp"):
            val = c.get(field)
            if not isinstance(val, (int, float)) or val < 0:
                bad.append(f"{c['number']}.{field}={val}")
    assert not bad, f"不正なPL stats: {bad[:20]}"
