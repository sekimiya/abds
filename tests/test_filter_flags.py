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


def test_sq_trigger_populated(built):
    """SQ発動条件フィルタの参照先が導出されていること"""
    index, _ = built
    ui_keys = {"ロックオン時", "戦艦/拠点ロックオン時", "撃破時",
               "SQゲージ最大時", "MSアビリティ発動時", "出撃時"}
    values = {c.get("sq_trigger") for c in index.values() if c.get("sq_trigger")}
    assert values <= ui_keys, f"UIキーにないsq_trigger: {values - ui_keys}"
    assert values, "sq_triggerが全カード空(SQ発動条件フィルタが常に0件になる)"
