"""検索フィルタ用派生フラグの整合テスト。

card_index の派生フラグ(has_eb等)が card_details のcanonicalデータと
論理的に一致していることを検証する。導出ロジック(rebuild_index.py)が
canonicalフィールド以外を参照し始めた場合ここで検出される。
"""

import json
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def built():
    with open(ROOT / "data" / "card_index.json", encoding="utf-8") as f:
        index = {c["number"]: c for c in json.load(f)}
    with open(ROOT / "data" / "card_details.json", encoding="utf-8") as f:
        details = json.load(f)
    return index, details


def test_has_eb_matches_echoes_beat(built):
    index, details = built
    bad = []
    for num, c in index.items():
        ocr = details.get(num, {}).get("ocr_data", {})
        if ocr.get("type") != "MS":
            continue
        eb = (ocr.get("special_attack") or {}).get("echoes_beat")
        if bool(c.get("has_eb")) != isinstance(eb, dict):
            bad.append(num)
    assert not bad, f"has_ebとechoes_beatの不一致: {bad[:10]}"


def test_eb_type_matches_sp_type(built):
    index, details = built
    bad = []
    for num, c in index.items():
        if not c.get("has_eb"):
            continue
        ocr = details.get(num, {}).get("ocr_data", {})
        sp_type = (ocr.get("special_attack") or {}).get("sp_type", "")
        expected = "sp" if sp_type == "ECHOES BEAT SP" else "normal"
        if c.get("eb_type") != expected:
            bad.append((num, c.get("eb_type"), sp_type))
    assert not bad, f"eb_typeとsp_type印字の不一致: {bad[:10]}"


def test_eb_level_matches_canonical(built):
    index, details = built
    bad = []
    for num, c in index.items():
        ocr = details.get(num, {}).get("ocr_data", {})
        eb = (ocr.get("special_attack") or {}).get("echoes_beat")
        if isinstance(eb, dict) and eb.get("level") is not None:
            if c.get("eb_level") != eb["level"]:
                bad.append((num, c.get("eb_level"), eb["level"]))
    assert not bad, f"eb_levelの不一致: {bad[:10]}"


def test_has_eb_skill_matches_flag(built):
    index, details = built
    bad = []
    for num, c in index.items():
        ocr = details.get(num, {}).get("ocr_data", {})
        if ocr.get("type") != "PL":
            continue
        ps = ocr.get("pilot_skill") or {}
        if bool(c.get("has_eb_skill")) != bool(ps.get("is_eb_skill")):
            bad.append(num)
    assert not bad, f"has_eb_skillとis_eb_skillの不一致: {bad[:10]}"


def test_eb_trigger_level_matches_canonical(built):
    index, details = built
    bad = []
    for num, c in index.items():
        ocr = details.get(num, {}).get("ocr_data", {})
        ps = ocr.get("pilot_skill") or {}
        if ps.get("is_eb_skill") and ps.get("eb_trigger_level") is not None:
            if c.get("eb_trigger_level") != ps["eb_trigger_level"]:
                bad.append((num, c.get("eb_trigger_level"), ps["eb_trigger_level"]))
    assert not bad, f"eb_trigger_levelの不一致: {bad[:10]}"


def test_no_eb_data_in_united_sp(built):
    index, details = built
    import re
    bad = []
    for num, entry in details.items():
        sp = (entry.get("ocr_data") or {}).get("special_attack") or {}
        usp = sp.get("united_sp")
        if isinstance(usp, dict) and re.search(r"EBLv\.を\d+下げる", usp.get("description") or ""):
            bad.append(num)
    assert not bad, f"united_spにEB誤格納: {bad[:10]}"


def test_has_sqsp_matches_canonical(built):
    index, details = built
    bad = []
    for num, c in index.items():
        ocr = details.get(num, {}).get("ocr_data", {})
        if ocr.get("type") != "MS":
            continue
        sp = ocr.get("special_attack") or {}
        expected = sp.get("sp_type") == "SQUAD SP" or isinstance(sp.get("squad_sp"), dict)
        if bool(c.get("has_sqsp")) != expected:
            bad.append(num)
    assert not bad, f"has_sqspの不一致: {bad[:10]}"


def test_sq_gauge_rate_populated(built):
    """SQゲージ量フィルタ(UI: 大/中/小)の参照先が導出されていること"""
    index, _ = built
    values = {c.get("sq_gauge_rate") for c in index.values() if c.get("sq_gauge_rate")}
    assert values <= {"大", "中", "小"}, f"不正なsq_gauge_rate: {values}"
    assert values, "sq_gauge_rateが全カード空(SQゲージフィルタが常に0件になる)"


