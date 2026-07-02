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


def test_canonicalize_empties_dash_weapon_slot():
    ocr = {"weapon": {"main": {"name": "ビーム", "range": 1, "type": "近距離"},
                      "sub": {"name": "—", "range": 0, "type": "—"}}}
    changes = canonicalize_values(ocr)
    assert ocr["weapon"]["sub"] is None
    assert changes
