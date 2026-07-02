"""値語彙の正規化テスト: 全OCRソースが正規語彙(enum)に従っていることを検証。

表記揺れ(全角括弧、武器種の別名、対象の別表記等)は schema.canonicalize_values が
自動変換し、変換できない未知の語彙はここで検出されてpushがブロックされる。
"""

from schema import (
    canonicalize_values,
    validate_values,
    _canon_target,
    _canon_weapon_type,
)


def test_all_files_pass_value_validation(ocr_files):
    errors = []
    for cn, data in ocr_files.items():
        errors.extend(validate_values(data.get("ocr_data", {}), cn))
    assert not errors, "値語彙違反:\n" + "\n".join(errors[:20])


def test_all_files_already_canonical(ocr_files):
    """canonicalize_valuesを通しても無変更 = ソースが正規形で保存されている"""
    import copy
    dirty = []
    for cn, data in ocr_files.items():
        ocr = copy.deepcopy(data.get("ocr_data", {}))
        changes = canonicalize_values(ocr)
        if changes:
            dirty.append(f"{cn}: {changes}")
    assert not dirty, "非正規値が残存(normalize_ocr.py を実行):\n" + "\n".join(dirty[:10])


def test_target_alias_conversion():
    assert _canon_target("単体（敵）") == "単体(敵)"
    assert _canon_target("敵単体") == "単体(敵)"
    assert _canon_target("自身") == "自分"
    assert _canon_target("範囲(敵) / 貫通(敵)") == "範囲(敵)/貫通(敵)"
    assert _canon_target("範囲（敵）／貫通（敵）") == "範囲(敵)/貫通(敵)"
    assert _canon_target("—") == ""
    assert _canon_target("") == ""
    assert _canon_target(None) is None


def test_weapon_type_alias_conversion():
    assert _canon_weapon_type("射撃") == "遠距離"
    assert _canon_weapon_type("格闘") == "近距離"
    assert _canon_weapon_type("遠距離攻撃") == "遠距離"
    assert _canon_weapon_type("中距離射撃") == "遠距離"
    assert _canon_weapon_type("速距離") == "遠距離"
    assert _canon_weapon_type("防御") == "防御"
    assert _canon_weapon_type("ー") == ""


def test_validate_rejects_unknown_vocabulary():
    ocr = {
        "type": "MS",
        "rarity": "SECRET",
        "category": "殲滅",
        "weapon": {"main": {"name": "x", "range": 1, "type": "謎距離"}, "sub": None},
        "ms_ability": {"activation": "デッキに2枚以上", "target": "敵"},
    }
    errors = validate_values(ocr, "TEST-XXX")
    joined = "\n".join(errors)
    assert "rarity" in joined
    assert "category" in joined  # MSに殲滅はPL語彙
    assert "weapon.main.type" in joined
    assert "activation" in joined
    assert "ms_ability.target" in joined


def test_canonicalize_derives_sp_type_from_eb_type():
    """OCR生出力のeb_type(normal/sp)からsp_typeを補完する"""
    ocr = {"special_attack": {"description": "通常効果。", "sp_type": "",
                              "echoes_beat": {"eb_type": "sp", "name": "技名 Lv.3",
                                              "description": "EBLv.を3下げる。効果。"}}}
    canonicalize_values(ocr)
    assert ocr["special_attack"]["sp_type"] == "ECHOES BEAT SP"

    ocr2 = {"special_attack": {"description": "", "sp_type": "",
                               "echoes_beat": {"eb_type": "normal", "name": "技名 Lv.1",
                                               "description": "EBLv.を1下げる。効果。"}}}
    canonicalize_values(ocr2)
    assert ocr2["special_attack"]["sp_type"] == "ECHOES BEAT"


def test_canonicalize_splits_eb_from_sp_description():
    """通常SP／EB併記の自動分離。文中の[遠／近攻撃力]は誤爆しない"""
    ocr = {"special_attack": {
        "sp_type": "ECHOES BEAT",
        "description": "敵の[遠／近攻撃力]をダウンする。／EBLv.を2下げる。EB効果。",
        "echoes_beat": {"name": "技名 Lv.2", "description": ""}}}
    changes = canonicalize_values(ocr)
    sp = ocr["special_attack"]
    assert sp["description"] == "敵の[遠／近攻撃力]をダウンする。"
    assert sp["echoes_beat"]["description"] == "EBLv.を2下げる。EB効果。"
    assert changes

    # 半角スラッシュ区切り + EB側が既に正しい場合はsp側の切り詰めのみ
    ocr2 = {"special_attack": {
        "sp_type": "ECHOES BEAT",
        "description": "通常効果。/EBLv.を1下げる。重複EB効果。",
        "echoes_beat": {"name": "技名 Lv.1", "description": "EBLv.を1下げる。正しいEB効果。"}}}
    canonicalize_values(ocr2)
    assert ocr2["special_attack"]["description"] == "通常効果。"
    assert ocr2["special_attack"]["echoes_beat"]["description"] == "EBLv.を1下げる。正しいEB効果。"


def test_canonicalize_empties_dash_weapon_slot():
    ocr = {"weapon": {"main": {"name": "ビーム", "range": 1, "type": "近距離"},
                      "sub": {"name": "—", "range": 0, "type": "—"}}}
    changes = canonicalize_values(ocr)
    assert ocr["weapon"]["sub"] is None
    assert changes
