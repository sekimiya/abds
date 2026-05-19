"""card_index / card_details 間のデータ整合性テスト"""


def test_index_details_count_match(card_index, card_details):
    idx_nums = {c["number"] for c in card_index}
    det_nums = set(card_details.keys())
    only_idx = idx_nums - det_nums
    only_det = det_nums - idx_nums
    assert not only_idx, f"card_indexにのみ存在: {only_idx}"
    assert not only_det, f"card_detailsにのみ存在: {only_det}"


def test_type_consistency(card_index, card_details):
    bad = []
    for c in card_index:
        det = card_details.get(c["number"], {})
        det_type = det.get("ocr_data", {}).get("type", "")
        if det_type and c["type"] != det_type:
            bad.append(f"{c['number']}: index={c['type']} details={det_type}")
    assert not bad, f"type不一致: {bad[:20]}"


def test_name_consistency(card_index, card_details):
    bad = []
    for c in card_index:
        det = card_details.get(c["number"], {})
        det_name = det.get("name", "") or det.get("ocr_data", {}).get("name", "")
        if det_name and c["name"] and c["name"] != det_name:
            bad.append(f"{c['number']}: index='{c['name']}' details='{det_name}'")
    assert not bad, f"name不一致: {bad[:10]}"


def test_parallel_has_base_stats(card_index, card_details):
    """パラレルカードのstatsがベースカードと一致する"""
    import re

    base_stats = {}
    for c in card_index:
        if "_p" not in c["number"]:
            base_stats[c["number"]] = {
                "mobility": c.get("mobility", 0),
                "ranged": c.get("ranged", 0),
                "melee": c.get("melee", 0),
                "hp": c.get("hp", 0),
            }

    bad = []
    for c in card_index:
        if "_p" not in c["number"]:
            continue
        base_num = re.sub(r"_p\d+$", "", c["number"])
        base = base_stats.get(base_num)
        if not base:
            continue
        for field in ("mobility", "ranged", "melee", "hp"):
            if c.get(field, 0) != base.get(field, 0):
                bad.append(f"{c['number']}.{field}: {c.get(field)}!={base.get(field)}")
                break
    assert not bad, f"パラレルstats不一致: {bad[:10]}"
