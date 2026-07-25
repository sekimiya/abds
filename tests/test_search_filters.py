"""カード検索フィルタの契約・ロジック検証テスト。

3層構成:
  A-1. UIキー ↔ データ パリティ ... フィルタ選択肢と実データの双方向一致
  A-3. フィルタロジック不変条件 ... JS(applyFilters)のリファレンス実装に対する性質検証
  A-4. 到達可能性 ... フィルタが参照するデータの欠損検出

【重要】このファイルの UI キー定数は index.html / mobile.html の
フィルタパネル（rarity-btn, categoryFilter, terrain セレクト等）と
一致させること。UI を変更したらここも更新する。
なお A-2/A-3 のリファレンス実装は desktop 版 (index.html) の
SearchPanel.applyFilters() (L5098-5282) 準拠。
mobile.html 独自フィルタ（_statFilter/_quickSeries 等）は対象外。
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------
# UI キー定数（index.html / mobile.html のフィルタパネルと一致させること）
# ---------------------------------------------------------------
# レアリティのUIキーは index.html / mobile.html の rarity-btn から
# 実際にパースして検証する（定数手管理だとUI改修に追随できないため）
def _parse_ui_rarity_keys():
    """両HTMLの data-rarity 属性値を {filename: set} で返す"""
    result = {}
    for html in ("index.html", "mobile.html"):
        text = (ROOT / html).read_text(encoding="utf-8")
        result[html] = set(re.findall(r'data-rarity="([^"]+)"', text))
    return result


RARITY_UI_KEYS = _parse_ui_rarity_keys()["index.html"]
# 将来拡張用に UI へ先行配置されているが現データに0件のレアリティ。
# 新シリーズで該当レアリティが追加されたらこの集合から除くこと。
KNOWN_FUTURE_RARITIES = {"UT", "FQ", "SP-SEC"}

CATEGORY_MS = {"機動", "近距離", "遠距離"}
CATEGORY_PL = {"殲滅", "制圧", "防衛"}

TERRAIN_KEYS = {"ground", "space", "desert", "water"}
RANK_ORDER = ["S", "A", "B", "C", "D"]  # JS: rankOrder (indexOf<=で「以上」比較)

COST_SLIDER_MIN, COST_SLIDER_MAX = 0, 13  # #filterCostMin/Max の range
EB_LEVEL_UI = {1, 2, 3}


# ---------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------
@pytest.fixture(scope="module")
def cards():
    with open(ROOT / "data" / "card_index.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def links():
    with open(ROOT / "data" / "link_index.json", encoding="utf-8") as f:
        return json.load(f)


# ===============================================================
# A-1. UIキー ↔ データ パリティ
# ===============================================================
def test_rarity_data_covered_by_ui(cards):
    """データのレアリティ値がすべてUIボタンで選択可能であること（取りこぼし検出）。
    両HTMLの実ボタンをパースして検証する。"""
    data_values = {c.get("rarity") for c in cards if c.get("rarity")}
    for html, keys in _parse_ui_rarity_keys().items():
        uncovered = data_values - keys
        assert not uncovered, (
            f"{html} のレアリティボタンにない値(フィルタで到達不能): {uncovered}。"
            " rarity-btn を追加するかデータを修正すること")


def test_rarity_ui_parity_between_pages():
    """index.html と mobile.html のレアリティボタンが一致していること"""
    keys = _parse_ui_rarity_keys()
    assert keys["index.html"] == keys["mobile.html"], (
        f"レアリティボタンの差分: "
        f"index のみ={keys['index.html'] - keys['mobile.html']}, "
        f"mobile のみ={keys['mobile.html'] - keys['index.html']}")


def test_rarity_no_dead_buttons(cards):
    """全レアリティボタンが1枚以上にマッチすること（死にボタン検出）。
    KNOWN_FUTURE_RARITIES は将来拡張用の先行配置として明示的に除外。"""
    data_values = {c.get("rarity") for c in cards if c.get("rarity")}
    dead = RARITY_UI_KEYS - data_values - KNOWN_FUTURE_RARITIES
    assert not dead, f"どのカードにもマッチしないレアリティボタン: {dead}"


def test_known_future_rarities_still_future(cards):
    """KNOWN_FUTURE_RARITIES に値が来たらホワイトリストを更新させるための検知"""
    data_values = {c.get("rarity") for c in cards if c.get("rarity")}
    arrived = KNOWN_FUTURE_RARITIES & data_values
    assert not arrived, (
        f"{arrived} がデータに出現。KNOWN_FUTURE_RARITIES から除外すること")


def test_category_ui_parity(cards):
    """カテゴリ: データ値がtype別UIキーに完全一致（双方向）"""
    ms_values = {c.get("category") for c in cards
                 if c.get("type") == "MS" and c.get("category")}
    pl_values = {c.get("category") for c in cards
                 if c.get("type") == "PL" and c.get("category")}
    assert ms_values == CATEGORY_MS, f"MSカテゴリ不一致: {ms_values ^ CATEGORY_MS}"
    assert pl_values == CATEGORY_PL, f"PLカテゴリ不一致: {pl_values ^ CATEGORY_PL}"


def test_terrain_keys_and_ranks(cards):
    """地形キーとランクがUIの語彙内であること"""
    bad_keys, bad_ranks = set(), set()
    for c in cards:
        for k, v in (c.get("terrain") or {}).items():
            if k not in TERRAIN_KEYS:
                bad_keys.add(k)
            if v is not None and v not in RANK_ORDER:
                bad_ranks.add(v)
    assert not bad_keys, f"未知の地形キー: {bad_keys}"
    assert not bad_ranks, f"UIランク語彙外の地形ランク: {bad_ranks}"


def test_cost_within_slider_range(cards):
    """コストがスライダー範囲(0-13)内のintかNoneであること"""
    bad = [(c["number"], c.get("cost")) for c in cards
           if c.get("cost") is not None
           and (not isinstance(c.get("cost"), int)
                or not (COST_SLIDER_MIN <= c["cost"] <= COST_SLIDER_MAX))]
    assert not bad, f"スライダー範囲外/非intのコスト: {bad[:10]}"


def test_stats_are_non_negative_ints(cards):
    """ステータスが非負intかNoneであること
    （700超はスライダー最大=『≥700』に包含されるため許容）"""
    bad = []
    for c in cards:
        for k in ("mobility", "ranged", "melee", "hp"):
            v = c.get(k)
            if v is not None and (not isinstance(v, int) or v < 0):
                bad.append((c["number"], k, v))
    assert not bad, f"不正なステータス値: {bad[:10]}"


def test_eb_levels_within_ui(cards):
    """EB Lv. がUIトグル{1,2,3}の語彙内であること"""
    bad = []
    for c in cards:
        for k in ("eb_level", "eb_trigger_level"):
            v = c.get(k)
            if v is not None and v not in EB_LEVEL_UI:
                bad.append((c["number"], k, v))
    assert not bad, f"UI語彙外のEB Lv.: {bad[:10]}"


def test_series_populated(cards):
    """全カードの series が非空であること（シリーズフィルタの前提）"""
    bad = [c["number"] for c in cards if not c.get("series")]
    assert not bad, f"series未設定のカード: {bad[:10]}"


# ===============================================================
# A-2. JSフィルタのリファレンス実装
# （index.html SearchPanel.applyFilters() 準拠。UI変更時は同期すること）
# ===============================================================
# JSは大文字(Ⅰ-Ⅹ)・小文字(ⅰ-ⅹ)両方をマップする。Pythonのlower()は
# ローマ数字も小文字化(U+2160→U+2170)するため両方必要。
_ROMAN = dict(zip("ⅠⅰⅡⅱⅢⅲⅣⅳⅤⅴⅥⅵⅦⅶⅧⅷⅨⅸⅩⅹ",
                  ["1", "1", "2", "2", "3", "3", "4", "4", "5", "5",
                   "6", "6", "7", "7", "8", "8", "9", "9", "10", "10"]))
_KANJI_NUM = {"壱": "1", "弐": "2", "参": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
_CIRCLED = dict(zip("①②③④⑤⑥⑦⑧⑨", "123456789"))
_STRIP_CHARS = set("・･· \u3000-‐‑‒–—―−ｰ")


def normalize_search(s):
    """JS _normalizeSearch() 相当: 小文字化→数字表記統一→記号/空白除去"""
    if not s:
        return ""
    out = []
    for ch in str(s).lower():
        if ch in _ROMAN:
            out.append(_ROMAN[ch])
        elif ch in _KANJI_NUM:
            out.append(_KANJI_NUM[ch])
        elif ch in _CIRCLED:
            out.append(_CIRCLED[ch])
        elif ch in _STRIP_CHARS or ch.isspace():  # JS \s + \u3000 相当
            continue
        else:
            out.append(ch)
    return "".join(out)


def no_detail(c):
    """JS _noDetail(c): プロモ等の詳細未設定カードは全詳細フィルタをパス"""
    return c.get("cost") is None


def match_rarity(c, selected):
    """JS: !c.rarity || currentRarity.has(c.rarity)（選択空=無効は呼び出し側で制御）"""
    return not c.get("rarity") or c.get("rarity") in selected


def match_category(c, selected):
    return not c.get("category") or c.get("category") in selected


def match_cost(c, lo, hi):
    """JS: min>0||max<13 のとき有効。両端含む。_noDetailはパス"""
    if lo <= COST_SLIDER_MIN and hi >= COST_SLIDER_MAX:
        return True
    return no_detail(c) or (c.get("cost") is not None and lo <= c["cost"] <= hi)


def match_stat(c, key, threshold):
    """JS: 値>0 のとき有効。下限のみ。c.stat>=v（nullは0にcoerce）"""
    if threshold <= 0:
        return True
    return no_detail(c) or (c.get(key) or 0) >= threshold


def match_terrain(c, terrain_type, min_rank):
    """JS: タイプとランク両方選択時のみ有効。rankOrder.indexOf<=で『以上』。
    該当キーなし/ランクnullは除外。_noDetailはパス"""
    if no_detail(c):
        return True
    r = (c.get("terrain") or {}).get(terrain_type)
    if r is None or r not in RANK_ORDER:
        return False
    return RANK_ORDER.index(r) <= RANK_ORDER.index(min_rank)


def match_eb_lv(c, levels):
    """JS: eb_level or eb_trigger_level が選択Lvに含まれる（OR）"""
    return (no_detail(c) or c.get("eb_level") in levels
            or c.get("eb_trigger_level") in levels)


def match_name(c, query):
    """JS: normalize後に number||name の部分一致（OR）"""
    q = normalize_search(query)
    if not q:
        return True
    return (q in normalize_search(c.get("number"))
            or q in normalize_search(c.get("name")))


def match_text(c, query):
    """JS: 空白分割した全語が search_text に含まれる（AND）"""
    terms = [normalize_search(t) for t in str(query).split() if t.strip()]
    if not terms:
        return True
    hay = normalize_search(c.get("search_text"))
    return all(t in hay for t in terms)


def has_active_filter_desktop(series_selected=False, all_series=False, name_q="",
                              text_q="", link_q="", alt_art=False, bookmark=False,
                              **_ignored_detail_filters):
    """JS _hasActiveFilter() (desktop): シリーズ/名前/テキスト/リンク/
    イラスト違い/BM のみが起動条件。コスト・レアリティ等だけでは起動しない。"""
    return bool((series_selected or all_series) or name_q or text_q
                or link_q or alt_art or bookmark)


# ===============================================================
# A-3. フィルタロジック不変条件（実データに対する性質テスト）
# ===============================================================
def test_or_within_dimension_monotonic(cards):
    """次元内OR: レアリティ選択を増やすと結果は単調増加"""
    rarities = sorted({c.get("rarity") for c in cards if c.get("rarity")})
    prev = set()
    for i in range(1, len(rarities) + 1):
        sel = set(rarities[:i])
        hit = {c["number"] for c in cards if match_rarity(c, sel)}
        assert prev <= hit, "選択追加で結果が減少（ORでない）"
        prev = hit


def test_and_across_dimensions(cards):
    """次元間AND: フィルタ追加で結果は単調減少"""
    by_cost = {c["number"] for c in cards if match_cost(c, 3, 5)}
    by_cost_and_hp = {c["number"] for c in cards
                      if match_cost(c, 3, 5) and match_stat(c, "hp", 200)}
    assert by_cost_and_hp <= by_cost
    assert by_cost, "前提となるコスト3-5のカードが0件"


def test_cost_range_inclusive(cards):
    """コスト範囲は両端含む（境界値13のカードがmin=max=13でヒット）"""
    boundary = [c for c in cards if c.get("cost") == COST_SLIDER_MAX]
    assert boundary, "コスト13のカードが存在しない（前提データ欠損）"
    assert all(match_cost(c, COST_SLIDER_MAX, COST_SLIDER_MAX) for c in boundary)
    low = [c for c in cards if c.get("cost") == 1]
    assert low and all(match_cost(c, 1, 1) for c in low)


def test_terrain_rank_monotonic(cards):
    """地形『以上』指定: S以上 ⊆ A以上 ⊆ B以上 ⊆ C以上"""
    for ttype in sorted(TERRAIN_KEYS):
        prev = None
        for rank in RANK_ORDER:
            hit = {c["number"] for c in cards if match_terrain(c, ttype, rank)}
            if prev is not None:
                assert prev <= hit, f"{ttype}: {rank}以上で集合が縮小"
            prev = hit


def test_stat_threshold_monotonic(cards):
    """ステータス下限: 閾値を上げると結果は単調減少"""
    for key in ("mobility", "ranged", "melee", "hp"):
        prev = None
        for th in (0, 100, 200, 300, 400, 500, 700):
            hit = {c["number"] for c in cards if match_stat(c, key, th)}
            if prev is not None:
                assert hit <= prev, f"{key}>={th} で集合が拡大"
            prev = hit


def test_name_search_normalization(cards):
    """検索正規化: ローマ数字・漢数字・記号・空白の表記揺れを吸収"""
    roman = next((c for c in cards if "Ⅱ" in (c.get("name") or "")), None)
    assert roman, "Ⅱを含むカード名が存在しない（前提データ欠損）"
    assert match_name(roman, roman["name"].replace("Ⅱ", "2"))
    # ハイフン除去: 番号のハイフンなし検索でもヒット
    c0 = cards[0]
    assert match_name(c0, c0["number"].replace("-", ""))


def test_text_search_all_terms_and(cards):
    """テキスト検索: 複数語はAND（戻りカードは全語を含む）"""
    sample = next(c for c in cards
                  if c.get("search_text") and len(c["search_text"].split()) >= 2)
    words = [w for w in sample["search_text"].split()
             if normalize_search(w)][:2]
    assert len(words) == 2
    query = " ".join(words)
    hits = [c for c in cards if match_text(c, query)]
    assert sample in hits
    for c in hits:
        hay = normalize_search(c.get("search_text"))
        assert all(normalize_search(w) in hay for w in words)


def test_no_detail_passes_detail_filters(cards):
    """_noDetail(cost===null)はコスト/ステータス/地形/EB Lv.を無条件パス"""
    synthetic = {"number": "TEST-ND", "cost": None, "terrain": {}}
    assert match_cost(synthetic, 5, 10)
    assert match_stat(synthetic, "hp", 700)
    assert match_terrain(synthetic, "ground", "S")
    assert match_eb_lv(synthetic, {3})


def test_null_category_rarity_pass(cards):
    """カテゴリ/レアリティ未設定のカードはフィルタをパス"""
    synthetic = {"number": "TEST-NULL", "cost": 3}
    assert match_category(synthetic, CATEGORY_MS)
    assert match_rarity(synthetic, {"C"})


def test_ocr_gate_active_filter_desktop(cards):
    """desktopの起動条件: 詳細フィルタ単独では検索が起動しない"""
    assert not has_active_filter_desktop()  # 何も指定なし → 起動しない
    assert not has_active_filter_desktop(cost=(3, 5))  # コストのみ → 起動しない
    assert has_active_filter_desktop(name_q="ガンダム")
    assert has_active_filter_desktop(all_series=True)
    assert has_active_filter_desktop(bookmark=True)


def test_eb_lv_matches_either_level(cards):
    """EB Lv.フィルタは eb_level / eb_trigger_level のどちらでもヒット（OR）"""
    trig_only = [c for c in cards
                 if c.get("eb_trigger_level") and not c.get("eb_level")]
    if trig_only:  # 該当データがある場合のみ検証
        c = trig_only[0]
        assert match_eb_lv(c, {c["eb_trigger_level"]})
        assert not match_eb_lv(c, EB_LEVEL_UI - {c["eb_trigger_level"]})


# ===============================================================
# A-4. 到達可能性・クロスリファレンス
# ===============================================================
def test_link_index_refs_exist(cards, links):
    """link_index の全カード番号が card_index に存在すること（参照切れ検出）"""
    known = {c["number"] for c in cards}
    missing = {}
    for name, entry in links.items():
        for num in (entry.get("ms_cards") or []) + (entry.get("pl_cards") or []):
            if num not in known:
                missing.setdefault(name, []).append(num)
    assert not missing, f"link_indexの参照切れ: {dict(list(missing.items())[:5])}"


def test_search_text_nonempty(cards):
    """OCR済みカードの search_text が非空であること（テキスト検索の前提）"""
    bad = [c["number"] for c in cards if c.get("has_ocr") and not c.get("search_text")]
    assert not bad, f"search_text空のカード: {bad[:10]}"


def test_skill_name_select_source(cards):
    """PLスキル名セレクトの母集団（PLかつskill_name非空）が存在すること"""
    assert any(c.get("type") == "PL" and c.get("skill_name") for c in cards), \
        "skill_name非空のPLカードが0件（スキル名フィルタが死ぬ）"


def test_illustrator_select_source(cards):
    """イラストレーターセレクトの母集団が存在すること"""
    assert any(c.get("illustrator") and c.get("illustrator") != "不明"
               for c in cards), "有効なillustratorが0件"


def test_alt_art_detectable(cards):
    """イラスト違いトグル（番号に_を含む）の母集団が存在すること"""
    assert any("_" in c["number"] for c in cards), \
        "イラスト違いカードが0件（トグルが死ぬ）"
