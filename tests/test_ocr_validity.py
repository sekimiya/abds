"""OCRデータの妥当性検証（ドメインルールによるCIゲート）。

card_details.json の ocr_data に対し、OCR読み違い・構造化ミスが
混入していないかを確定的ルールで検証する。
統計的な異常検知（外れ値レビュー）は scripts/check_ocr_anomalies.py 担当。

語彙定数は tests/test_search_filters.py のUIキーと同期させること。
"""

import json
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CATEGORY_MS = {"機動", "近距離", "遠距離"}
CATEGORY_PL = {"殲滅", "制圧", "防衛"}
TERRAIN_KEYS = {"ground", "space", "desert", "water"}
TERRAIN_RANKS = {"S", "A", "B", "C", "D"}
STAT_KEYS = {"mobility", "ranged_attack", "melee_attack", "hp"}
EB_LEVELS = {1, 2, 3}
# レアリティ語彙はUIボタン(test_search_filters.pyが実HTMLから検証)と同一
RARITY_VOCAB = {"C", "R", "M", "A", "LX", "UT", "FQ", "P", "U",
                "SP-SEC", "PR", "SN", "LE", "VE"}


@pytest.fixture(scope="module")
def details():
    with open(ROOT / "data" / "card_details.json", encoding="utf-8") as f:
        return json.load(f)


def _ocr(entry):
    return entry.get("ocr_data") or {}


def _all_strings(obj, path=""):
    """ocr_data内の全文字列を (path, value) で列挙"""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _all_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _all_strings(v, f"{path}[{i}]")


def test_type_vocab(details):
    bad = [(num, _ocr(e).get("type")) for num, e in details.items()
           if _ocr(e).get("type") not in ("MS", "PL")]
    assert not bad, f"type が MS/PL 以外: {bad[:10]}"


def test_name_nonempty(details):
    bad = [num for num, e in details.items() if not (_ocr(e).get("name") or "").strip()]
    assert not bad, f"name が空: {bad[:10]}"


def test_number_matches_entry_key(details):
    bad = [num for num, e in details.items()
           if e.get("number") and e["number"] != num]
    assert not bad, f"エントリキーと number の不一致: {bad[:10]}"


def test_category_vocab_by_type(details):
    bad = []
    for num, e in details.items():
        ocr = _ocr(e)
        cat = ocr.get("category")
        if cat is None:
            continue
        vocab = CATEGORY_MS if ocr.get("type") == "MS" else CATEGORY_PL
        if cat not in vocab:
            bad.append((num, ocr.get("type"), cat))
    assert not bad, f"語彙外カテゴリ: {bad[:10]}"


def test_rarity_vocab(details):
    bad = [(num, _ocr(e).get("rarity")) for num, e in details.items()
           if _ocr(e).get("rarity") is not None
           and _ocr(e).get("rarity") not in RARITY_VOCAB]
    assert not bad, f"語彙外レアリティ: {bad[:10]}"


def test_stats_structure_and_types(details):
    """stats は4キー・値は非負intまたはNone"""
    bad = []
    for num, e in details.items():
        stats = _ocr(e).get("stats")
        if stats is None:
            continue
        if not isinstance(stats, dict):
            bad.append((num, "stats非dict", type(stats).__name__))
            continue
        unknown = set(stats) - STAT_KEYS
        if unknown:
            bad.append((num, "未知のstatキー", sorted(unknown)))
        for k, v in stats.items():
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
                bad.append((num, k, v))
    assert not bad, f"stats の構造/型異常: {bad[:10]}"


def test_cost_type(details):
    bad = [(num, repr(_ocr(e).get("cost"))) for num, e in details.items()
           if _ocr(e).get("cost") is not None
           and (not isinstance(_ocr(e).get("cost"), int)
                or isinstance(_ocr(e).get("cost"), bool))]
    assert not bad, f"cost が非int（文字列数値等の混入）: {bad[:10]}"


def test_terrain_compatibility_vocab(details):
    bad_keys, bad_ranks = set(), set()
    for num, e in details.items():
        for k, v in (_ocr(e).get("terrain_compatibility") or {}).items():
            if k not in TERRAIN_KEYS:
                bad_keys.add((num, k))
            if v is not None and v not in TERRAIN_RANKS:
                bad_ranks.add((num, v))
    assert not bad_keys, f"未知の地形キー: {sorted(bad_keys)[:10]}"
    assert not bad_ranks, f"語彙外の地形ランク: {sorted(bad_ranks)[:10]}"


def test_link_ability_present(details):
    """実カードは1件以上のリンクアビリティを持つこと。
    （TEST- プレフィックスはテスト用フィクスチャデータのため除外。
      1件のみのカードは実在するため >=1 を要件とし、
      !=2 のレビューは check_ocr_anomalies.py のレポートで扱う）"""
    bad = []
    for num, e in details.items():
        if num.startswith("TEST-"):
            continue
        la = _ocr(e).get("link_ability")
        if not isinstance(la, list) or len(la) == 0:
            bad.append(num)
    assert not bad, f"リンクアビリティ0件の実カード: {bad[:10]}"


def test_link_ability_entry_structure(details):
    """各リンクエントリの name/condition/effect が非空であること"""
    bad = []
    for num, e in details.items():
        for i, la in enumerate(_ocr(e).get("link_ability") or []):
            if not isinstance(la, dict):
                bad.append((num, i, "非dict"))
                continue
            for k in ("name", "condition", "effect"):
                if not (la.get(k) or "").strip():
                    bad.append((num, i, k))
    assert not bad, f"リンクエントリの必須フィールド空: {bad[:10]}"


def test_eb_level_vocab(details):
    """echoes_beat.level は 1-3（またはNone）であること"""
    bad = []
    for num, e in details.items():
        eb = (_ocr(e).get("special_attack") or {}).get("echoes_beat")
        if isinstance(eb, dict):
            lv = eb.get("level")
            if lv is not None and lv not in EB_LEVELS:
                bad.append((num, lv))
    assert not bad, f"語彙外のEB Lv.: {bad[:10]}"


def test_no_mojibake_or_control_chars(details):
    """文字化け(U+FFFD)・制御文字がテキストに混入していないこと"""
    bad = []
    for num, e in details.items():
        for path, s in _all_strings(_ocr(e)):
            if "�" in s:
                bad.append((num, path, "U+FFFD"))
                continue
            ctrl = [ch for ch in s
                    if unicodedata.category(ch) == "Cc" and ch not in "\n\t"]
            if ctrl:
                bad.append((num, path, f"制御文字:{[hex(ord(c)) for c in ctrl]}"))
    assert not bad, f"文字化け/制御文字混入: {bad[:10]}"
