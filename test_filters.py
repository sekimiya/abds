#!/usr/bin/env python3
"""
フィルタ機能テスト

フロントエンド(index.html)の applyFilters() ロジックをPythonで再現し、
card_index.json のデータがフィルタ条件に正しく対応しているか検証する。
"""

import json
import os
import re
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

ERRORS = []
WARNINGS = []


def error(msg):
    ERRORS.append(msg)
    print(f"  FAIL: {msg}")


def warn(msg):
    WARNINGS.append(msg)
    print(f"  WARN: {msg}")


def ok(msg):
    print(f"  OK: {msg}")


def load(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


INDEX = load('data/card_index.json')
DETAILS = load('data/card_details.json')
LINKS = load('data/link_index.json')


# ============================================================
# Filter helpers (mirror JS logic)
# ============================================================

def _no_detail(c):
    """JS: const _noDetail = c => c.cost === null"""
    return c.get('cost') is None


def _normalize_search(s):
    return s.lower().strip()


def filter_by_type(cards, card_type):
    return [c for c in cards if c['type'] == card_type]


def filter_by_category(cards, categories):
    return [c for c in cards if not c.get('category') or c['category'] in categories]


def filter_by_rarity(cards, rarities):
    return [c for c in cards if not c.get('rarity') or c['rarity'] in rarities]


def filter_by_series(cards, series_set):
    return [c for c in cards if c.get('series') in series_set]


def filter_by_cost(cards, cost_min, cost_max):
    return [c for c in cards if c.get('cost') is not None and cost_min <= c['cost'] <= cost_max]


def filter_by_stat(cards, stat_name, min_val):
    return [c for c in cards if _no_detail(c) or (c.get(stat_name) or 0) >= min_val]


def filter_by_terrain(cards, terrain_type, terrain_rank):
    rank_order = ['S', 'A', 'B', 'C', 'D']
    min_idx = rank_order.index(terrain_rank)
    result = []
    for c in cards:
        if _no_detail(c):
            result.append(c)
            continue
        tc = c.get('terrain') or {}
        r = tc.get(terrain_type)
        if not r:
            continue
        if rank_order.index(r) <= min_idx:
            result.append(c)
    return result


def filter_by_illustrator(cards, illustrator):
    return [c for c in cards if c.get('illustrator') == illustrator]


def filter_by_search(cards, query):
    q = _normalize_search(query)
    return [c for c in cards
            if q in _normalize_search(c.get('number', ''))
            or q in _normalize_search(c.get('name', ''))]


def filter_by_fulltext(cards, query):
    terms = [_normalize_search(t) for t in query.split()]
    return [c for c in cards
            if all(t in _normalize_search(c.get('search_text', '')) for t in terms)]


def filter_eb_category(cards, eb_cats):
    return [c for c in cards if _no_detail(c) or
            ('eb_sp' in eb_cats and c.get('has_eb')) or
            ('eb_skill' in eb_cats and c.get('has_eb_skill')) or
            ('eb_link' in eb_cats and c.get('has_eb_link'))]


def filter_eb_level(cards, levels):
    levels = [int(lv) for lv in levels]
    return [c for c in cards if _no_detail(c) or
            c.get('eb_level') in levels or c.get('eb_trigger_level') in levels]


def filter_sq_category(cards, sq_cats):
    return [c for c in cards if _no_detail(c) or
            ('sqsp' in sq_cats and c.get('has_sqsp')) or
            ('sq_skill' in sq_cats and c.get('has_sq_skill')) or
            ('sq_link' in sq_cats and c.get('has_sq_link')) or
            ('sq_rush' in sq_cats and c.get('sq_rush_effect'))]


def filter_ab_category(cards, ab_cats):
    return [c for c in cards if _no_detail(c) or
            ('ab_link' in ab_cats and c.get('has_ab_link'))]


def filter_effect_tags(cards, field, tags):
    return [c for c in cards if _no_detail(c) or
            (c.get(field) and any(t in c[field] for t in tags))]


def filter_skill_name(cards, skill_name):
    return [c for c in cards if _no_detail(c) or c.get('skill_name') == skill_name]


def filter_alt_art(cards):
    return [c for c in cards if '_' in c.get('number', '')]


# ============================================================
# Tests
# ============================================================

def test_type_filter():
    """MS/PLタイプフィルタ"""
    print("=== タイプフィルタ ===")
    ms = filter_by_type(INDEX, 'MS')
    pl = filter_by_type(INDEX, 'PL')
    if not ms:
        error("MSカードが0件")
    if not pl:
        error("PLカードが0件")
    if len(ms) + len(pl) != len(INDEX):
        error(f"MS({len(ms)})+PL({len(pl)})={len(ms)+len(pl)} != total({len(INDEX)})")
    for c in ms:
        if c['type'] != 'MS':
            error(f"{c['number']}: MSフィルタに非MSカード")
    for c in pl:
        if c['type'] != 'PL':
            error(f"{c['number']}: PLフィルタに非PLカード")
    ok(f"MS={len(ms)}, PL={len(pl)}")


def test_category_filter():
    """カテゴリフィルタ(近距離/遠距離/砲撃)"""
    print("=== カテゴリフィルタ ===")
    categories = set()
    for c in INDEX:
        if c.get('category'):
            categories.add(c['category'])
    if not categories:
        error("カテゴリが全て空")
    for cat in categories:
        result = filter_by_category(INDEX, {cat})
        if not result:
            error(f"カテゴリ '{cat}' の結果が0件")
        for c in result:
            if c.get('category') and c['category'] != cat:
                error(f"{c['number']}: カテゴリ '{cat}' でフィルタしたが '{c['category']}' が混入")
    ok(f"カテゴリ: {sorted(categories)}")


def test_rarity_filter():
    """レアリティフィルタ"""
    print("=== レアリティフィルタ ===")
    rarities = set()
    for c in INDEX:
        if c.get('rarity'):
            rarities.add(c['rarity'])
    for r in rarities:
        result = filter_by_rarity(INDEX, {r})
        actual = [c for c in result if c.get('rarity') == r]
        if not actual:
            error(f"レアリティ '{r}' の結果が0件")
    ok(f"レアリティ: {sorted(rarities)}")


def test_series_filter():
    """シリーズフィルタ"""
    print("=== シリーズフィルタ ===")
    series = set()
    for c in INDEX:
        if c.get('series'):
            series.add(c['series'])
    if not series:
        error("シリーズが全て空")
    for s in sorted(series):
        result = filter_by_series(INDEX, {s})
        if not result:
            error(f"シリーズ '{s}' の結果が0件")
        for c in result:
            if c['series'] != s:
                error(f"{c['number']}: シリーズ '{s}' に '{c['series']}' が混入")
    ok(f"{len(series)} series")


def test_cost_filter():
    """コストフィルタ"""
    print("=== コストフィルタ ===")
    costs = set()
    for c in INDEX:
        if c.get('cost') is not None:
            costs.add(c['cost'])
    if not costs:
        error("コストが全てnull")

    for cost_min, cost_max in [(0, 3), (4, 6), (7, 13), (5, 5)]:
        result = filter_by_cost(INDEX, cost_min, cost_max)
        for c in result:
            if c['cost'] < cost_min or c['cost'] > cost_max:
                error(f"{c['number']}: コスト {c['cost']} が範囲 {cost_min}-{cost_max} 外")
        if not result and cost_min <= 5:
            error(f"コスト {cost_min}-{cost_max} の結果が0件")
    ok(f"コスト値: {sorted(costs)}")


def test_stat_filters():
    """ステータスフィルタ(mobility/ranged/melee/hp)"""
    print("=== ステータスフィルタ ===")
    for stat in ('mobility', 'ranged', 'melee', 'hp'):
        values = [c.get(stat, 0) for c in INDEX if not _no_detail(c) and isinstance(c.get(stat), (int, float))]
        if not values:
            error(f"{stat}: 値なし")
            continue
        threshold = sorted(values)[len(values) // 2]
        result = filter_by_stat(INDEX, stat, threshold)
        for c in result:
            if not _no_detail(c) and (c.get(stat) or 0) < threshold:
                error(f"{c['number']}: {stat}={c.get(stat)} < threshold {threshold}")
        ok(f"{stat}: min={min(values)}, max={max(values)}, median={threshold}, filtered={len(result)}")


def test_terrain_filter():
    """地形フィルタ"""
    print("=== 地形フィルタ ===")
    terrain_types = ['ground', 'space', 'desert', 'water']
    ranks = ['S', 'A', 'B', 'C', 'D']
    valid_ranks = set(ranks)

    for tt in terrain_types:
        values = set()
        for c in INDEX:
            tc = c.get('terrain') or {}
            r = tc.get(tt)
            if r:
                values.add(r)
        invalid = values - valid_ranks
        if invalid:
            error(f"terrain.{tt}: 不正な値 {invalid}")

        if values:
            result = filter_by_terrain(INDEX, tt, 'A')
            for c in result:
                if _no_detail(c):
                    continue
                tc = c.get('terrain') or {}
                r = tc.get(tt)
                if r and ranks.index(r) > ranks.index('A'):
                    error(f"{c['number']}: terrain.{tt}={r} がAランク以上フィルタを通過")
            ok(f"terrain.{tt}: 値={sorted(values)}, A以上={len(result)}")
        else:
            warn(f"terrain.{tt}: 値を持つカードなし")


def test_terrain_null_handling():
    """terrainのnull値がフィルタで正しく除外されるか"""
    print("=== 地形null除外テスト ===")
    null_water = [c for c in INDEX
                  if not _no_detail(c) and (c.get('terrain') or {}).get('water') is None]
    result = filter_by_terrain(INDEX, 'water', 'C')
    for c in null_water:
        if c in result:
            error(f"{c['number']}: water=null がフィルタを通過してしまった")
    ok(f"water=null {len(null_water)}件が正しく除外される")


def test_illustrator_filter():
    """イラストレーターフィルタ"""
    print("=== イラストレーターフィルタ ===")
    illustrators = set()
    for c in INDEX:
        if c.get('illustrator'):
            illustrators.add(c['illustrator'])

    for ill in list(illustrators)[:3]:
        result = filter_by_illustrator(INDEX, ill)
        if not result:
            error(f"イラストレーター '{ill}' の結果が0件")
        for c in result:
            if c['illustrator'] != ill:
                error(f"{c['number']}: illustrator '{c['illustrator']}' != '{ill}'")
    ok(f"イラストレーター: {len(illustrators)}名")


def test_search_filter():
    """名前/番号検索フィルタ"""
    print("=== 名前/番号検索フィルタ ===")
    result = filter_by_search(INDEX, 'ガンダム')
    if not result:
        error("'ガンダム' 検索結果が0件")
    for c in result:
        if 'ガンダム' not in c['name'] and 'ガンダム' not in c['number'].lower():
            error(f"{c['number']}: 名前に 'ガンダム' を含まないが検索ヒット")

    result2 = filter_by_search(INDEX, 'AB01-001')
    if len(result2) < 1:
        error("'AB01-001' 検索結果が0件")

    result3 = filter_by_search(INDEX, 'zzzzzzz_no_match')
    if result3:
        error(f"存在しないキーワードで {len(result3)}件ヒット")

    ok(f"'ガンダム'={len(result)}件, 'AB01-001'={len(result2)}件, 不存在=0件")


def test_fulltext_search():
    """全文検索フィルタ"""
    print("=== 全文検索フィルタ ===")
    has_search = sum(1 for c in INDEX if c.get('search_text'))
    if has_search == 0:
        error("search_text が全て空")
        return

    result = filter_by_fulltext(INDEX, 'ビーム・サーベル')
    if not result:
        error("'ビーム・サーベル' 全文検索結果が0件")

    result2 = filter_by_fulltext(INDEX, 'ビーム サーベル')
    if not result2:
        warn("スペース区切り検索 'ビーム サーベル' 結果が0件")

    result3 = filter_by_fulltext(INDEX, '連撃 ロックオン')
    if not result3:
        warn("AND検索 '連撃 ロックオン' 結果が0件")

    ok(f"search_text入り={has_search}件, 'ビーム・サーベル'={len(result)}件")


def test_eb_filters():
    """ECHOES BEAT関連フィルタ"""
    print("=== ECHOES BEATフィルタ ===")
    has_eb = [c for c in INDEX if c.get('has_eb')]
    has_eb_skill = [c for c in INDEX if c.get('has_eb_skill')]
    has_eb_link = [c for c in INDEX if c.get('has_eb_link')]

    if not has_eb and not has_eb_skill and not has_eb_link:
        warn("EB関連カードが0件")
        return

    result = filter_eb_category(INDEX, {'eb_sp'})
    non_detail_count = sum(1 for c in result if _no_detail(c))
    for c in result:
        if not _no_detail(c) and not c.get('has_eb'):
            error(f"{c['number']}: has_eb=false がeb_spフィルタを通過")

    result2 = filter_eb_category(INDEX, {'eb_skill'})
    for c in result2:
        if not _no_detail(c) and not c.get('has_eb_skill'):
            error(f"{c['number']}: has_eb_skill=false がeb_skillフィルタを通過")

    result3 = filter_eb_category(INDEX, {'eb_link'})
    for c in result3:
        if not _no_detail(c) and not c.get('has_eb_link'):
            error(f"{c['number']}: has_eb_link=false がeb_linkフィルタを通過")

    eb_levels = set()
    for c in INDEX:
        if c.get('eb_level') is not None:
            eb_levels.add(c['eb_level'])
        if c.get('eb_trigger_level') is not None:
            eb_levels.add(c['eb_trigger_level'])
    if eb_levels:
        for lv in sorted(eb_levels):
            lv_result = filter_eb_level(INDEX, {lv})
            for c in lv_result:
                if not _no_detail(c) and c.get('eb_level') != lv and c.get('eb_trigger_level') != lv:
                    error(f"{c['number']}: eb_level={c.get('eb_level')}, eb_trigger_level={c.get('eb_trigger_level')} != Lv.{lv}")

    ok(f"EB SP={len(has_eb)}, EB Skill={len(has_eb_skill)}, EB Link={len(has_eb_link)}, Levels={sorted(eb_levels)}")


def test_sq_filters():
    """SQUAD関連フィルタ"""
    print("=== SQUADフィルタ ===")
    has_sqsp = [c for c in INDEX if c.get('has_sqsp')]
    has_sq_skill = [c for c in INDEX if c.get('has_sq_skill')]
    has_sq_link = [c for c in INDEX if c.get('has_sq_link')]
    has_sq_rush = [c for c in INDEX if c.get('sq_rush_effect')]

    result = filter_sq_category(INDEX, {'sqsp'})
    for c in result:
        if not _no_detail(c) and not c.get('has_sqsp'):
            error(f"{c['number']}: has_sqsp=false がsqspフィルタを通過")

    result2 = filter_sq_category(INDEX, {'sq_skill'})
    for c in result2:
        if not _no_detail(c) and not c.get('has_sq_skill'):
            error(f"{c['number']}: has_sq_skill=false がsq_skillフィルタを通過")

    result3 = filter_sq_category(INDEX, {'sq_link'})
    for c in result3:
        if not _no_detail(c) and not c.get('has_sq_link'):
            error(f"{c['number']}: has_sq_link=false がsq_linkフィルタを通過")

    result4 = filter_sq_category(INDEX, {'sq_rush'})
    for c in result4:
        if not _no_detail(c) and not c.get('sq_rush_effect'):
            error(f"{c['number']}: sq_rush_effect 空がsq_rushフィルタを通過")

    ok(f"SQSP={len(has_sqsp)}, SQ Skill={len(has_sq_skill)}, SQ Link={len(has_sq_link)}, SQ Rush={len(has_sq_rush)}")


def test_ab_filter():
    """ABリンクフィルタ"""
    print("=== ABリンクフィルタ ===")
    has_ab = [c for c in INDEX if c.get('has_ab_link')]

    result = filter_ab_category(INDEX, {'ab_link'})
    for c in result:
        if not _no_detail(c) and not c.get('has_ab_link'):
            error(f"{c['number']}: has_ab_link=false がab_linkフィルタを通過")

    ok(f"AB Link={len(has_ab)}")


def test_effect_tag_filters():
    """エフェクトタグフィルタ"""
    print("=== エフェクトタグフィルタ ===")
    tag_fields = {
        'sp_effect_tags': 'SP効果',
        'sqsp_effect_tags': 'SQSP効果',
        'ebsp_effect_tags': 'EBSP効果',
        'sq_skill_effect_tags': 'SQスキル効果',
        'skill_effect_tags': 'スキル効果',
    }

    for field, label in tag_fields.items():
        all_tags = set()
        for c in INDEX:
            tags = c.get(field) or []
            if not isinstance(tags, list):
                error(f"{c['number']}: {field} is {type(tags).__name__}, not list")
                continue
            all_tags.update(tags)

        has_tags = sum(1 for c in INDEX if c.get(field))
        if all_tags:
            for tag in list(all_tags)[:2]:
                result = filter_effect_tags(INDEX, field, {tag})
                for c in result:
                    if not _no_detail(c) and tag not in (c.get(field) or []):
                        error(f"{c['number']}: {field}にタグ '{tag}' がないのにフィルタ通過")
        ok(f"{label}({field}): tags={sorted(all_tags)}, カード数={has_tags}")


def test_skill_name_filter():
    """PLスキル名フィルタ"""
    print("=== PLスキル名フィルタ ===")
    skill_names = set()
    for c in INDEX:
        if c.get('skill_name'):
            skill_names.add(c['skill_name'])

    if not skill_names:
        warn("skill_nameが全て空")
        return

    for sn in list(skill_names)[:3]:
        result = filter_skill_name(INDEX, sn)
        for c in result:
            if not _no_detail(c) and c.get('skill_name') != sn:
                error(f"{c['number']}: skill_name '{c.get('skill_name')}' != '{sn}'")

    ok(f"スキル名: {len(skill_names)}種")


def test_alt_art_filter():
    """イラスト違いフィルタ"""
    print("=== イラスト違いフィルタ ===")
    result = filter_alt_art(INDEX)
    for c in result:
        if '_' not in c['number']:
            error(f"{c['number']}: '_' を含まないのにイラスト違いフィルタ通過")
    non_alt = [c for c in INDEX if '_' not in c['number']]
    for c in non_alt:
        if c in result:
            error(f"{c['number']}: 通常カードがイラスト違いフィルタ通過")
    ok(f"イラスト違い={len(result)}件")


def test_link_search():
    """リンクアビリティ検索"""
    print("=== リンクアビリティ検索 ===")
    if not LINKS:
        error("link_index.json が空")
        return

    for link_name in list(LINKS.keys())[:3]:
        link_data = LINKS[link_name]
        card_set = set(link_data.get('ms_cards', []) + link_data.get('pl_cards', []))
        if not card_set:
            warn(f"リンク '{link_name}' に所属カードなし")
            continue
        result = [c for c in INDEX if c['number'] in card_set]
        if not result:
            error(f"リンク '{link_name}' のカードが card_index に存在しない")

        for num in card_set:
            detail = DETAILS.get(num)
            if not detail:
                continue
            ocr = detail.get('ocr_data', {})
            link_names = [la.get('name', '') for la in (ocr.get('link_ability') or []) if isinstance(la, dict)]
            clean_names = [re.sub(r'^\[(SQ|EB|AB)\]\s*', '', n) for n in link_names]
            if link_name not in clean_names:
                warn(f"{num}: link_index '{link_name}' に登録されているが card_details のlink_abilityに未記載")

    ok(f"リンク数={len(LINKS)}")


def test_combined_filters():
    """複合フィルタ(複数条件同時適用)"""
    print("=== 複合フィルタ ===")

    cards = [c for c in INDEX if c.get('has_ocr')]
    cards = filter_by_type(cards, 'MS')
    cards = filter_by_category(cards, {'近距離'})
    cards = filter_by_cost(cards, 4, 6)
    cards = filter_by_stat(cards, 'melee', 200)

    for c in cards:
        if c['type'] != 'MS':
            error(f"{c['number']}: MS以外が混入")
        if c.get('category') and c['category'] != '近距離':
            error(f"{c['number']}: 近距離以外が混入")
        if c['cost'] < 4 or c['cost'] > 6:
            error(f"{c['number']}: コスト範囲外")
        if not _no_detail(c) and c.get('melee', 0) < 200:
            error(f"{c['number']}: melee < 200")

    ok(f"MS + 近距離 + コスト4-6 + melee>=200 = {len(cards)}件")

    cards2 = [c for c in INDEX if c.get('has_ocr')]
    cards2 = filter_by_type(cards2, 'PL')
    cards2 = filter_eb_category(cards2, {'eb_skill'})
    cards2 = filter_by_rarity(cards2, {'R', 'M'})

    for c in cards2:
        if c['type'] != 'PL':
            error(f"{c['number']}: PL以外が混入")
        if not _no_detail(c) and not c.get('has_eb_skill'):
            error(f"{c['number']}: EB Skillなしが混入")
        if c.get('rarity') and c['rarity'] not in ('R', 'M'):
            error(f"{c['number']}: レアリティ R/M以外が混入")

    ok(f"PL + EB Skill + R/M = {len(cards2)}件")


def test_filter_field_presence():
    """フィルタが参照する全フィールドが存在するか"""
    print("=== フィルタ参照フィールド存在チェック ===")
    required_fields = [
        'number', 'name', 'type', 'category', 'cost', 'series', 'rarity',
        'front_url', 'back_url', 'has_ocr',
        'mobility', 'ranged', 'melee', 'hp',
        'terrain', 'search_text',
        'pilot', 'model', 'illustrator',
        'has_eb', 'has_eb_skill', 'has_eb_link', 'has_ab_link',
        'eb_level', 'eb_trigger_level', 'eb_trigger_cond', 'eb_type',
        'eb_text', 'eb_skill_text',
        'has_sqsp', 'has_sq_skill', 'has_sq_link',
        'sqsp_text', 'sq_skill_text', 'sq_rush_effect',
        'sq_trigger', 'sq_gauge_rate',
        'sp_effect_tags', 'sqsp_effect_tags', 'ebsp_effect_tags',
        'sq_skill_effect_tags', 'skill_effect_tags',
        'skill_name', 'ability_name',
    ]
    missing = {}
    for c in INDEX:
        for f in required_fields:
            if f not in c:
                missing.setdefault(f, []).append(c['number'])

    if missing:
        for f, nums in missing.items():
            error(f"フィールド '{f}' が {len(nums)}件で欠落 (例: {nums[:3]})")
    else:
        ok(f"全{len(required_fields)}フィールドが全{len(INDEX)}件に存在")


def test_terrain_field_values():
    """terrain内の値がS/A/B/C/D/nullのいずれかであること"""
    print("=== terrain値バリデーション ===")
    valid = {'S', 'A', 'B', 'C', 'D', None}
    bad = []
    for c in INDEX:
        tc = c.get('terrain') or {}
        for key in ('ground', 'space', 'desert', 'water'):
            val = tc.get(key)
            if val not in valid:
                bad.append(f"{c['number']}.terrain.{key}={val!r}")
    if bad:
        for b in bad[:10]:
            error(b)
    else:
        ok(f"全terrain値がS/A/B/C/D/nullのいずれか")


def test_eb_level_values():
    """eb_level/eb_trigger_levelがint or nullであること"""
    print("=== EB Level型チェック ===")
    bad = []
    for c in INDEX:
        for f in ('eb_level', 'eb_trigger_level'):
            val = c.get(f)
            if val is not None and not isinstance(val, int):
                bad.append(f"{c['number']}.{f}={val!r} ({type(val).__name__})")
    if bad:
        for b in bad[:10]:
            error(b)
    else:
        ok("eb_level/eb_trigger_level は全て int|null")


# ============================================================
# Main
# ============================================================

if __name__ == '__main__':
    test_filter_field_presence()
    test_type_filter()
    test_category_filter()
    test_rarity_filter()
    test_series_filter()
    test_cost_filter()
    test_stat_filters()
    test_terrain_filter()
    test_terrain_null_handling()
    test_terrain_field_values()
    test_illustrator_filter()
    test_search_filter()
    test_fulltext_search()
    test_eb_filters()
    test_eb_level_values()
    test_sq_filters()
    test_ab_filter()
    test_effect_tag_filters()
    test_skill_name_filter()
    test_alt_art_filter()
    test_link_search()
    test_combined_filters()

    print()
    print(f"=== RESULTS ===")
    print(f"Errors: {len(ERRORS)}")
    print(f"Warnings: {len(WARNINGS)}")
    if ERRORS:
        print("\nFAILED:")
        for e in ERRORS[:30]:
            print(f"  {e}")
        if len(ERRORS) > 30:
            print(f"  ... and {len(ERRORS) - 30} more")
        sys.exit(1)
    else:
        print("\nALL PASSED")
        sys.exit(0)