def test_skip_sp_consistency(built):
    """スキップSP = Lv.1のEB技でEBLv.が3に上昇するもの"""
    import re
    index, details = built
    bad = []
    for num, c in index.items():
        ocr = details.get(num, {}).get("ocr_data", {})
        eb = (ocr.get("special_attack") or {}).get("echoes_beat")
        desc = eb.get("description", "") if isinstance(eb, dict) else ""
        jump = re.search(r"EBLv\.が(\d+)に上昇", desc)
        expected = (isinstance(eb, dict) and c.get("eb_level") == 1
                    and jump is not None and jump.group(1) == "3")
        if bool(c.get("has_skip_sp")) != expected:
            bad.append(num)
    assert not bad, f"has_skip_spの不整合: {bad[:10]}"


def test_eb_desc_not_boilerplate(built):
    """echoes_beat.descriptionにバナー定型文が入っていない(効果文が入っていること)"""
    _, details = built
    bad = []
    for num, entry in details.items():
        eb = ((entry.get("ocr_data") or {}).get("special_attack") or {}).get("echoes_beat")
        if isinstance(eb, dict) and "ECHOES BEAT Lv.を下げることで" in (eb.get("description") or ""):
            bad.append(num)
    assert not bad, f"EB説明がバナー定型文(↓↑バッジ/効果タグが出ない): {bad[:10]}"


def test_skill_trigger_ui_keys_all_match(built):
    """skTimフィルタの全UIキーが少なくとも1枚にマッチすること
    (フロントはskill_trigger(生トリガー文)への部分一致。HP条件時のみ正規表現)"""
    import re
    index, _ = built
    ui_keys = ["出撃時", "ロックオン時", "MSアビリティ", "HP条件時", "撃破時",
               "一定時間経過毎", "撤退時", "EBLv", "戦術技発動時", "防衛拠点変更", "SQゲージ"]
    triggers = [c.get("skill_trigger") or "" for c in index.values()]
    dead = []
    for k in ui_keys:
        if k == "HP条件時":
            n = sum(1 for t in triggers if re.search(r"HP\d+%", t))
        else:
            n = sum(1 for t in triggers if k in t)
        if n == 0:
            dead.append(k)
    assert not dead, f"どのカードにもマッチしないskTimキー(死にボタン): {dead}"


def test_eb_trigger_cond_ui_keys_all_match(built):
    """ebCondフィルタの全UIキー(上昇時/以上/Lv到達時)がマッチすること"""
    index, _ = built
    values = {c.get("eb_trigger_cond") for c in index.values() if c.get("eb_trigger_cond")}
    ui_keys = {"上昇時", "以上", "Lv到達時"}
    assert values == ui_keys, f"ebCond導出値とUIキーの不一致: 導出={values}"


def test_skill_effect_ui_keys_all_match(built):
    """skEffフィルタの全UIキーがskill_effect_tagsに存在すること"""
    index, _ = built
    ui_keys = {"機動力UP", "遠距離攻撃力UP", "近距離攻撃力UP", "SP威力UP", "ダメージ軽減",
               "敵デバフ", "対戦艦/拠点", "SQゲージ増加", "全味方バフ", "全味方殲滅", "HP条件"}
    derived = {t for c in index.values() for t in (c.get("skill_effect_tags") or [])}
    dead = ui_keys - derived
    assert not dead, f"どのカードにも付かないskEffキー(死にボタン): {dead}"


def test_no_fullwidth_slash_in_text_fields(built):
    """テキストフィールドのスラッシュは半角に統一されていること"""
    _, details = built
    bad = []
    for num, entry in details.items():
        ocr = entry.get("ocr_data") or {}
        texts = []
        msa = ocr.get("ms_ability") or {}
        if isinstance(msa, dict):
            texts.append(msa.get("description"))
        sp = ocr.get("special_attack") or {}
        if isinstance(sp, dict):
            texts.append(sp.get("description"))
            for k in ("echoes_beat", "united_sp", "squad_sp"):
                o = sp.get(k)
                if isinstance(o, dict):
                    texts.append(o.get("description"))
        ps = ocr.get("pilot_skill") or {}
        if isinstance(ps, dict):
            texts.extend([ps.get("trigger"), ps.get("effect")])
        for la in (ocr.get("link_ability") or []):
            if isinstance(la, dict):
                texts.append(la.get("effect"))
        if any(isinstance(t, str) and "／" in t for t in texts):
            bad.append(num)
    assert not bad, f"全角スラッシュ残留: {bad[:10]}"


def test_sq_trigger_populated(built):
    """SQ発動条件フィルタの参照先が導出されていること"""
    index, _ = built
    ui_keys = {"ロックオン時", "戦艦/拠点ロックオン時", "撃破時",
               "SQゲージ最大時", "MSアビリティ発動時", "出撃時"}
    values = {c.get("sq_trigger") for c in index.values() if c.get("sq_trigger")}
    assert values <= ui_keys, f"UIキーにないsq_trigger: {values - ui_keys}"
    assert values, "sq_triggerが全カード空(SQ発動条件フィルタが常に0件になる)"
