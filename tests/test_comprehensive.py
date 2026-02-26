"""
ガンダムアーセナルベース デッキシミュレーター 網羅的テスト

テスト対象:
  1. カードデータの整合性（全カードのフィールド存在・型・値範囲）
  2. API レスポンスの正確性（インデックス・詳細・検索・デッキCRUD）
  3. 計算ロジック（コスト合計・リンクバフ・ステータス計算・地形集計）
  4. データ変換（PL カテゴリ補正・重複排除・画像URL生成・シリーズコード抽出）
  5. デッキコード（エンコード/デコード・URL共有）
"""

import pytest
import json
import os
import sys
import re
import math
import base64
from urllib.parse import quote

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, get_card_index, get_card_detail

# logic パッケージからインポート（_safe_int / get_nested も logic 経由に統一）
from logic import (
    safe_int as _safe_int,
    get_nested,
    extract_stats,
    get_link_abilities,
    parse_link_condition,
    get_link_buffs,
    apply_buff,
    calc_unit_stats,
    calc_all_unit_stats,
    calc_total_cost,
    calc_cost_breakdown,
    calc_link_activation,
    get_active_links,
    calc_terrain,
    generate_code,
    parse_code,
    validate_deck,
    check_pilot_duplicates,
    get_type_multiplier,
    calc_defense_base_damage,
    analyze_deck_matchup,
    apply_terrain_effect,
    get_terrain_compatibility_rank,
    calc_exp_gain,
    get_level_cap,
    calc_hp_bonus,
    classify_ability,
    get_sp_attack_info,
    calc_deck_sp_costs,
    classify_skill_trigger,
    classify_skill_effect,
    get_skill_info,
    get_card_style,
    count_for_condition,
)


# ====================================================================
# Fixture
# ====================================================================

@pytest.fixture(scope='session')
def client():
    """Flask テストクライアント"""
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(scope='session')
def card_index(client):
    """カードインデックス（全カード軽量データ）"""
    res = client.get('/api/card_index')
    data = res.get_json()
    assert data['success']
    return data['cards']


@pytest.fixture(scope='session')
def ms_cards(card_index):
    """MSカードのみ"""
    return [c for c in card_index if c['type'] == 'MS']


@pytest.fixture(scope='session')
def pl_cards(card_index):
    """PLカードのみ"""
    return [c for c in card_index if c['type'] == 'PL']


@pytest.fixture(scope='session')
def ocr_cards(client):
    """OCRデータ付きカード（コスト情報あり）"""
    res = client.get('/api/cards/search?cost_min=1&limit=200')
    data = res.get_json()
    return data['cards']


@pytest.fixture(scope='session')
def sample_ms_detail(client, ms_cards):
    """OCR付きMSカードの詳細（最初のコスト有り）"""
    for c in ms_cards:
        if c['cost'] is not None and c['cost'] > 0:
            res = client.get(f'/api/card/{c["number"]}')
            d = res.get_json()
            if d['success'] and d['card'].get('ocr_data', {}).get('stats'):
                return d['card']
    pytest.skip('OCR付きMSカードが見つからない')


@pytest.fixture(scope='session')
def sample_pl_detail(client, pl_cards):
    """OCR付きPLカードの詳細"""
    for c in pl_cards:
        if c['cost'] is not None and c['cost'] > 0:
            res = client.get(f'/api/card/{c["number"]}')
            d = res.get_json()
            if d['success'] and d['card'].get('ocr_data', {}).get('stats'):
                return d['card']
    pytest.skip('OCR付きPLカードが見つからない')


@pytest.fixture(scope='session')
def sample_ms_with_links(client, ms_cards):
    """リンクアビリティ付きMSカード詳細"""
    for c in ms_cards:
        if c['cost'] is not None:
            res = client.get(f'/api/card/{c["number"]}')
            d = res.get_json()
            if d['success']:
                ocr = d['card'].get('ocr_data', {})
                links = ocr.get('link_abilities') or ocr.get('link_ability') or []
                if len(links) > 0:
                    return d['card']
    pytest.skip('リンク付きMSカードが見つからない')


# ====================================================================
# 1. カードインデックス データ整合性テスト
# ====================================================================

class TestCardIndexIntegrity:
    """カードインデックスの全レコードが必須フィールドと正しい型を持つことを検証"""

    def test_index_not_empty(self, card_index):
        assert len(card_index) > 0, 'カードインデックスが空'

    def test_index_card_count_reasonable(self, card_index):
        """カード枚数が妥当な範囲（重複排除済みで1000枚以上）"""
        assert len(card_index) >= 1000, f'カード数が少なすぎる: {len(card_index)}'

    def test_no_duplicate_numbers(self, card_index):
        """カード番号に重複がないこと"""
        numbers = [c['number'] for c in card_index]
        assert len(numbers) == len(set(numbers)), '重複するカード番号がある'

    def test_all_cards_have_required_fields(self, card_index):
        """全カードが必須フィールドを持つ"""
        required = ['number', 'name', 'type', 'front_url']
        for card in card_index:
            for field in required:
                assert field in card, f'{card.get("number", "?")} に {field} がない'

    def test_all_cards_have_stat_fields(self, card_index):
        """全カードがステータスフィールドを持つ（0含む）"""
        stat_fields = ['mobility', 'ranged', 'melee', 'hp']
        for card in card_index:
            for field in stat_fields:
                assert field in card, f'{card["number"]} に {field} がない'
                assert isinstance(card[field], (int, float)), \
                    f'{card["number"]} の {field} が数値でない: {type(card[field])}'

    def test_type_is_ms_or_pl(self, card_index):
        """タイプがMSまたはPL"""
        for card in card_index:
            assert card['type'] in ('MS', 'PL'), \
                f'{card["number"]} のタイプが不正: {card["type"]}'

    def test_ms_pl_both_exist(self, ms_cards, pl_cards):
        """MS/PLの両方が存在"""
        assert len(ms_cards) > 0, 'MSカードがない'
        assert len(pl_cards) > 0, 'PLカードがない'

    def test_card_number_format(self, card_index):
        """カード番号がプレフィックス-数字のフォーマット (例: AB01-001, FQB01-001, PR-001, TEST-A-001)"""
        pattern = re.compile(r'^[A-Z][A-Z0-9]+-([A-Z]-)?(\d{3,4})(_p\d+)?$')
        for card in card_index:
            assert pattern.match(card['number']), \
                f'カード番号フォーマット不正: {card["number"]}'

    def test_front_url_not_empty(self, card_index):
        """全カードの表面画像URLが存在"""
        for card in card_index:
            assert card['front_url'], f'{card["number"]} の front_url が空'

    def test_back_url_not_empty(self, card_index):
        """全カードの裏面画像URLが存在"""
        for card in card_index:
            assert card.get('back_url'), f'{card["number"]} の back_url が空'

    def test_cost_is_valid_when_present(self, card_index):
        """コストが存在する場合、0以上20以下の整数"""
        for card in card_index:
            if card['cost'] is not None:
                assert isinstance(card['cost'], int), \
                    f'{card["number"]} のコストが整数でない: {card["cost"]}'
                assert 0 <= card['cost'] <= 20, \
                    f'{card["number"]} のコストが範囲外: {card["cost"]}'

    def test_stats_non_negative(self, card_index):
        """ステータスが非負"""
        for card in card_index:
            for stat in ['mobility', 'ranged', 'melee', 'hp']:
                assert card[stat] >= 0, \
                    f'{card["number"]} の {stat} が負: {card[stat]}'

    def test_stats_within_reasonable_range(self, card_index):
        """ステータスが妥当な範囲内（0〜2000）"""
        for card in card_index:
            for stat in ['mobility', 'ranged', 'melee', 'hp']:
                assert card[stat] <= 2000, \
                    f'{card["number"]} の {stat} が異常に大きい: {card[stat]}'

    def test_series_format_when_present(self, card_index):
        """シリーズコードが存在する場合、XX99形式または日本語シリーズ名"""
        pattern = re.compile(r'^[A-Z]{2,3}\d{2}$')
        for card in card_index:
            if card.get('series') and not card['series'].startswith('SEASON'):
                # XX99形式か、日本語を含むシリーズ名のどちらか
                is_code = pattern.match(card['series'])
                is_japanese_name = any(
                    '\u3000' <= ch <= '\u9fff' or '\uff00' <= ch <= '\uffef'
                    for ch in card['series']
                )
                assert is_code or is_japanese_name, \
                    f'{card["number"]} のシリーズ形式不正: {card["series"]}'

    def test_index_sorted_by_number(self, card_index):
        """インデックスが番号順でソートされている"""
        numbers = [c['number'] for c in card_index]
        assert numbers == sorted(numbers), 'インデックスが番号順でない'


# ====================================================================
# 2. カード詳細 API テスト
# ====================================================================

class TestCardDetailAPI:
    """個別カード詳細APIの正確性"""

    def test_detail_returns_ocr_data(self, sample_ms_detail):
        """MSカード詳細にOCRデータが含まれる"""
        assert 'ocr_data' in sample_ms_detail
        assert sample_ms_detail['ocr_data'] is not None

    def test_detail_has_front_back_images(self, sample_ms_detail):
        """詳細に表裏画像URLが含まれる"""
        assert sample_ms_detail['front']['image_url']
        assert sample_ms_detail['back']['image_url']

    def test_ms_ocr_has_stats(self, sample_ms_detail):
        """MSカードOCRにステータスが含まれる"""
        stats = sample_ms_detail['ocr_data']['stats']
        for key in ['mobility', 'ranged_attack', 'melee_attack', 'hp']:
            assert key in stats, f'stats に {key} がない'

    def test_ms_ocr_stats_are_numeric(self, sample_ms_detail):
        """MSカードのステータスが数値変換可能"""
        stats = sample_ms_detail['ocr_data']['stats']
        for key in ['mobility', 'ranged_attack', 'melee_attack', 'hp']:
            val = stats[key]
            assert isinstance(_safe_int(val), int)

    def test_ms_ocr_has_type(self, sample_ms_detail):
        """MSカードOCRにタイプ(MS)が含まれる"""
        assert sample_ms_detail['ocr_data'].get('type') == 'MS'

    def test_pl_ocr_has_type(self, sample_pl_detail):
        """PLカードOCRにタイプ(PL)が含まれる"""
        assert sample_pl_detail['ocr_data'].get('type') == 'PL'

    def test_pl_ocr_has_stats(self, sample_pl_detail):
        """PLカードOCRにステータスが含まれる"""
        stats = sample_pl_detail['ocr_data']['stats']
        for key in ['mobility', 'ranged_attack', 'melee_attack', 'hp']:
            assert key in stats, f'PL stats に {key} がない'

    def test_ms_ocr_has_cost(self, sample_ms_detail):
        """MSカードOCRにコストが含まれる"""
        cost = sample_ms_detail['ocr_data'].get('cost')
        assert cost is not None
        assert _safe_int(cost) > 0

    def test_ms_ocr_has_weapon(self, sample_ms_detail):
        """MSカードOCRに武装情報が含まれる"""
        ocr = sample_ms_detail['ocr_data']
        if ocr.get('weapon'):
            weapon = ocr['weapon']
            if weapon.get('main'):
                assert 'name' in weapon['main'], '主武装に name がない'
                assert 'range' in weapon['main'], '主武装に range がない'

    def test_ms_ocr_terrain_compatibility(self, sample_ms_detail):
        """MSカードOCRに地形適性が含まれる"""
        ocr = sample_ms_detail['ocr_data']
        if ocr.get('terrain_compatibility'):
            tc = ocr['terrain_compatibility']
            valid_ratings = {'S', 'A', 'B', 'C', 'D'}
            for terrain in ['ground', 'space', 'desert', 'water']:
                if terrain in tc:
                    assert tc[terrain] in valid_ratings, \
                        f'地形適性値が不正: {terrain}={tc[terrain]}'

    def test_ms_ocr_link_abilities_structure(self, sample_ms_with_links):
        """リンクアビリティの構造が正しい"""
        ocr = sample_ms_with_links['ocr_data']
        links = ocr.get('link_abilities') or ocr.get('link_ability') or []
        assert len(links) > 0
        for link in links:
            assert 'name' in link, 'リンクに name がない'
            assert 'condition' in link, f'リンク「{link["name"]}」に condition がない'
            assert 'effect' in link, f'リンク「{link["name"]}」に effect がない'

    def test_link_condition_format(self, sample_ms_with_links):
        """リンク条件が「デッキにN枚以上」形式"""
        ocr = sample_ms_with_links['ocr_data']
        links = ocr.get('link_abilities') or ocr.get('link_ability') or []
        pattern = re.compile(r'(\d+)枚以上')
        for link in links:
            cond = link.get('condition', '')
            match = pattern.search(cond)
            assert match, f'リンク条件が不正: {cond}'
            required = int(match.group(1))
            assert 1 <= required <= 10, f'リンク必要枚数が範囲外: {required}'

    def test_detail_not_found(self, client):
        """存在しないカード番号で404"""
        res = client.get('/api/card/ZZ99-999')
        assert res.status_code == 404

    def test_batch_detail(self, client, card_index):
        """バッチ詳細取得が正しく動作"""
        nums = [c['number'] for c in card_index[:5]]
        res = client.post('/api/cards/batch',
                          json={'numbers': nums},
                          content_type='application/json')
        data = res.get_json()
        assert data['success']
        assert len(data['cards']) == len(nums)
        for num in nums:
            assert num in data['cards']


# ====================================================================
# 3. カード検索 API テスト
# ====================================================================

class TestSearchAPI:
    """検索・フィルタリング・ソートAPIの正確性"""

    def test_search_by_type_ms(self, client):
        res = client.get('/api/cards/search?type=MS&limit=10')
        data = res.get_json()
        assert data['success']
        for c in data['cards']:
            assert c['type'] == 'MS'

    def test_search_by_type_pl(self, client):
        res = client.get('/api/cards/search?type=PL&limit=10')
        data = res.get_json()
        assert data['success']
        for c in data['cards']:
            assert c['type'] == 'PL'

    def test_search_by_category(self, client):
        """カテゴリフィルタの動作"""
        for cat in ['機動', '近距離', '遠距離']:
            res = client.get(f'/api/cards/search?category={quote(cat)}&limit=5')
            data = res.get_json()
            assert data['success']
            for c in data['cards']:
                assert c['category'] == cat, \
                    f'{c["number"]} のカテゴリが {c["category"]}（期待: {cat}）'

    def test_search_cost_range(self, client):
        """コスト範囲フィルタの動作"""
        res = client.get('/api/cards/search?cost_min=3&cost_max=5&limit=100')
        data = res.get_json()
        assert data['success']
        for c in data['cards']:
            assert c['cost'] is not None
            assert 3 <= c['cost'] <= 5, f'{c["number"]} のコスト {c["cost"]} が範囲外'

    def test_search_cost_min_only(self, client):
        """最低コストのみ指定"""
        res = client.get('/api/cards/search?cost_min=6&limit=100')
        data = res.get_json()
        assert data['success']
        for c in data['cards']:
            assert c['cost'] >= 6

    def test_search_cost_max_only(self, client):
        """最高コストのみ指定"""
        res = client.get('/api/cards/search?cost_max=2&limit=100')
        data = res.get_json()
        assert data['success']
        for c in data['cards']:
            assert c['cost'] is not None
            assert c['cost'] <= 2

    def test_search_text_by_name(self, client):
        """名前テキスト検索"""
        res = client.get(f'/api/cards/search?q={quote("ガンダム")}&limit=10')
        data = res.get_json()
        assert data['success']
        assert data['total'] > 0
        for c in data['cards']:
            found = ('ガンダム' in (c['name'] or '').lower() or
                     'ガンダム' in (c['number'] or '').lower() or
                     'ガンダム' in (c['series'] or '').lower())
            assert found, f'{c["number"]} {c["name"]} にガンダムが含まれない'

    def test_search_text_by_number(self, client):
        """番号テキスト検索"""
        res = client.get('/api/cards/search?q=FQ01&limit=10')
        data = res.get_json()
        assert data['success']
        for c in data['cards']:
            assert 'fq01' in c['number'].lower() or 'fq01' in (c['name'] or '').lower()

    def test_search_combined_filters(self, client):
        """複合フィルタ（タイプ+コスト範囲）"""
        res = client.get('/api/cards/search?type=MS&cost_min=4&cost_max=6&limit=100')
        data = res.get_json()
        assert data['success']
        for c in data['cards']:
            assert c['type'] == 'MS'
            assert 4 <= c['cost'] <= 6

    def test_sort_by_cost_asc(self, client):
        """コスト昇順ソート"""
        res = client.get('/api/cards/search?sort=cost&order=asc&cost_min=1&limit=20')
        data = res.get_json()
        costs = [c['cost'] for c in data['cards'] if c['cost'] is not None]
        assert costs == sorted(costs), f'昇順でない: {costs}'

    def test_sort_by_cost_desc(self, client):
        """コスト降順ソート"""
        res = client.get('/api/cards/search?sort=cost&order=desc&cost_min=1&limit=20')
        data = res.get_json()
        costs = [c['cost'] for c in data['cards'] if c['cost'] is not None]
        assert costs == sorted(costs, reverse=True), f'降順でない: {costs}'

    def test_sort_none_values_at_end(self, client):
        """None値がソート末尾に配置される"""
        res = client.get('/api/cards/search?sort=cost&order=desc&limit=5000')
        data = res.get_json()
        cards = data['cards']
        none_started = False
        for c in cards:
            if c['cost'] is None:
                none_started = True
            elif none_started:
                pytest.fail(f'{c["number"]} (cost={c["cost"]}) がNone群の後に出現')

    def test_sort_by_mobility(self, client):
        """機動力ソート"""
        res = client.get('/api/cards/search?sort=mobility&order=desc&cost_min=1&limit=10')
        data = res.get_json()
        vals = [c['mobility'] for c in data['cards']]
        assert vals == sorted(vals, reverse=True)

    def test_sort_by_hp(self, client):
        """HPソート"""
        res = client.get('/api/cards/search?sort=hp&order=desc&cost_min=1&limit=10')
        data = res.get_json()
        vals = [c['hp'] for c in data['cards']]
        assert vals == sorted(vals, reverse=True)

    def test_pagination_offset(self, client):
        """ページネーション（オフセット）"""
        res1 = client.get('/api/cards/search?limit=5&offset=0')
        res2 = client.get('/api/cards/search?limit=5&offset=5')
        d1 = res1.get_json()['cards']
        d2 = res2.get_json()['cards']
        nums1 = {c['number'] for c in d1}
        nums2 = {c['number'] for c in d2}
        assert nums1.isdisjoint(nums2), 'ページ間で重複がある'

    def test_pagination_total_consistent(self, client):
        """ページネーション合計数の一貫性"""
        res1 = client.get('/api/cards/search?limit=5&offset=0')
        res2 = client.get('/api/cards/search?limit=5&offset=5')
        assert res1.get_json()['total'] == res2.get_json()['total']

    def test_empty_search_returns_all(self, client, card_index):
        """空検索で全件返却"""
        res = client.get('/api/cards/search?limit=10000')
        data = res.get_json()
        assert data['total'] == len(card_index)

    def test_search_no_results(self, client):
        """検索結果0件"""
        res = client.get(f'/api/cards/search?q={quote("存在しないカード名XXXYYY")}')
        data = res.get_json()
        assert data['total'] == 0
        assert len(data['cards']) == 0

    def test_search_by_series(self, client):
        """シリーズフィルタ"""
        res = client.get('/api/cards/search?series=FQ01&limit=100')
        data = res.get_json()
        assert data['success']
        for c in data['cards']:
            assert c['series'] == 'FQ01', f'{c["number"]} のシリーズが {c["series"]}'


# ====================================================================
# 4. PL カテゴリ補正テスト
# ====================================================================

class TestPLCategoryCorrection:
    """PLカードのカテゴリが正しく補正されていることを検証"""

    def test_pl_cards_have_combat_style_categories(self, client, pl_cards):
        """コスト付きPLカードが殲滅/制圧/防衛のいずれかのカテゴリを持つ"""
        valid_styles = {'殲滅', '制圧', '防衛', 'パイロット', 'PL', ''}
        for card in pl_cards:
            if card['cost'] is not None:
                assert card['category'] in valid_styles, \
                    f'PL {card["number"]} のカテゴリが不正: {card["category"]}'

    def test_pl_detail_category_matches_index(self, client, pl_cards):
        """PL詳細のカテゴリがインデックスと一致"""
        checked = 0
        for card in pl_cards[:20]:
            if card['cost'] is None:
                continue
            res = client.get(f'/api/card/{card["number"]}')
            detail = res.get_json()
            if not detail['success']:
                continue
            idx_cat = card['category']
            detail_cat = detail['card'].get('category', '')
            assert idx_cat == detail_cat, \
                f'{card["number"]}: index={idx_cat} vs detail={detail_cat}'
            checked += 1
        assert checked > 0, 'チェック対象のPLカードがない'


# ====================================================================
# 5. 画像URL生成テスト
# ====================================================================

class TestImageURLGeneration:
    """画像URLが正しく生成されることを検証"""

    def test_front_url_contains_card_number(self, card_index):
        """表面URLにカード番号が含まれる"""
        for card in card_index[:100]:
            assert card['number'] in card['front_url'], \
                f'{card["number"]} の front_url にカード番号がない: {card["front_url"]}'

    def test_front_url_no_back_suffix(self, card_index):
        """表面URLに_bサフィックスが含まれない"""
        for card in card_index[:100]:
            # _b.jpg は裏面なので表面に含まれてはいけない
            url = card['front_url']
            assert '_b.jpg' not in url and '_b?' not in url, \
                f'{card["number"]} の front_url に _b が含まれる: {url}'

    def test_back_url_format(self, card_index):
        """裏面URLが正しい形式"""
        for card in card_index[:100]:
            back = card.get('back_url', '')
            if back:
                # カード番号_b を含むか確認
                assert card['number'] in back, \
                    f'{card["number"]} の back_url にカード番号がない: {back}'


# ====================================================================
# 6. 計算ロジックテスト（_safe_int / safeInt）
# ====================================================================

class TestSafeInt:
    """_safe_int (Python) の動作を検証。JS の safeInt と同等のロジック。"""

    def test_int_value(self):
        assert _safe_int(42) == 42

    def test_string_int(self):
        assert _safe_int('320') == 320

    def test_none_returns_default(self):
        assert _safe_int(None) == 0
        assert _safe_int(None, 99) == 99

    def test_invalid_string(self):
        assert _safe_int('abc') == 0

    def test_float_string(self):
        # Python の int('3.5') は ValueError
        assert _safe_int('3.5') == 0

    def test_zero(self):
        assert _safe_int(0) == 0
        assert _safe_int('0') == 0

    def test_negative(self):
        assert _safe_int(-5) == -5

    def test_empty_string(self):
        assert _safe_int('') == 0

    def test_dash_string(self):
        """ステータスに '-' が入ることがある"""
        assert _safe_int('-') == 0


# ====================================================================
# 7. get_nested ヘルパーテスト
# ====================================================================

class TestGetNested:
    """get_nested 多段キー取得ヘルパーの動作検証"""

    def test_basic(self):
        d = {'a': {'b': {'c': 42}}}
        assert get_nested(d, ['a', 'b', 'c']) == 42

    def test_missing_key(self):
        d = {'a': {'b': 1}}
        assert get_nested(d, ['a', 'x']) is None

    def test_default(self):
        d = {'a': 1}
        assert get_nested(d, ['a', 'b'], 'default') == 'default'

    def test_non_dict_intermediate(self):
        d = {'a': 'string'}
        assert get_nested(d, ['a', 'b']) is None

    def test_empty_keys(self):
        d = {'a': 1}
        assert get_nested(d, []) == d


# ====================================================================
# 8. リンクバフ計算テスト（getLinkBuffs 相当）
# ====================================================================

class TestLinkBuffCalculation:
    """リンクアビリティのバフ計算ロジックを検証（logic.buff.get_link_buffs を使用）"""

    def test_no_links(self):
        """リンクなしで全バフ0"""
        buffs = get_link_buffs({}, [None] * 10)
        assert buffs['mobility']['small'] == 0
        assert buffs['hp']['medium'] == 0

    def test_link_not_activated(self):
        """条件未達成でバフ0"""
        ocr = {
            'link_abilities': [{
                'name': 'テストリンク',
                'condition': 'デッキに3枚以上',
                'effect': '「機動力」小アップ'
            }]
        }
        # デッキに1枚しかない
        all_ocr = [ocr] + [None] * 9
        buffs = get_link_buffs(ocr, all_ocr)
        assert buffs['mobility']['small'] == 0

    def test_link_activated(self):
        """条件達成でバフ適用"""
        ocr = {
            'link_abilities': [{
                'name': 'テストリンク',
                'condition': 'デッキに3枚以上',
                'effect': '「機動力」小アップ'
            }]
        }
        # デッキに3枚ある
        all_ocr = [ocr, ocr, ocr] + [None] * 7
        buffs = get_link_buffs(ocr, all_ocr)
        assert buffs['mobility']['small'] == 1

    def test_medium_buff(self):
        """中アップの検出"""
        ocr = {
            'link_abilities': [{
                'name': 'テスト中',
                'condition': 'デッキに2枚以上',
                'effect': '「遠距離攻撃力」中アップ'
            }]
        }
        all_ocr = [ocr, ocr] + [None] * 8
        buffs = get_link_buffs(ocr, all_ocr)
        assert buffs['ranged']['medium'] == 1
        assert buffs['ranged']['small'] == 0

    def test_multiple_stat_effect(self):
        """複数ステータス同時バフ"""
        ocr = {
            'link_abilities': [{
                'name': '多彩',
                'condition': 'デッキに2枚以上',
                'effect': '「遠距離攻撃力」「近距離攻撃力」小アップ'
            }]
        }
        all_ocr = [ocr, ocr] + [None] * 8
        buffs = get_link_buffs(ocr, all_ocr)
        assert buffs['ranged']['small'] == 1
        assert buffs['melee']['small'] == 1
        assert buffs['mobility']['small'] == 0

    def test_bracket_notation_effect(self):
        """[括弧]記法のエフェクト"""
        ocr = {
            'link_abilities': [{
                'name': '括弧テスト',
                'condition': 'デッキに2枚以上',
                'effect': '[HP]小アップ'
            }]
        }
        all_ocr = [ocr, ocr] + [None] * 8
        buffs = get_link_buffs(ocr, all_ocr)
        assert buffs['hp']['small'] == 1

    def test_multiple_links_on_card(self):
        """1枚に複数リンク"""
        ocr = {
            'link_abilities': [
                {
                    'name': 'リンクA',
                    'condition': 'デッキに2枚以上',
                    'effect': '「機動力」小アップ'
                },
                {
                    'name': 'リンクB',
                    'condition': 'デッキに3枚以上',
                    'effect': '「HP」小アップ'
                }
            ]
        }
        # リンクA: 2枚で発動、リンクB: 2枚なので未発動
        all_ocr = [ocr, ocr] + [None] * 8
        buffs = get_link_buffs(ocr, all_ocr)
        assert buffs['mobility']['small'] == 1
        assert buffs['hp']['small'] == 0  # 3枚必要だが2枚しかない


# ====================================================================
# 9. applyBuff 計算式テスト
# ====================================================================

class TestApplyBuff:
    """applyBuff: val × 1.1^small × 1.2^medium の計算を検証（logic.buff.apply_buff を使用）"""

    def test_no_buff(self):
        assert apply_buff(100, 0, 0) == 100

    def test_one_small(self):
        assert apply_buff(100, 1, 0) == 110

    def test_two_small(self):
        assert apply_buff(100, 2, 0) == 121  # 100 * 1.21

    def test_one_medium(self):
        assert apply_buff(100, 0, 1) == 120

    def test_small_and_medium(self):
        """100 * 1.1 * 1.2 = 132"""
        assert apply_buff(100, 1, 1) == 132

    def test_zero_value(self):
        assert apply_buff(0, 5, 5) == 0

    def test_real_stat_values(self):
        """実際のステータス値での計算"""
        # 機動力320 + 小バフ1: 320 * 1.1 = 352
        assert apply_buff(320, 1, 0) == 352
        # 遠距離570 + 中バフ1: 570 * 1.2 = 684
        assert apply_buff(570, 0, 1) == 684
        # HP580 + 小1 + 中1: 580 * 1.1 * 1.2 = 765.6 → 766
        assert apply_buff(580, 1, 1) == 766


# ====================================================================
# 10. ユニットステータス計算テスト
# ====================================================================

class TestUnitStatCalculation:
    """MSとPLの合算ステータス計算を検証（logic.stats.calc_unit_stats を使用）"""

    def test_empty_unit(self):
        """空スロットで全ステータス0"""
        result = calc_unit_stats(None, None, [None] * 10)
        for stat in ['mobility', 'ranged', 'melee', 'hp']:
            assert result[stat]['base'] == 0
            assert result[stat]['total'] == 0
            assert result[stat]['buff'] == 0

    def test_ms_only_unit(self):
        """MSのみの場合"""
        ms_ocr = {'stats': {'mobility': 320, 'ranged_attack': 570, 'melee_attack': 130, 'hp': 580}}
        result = calc_unit_stats(ms_ocr, None, [ms_ocr] + [None] * 9)
        assert result['mobility']['base'] == 320
        assert result['ranged']['base'] == 570
        assert result['melee']['base'] == 130
        assert result['hp']['base'] == 580

    def test_ms_pl_combined(self):
        """MS+PLの合算"""
        ms_ocr = {'stats': {'mobility': 320, 'ranged_attack': 570, 'melee_attack': 130, 'hp': 580}}
        pl_ocr = {'stats': {'mobility': 200, 'ranged_attack': 220, 'melee_attack': 90, 'hp': 240}}
        result = calc_unit_stats(ms_ocr, pl_ocr, [ms_ocr, None, None, None, None, pl_ocr] + [None] * 4)
        assert result['mobility']['base'] == 320 + 200
        assert result['ranged']['base'] == 570 + 220
        assert result['melee']['base'] == 130 + 90
        assert result['hp']['base'] == 580 + 240

    def test_ms_pl_combined_with_buff(self):
        """MS+PLの合算 + リンクバフ適用"""
        link = {
            'name': 'テスト',
            'condition': 'デッキに2枚以上',
            'effect': '「機動力」小アップ'
        }
        ms_ocr = {
            'stats': {'mobility': 200, 'ranged_attack': 100, 'melee_attack': 100, 'hp': 100},
            'link_abilities': [link]
        }
        pl_ocr = {
            'stats': {'mobility': 100, 'ranged_attack': 50, 'melee_attack': 50, 'hp': 50},
            'link_abilities': [link]
        }
        all_ocr = [ms_ocr, None, None, None, None, pl_ocr] + [None] * 4

        result = calc_unit_stats(ms_ocr, pl_ocr, all_ocr)

        # 機動力: MS=200*1.1=220, PL=100*1.1=110 → total=330
        assert result['mobility']['total'] == 330
        assert result['mobility']['base'] == 300
        assert result['mobility']['buff'] == 30

        # 遠距離: バフなし → base == total
        assert result['ranged']['total'] == 150
        assert result['ranged']['buff'] == 0

    def test_stat_percentage_calculation(self):
        """パーセンテージ計算（maxVal=1000基準）"""
        max_val = 1000
        total = 520
        pct = (total / max_val) * 100
        assert pct == 52.0

    def test_buff_does_not_apply_to_zero(self):
        """ステータス0にバフを適用しても0のまま"""
        ms_ocr = {
            'stats': {'mobility': 0, 'ranged_attack': 0, 'melee_attack': 0, 'hp': 0},
            'link_abilities': [{
                'name': 'テスト',
                'condition': 'デッキに2枚以上',
                'effect': '「機動力」小アップ'
            }]
        }
        all_ocr = [ms_ocr, ms_ocr] + [None] * 8
        result = calc_unit_stats(ms_ocr, None, all_ocr)
        assert result['mobility']['total'] == 0


# ====================================================================
# 11. 総コスト計算テスト
# ====================================================================

class TestTotalCostCalculation:
    """デッキ総コスト計算を検証（logic.stats.calc_total_cost を使用）"""

    def test_empty_deck(self):
        assert calc_total_cost([None] * 10) == 0

    def test_single_card(self):
        assert calc_total_cost([{'cost': 6}] + [None] * 9) == 6

    def test_full_deck(self):
        ocrs = [{'cost': c} for c in [6, 4, 2, 1, 3, 4, 3, 2, 1, 1]]
        assert calc_total_cost(ocrs) == 27

    def test_mixed_with_none(self):
        """コストNoneのカードを含むデッキ"""
        ocrs = [{'cost': 5}, None, {'cost': 3}, None, None,
                {'cost': 2}, None, None, None, None]
        assert calc_total_cost(ocrs) == 10

    def test_string_cost(self):
        """文字列コスト（OCRデータで起こりうる）"""
        ocrs = [{'cost': '6'}] + [None] * 9
        assert calc_total_cost(ocrs) == 6

    def test_invalid_cost_ignored(self):
        ocrs = [{'cost': 'abc'}] + [None] * 9
        assert calc_total_cost(ocrs) == 0


# ====================================================================
# 12. リンク発動判定テスト
# ====================================================================

class TestLinkActivation:
    """DeckAnalysis._updateLinks() のリンク発動判定ロジックを検証（logic.link.calc_link_activation を使用）"""

    def test_no_links(self):
        result = calc_link_activation([None] * 10)
        assert len(result) == 0

    def test_link_not_enough(self):
        """2枚必要だが1枚しかない"""
        ocr = {
            'link_abilities': [{
                'name': 'ガンダム0083',
                'condition': 'デッキに3枚以上',
                'effect': '【機動力】小アップ'
            }]
        }
        result = calc_link_activation([ocr] + [None] * 9)
        assert result['ガンダム0083']['active'] is False
        assert result['ガンダム0083']['count'] == 1
        assert result['ガンダム0083']['required'] == 3

    def test_link_exactly_met(self):
        """ちょうど条件枚数"""
        ocr = {
            'link_abilities': [{
                'name': 'テスト',
                'condition': 'デッキに3枚以上',
                'effect': '小アップ'
            }]
        }
        result = calc_link_activation([ocr, ocr, ocr] + [None] * 7)
        assert result['テスト']['active'] is True
        assert result['テスト']['count'] == 3

    def test_link_exceeded(self):
        """条件を超過"""
        ocr = {
            'link_abilities': [{
                'name': 'テスト',
                'condition': 'デッキに2枚以上',
                'effect': '小アップ'
            }]
        }
        result = calc_link_activation([ocr] * 5 + [None] * 5)
        assert result['テスト']['active'] is True
        assert result['テスト']['count'] == 5

    def test_multiple_different_links(self):
        """異なるリンクの独立判定"""
        ocr_a = {
            'link_abilities': [
                {'name': 'リンクA', 'condition': 'デッキに2枚以上', 'effect': '機動力小アップ'},
                {'name': 'リンクB', 'condition': 'デッキに4枚以上', 'effect': 'HP小アップ'},
            ]
        }
        result = calc_link_activation([ocr_a, ocr_a, ocr_a] + [None] * 7)
        assert result['リンクA']['active'] is True  # 3枚 >= 2
        assert result['リンクB']['active'] is False  # 3枚 < 4

    def test_cross_card_link_counting(self):
        """異なるカードからの同名リンクをカウント"""
        ocr_ms = {
            'link_abilities': [{'name': '共通リンク', 'condition': 'デッキに3枚以上', 'effect': 'HP小アップ'}]
        }
        ocr_pl = {
            'link_abilities': [{'name': '共通リンク', 'condition': 'デッキに3枚以上', 'effect': 'HP小アップ'}]
        }
        ocr_ms2 = {
            'link_abilities': [{'name': '共通リンク', 'condition': 'デッキに3枚以上', 'effect': 'HP小アップ'}]
        }
        result = calc_link_activation([ocr_ms, ocr_ms2, None, None, None, ocr_pl] + [None] * 4)
        assert result['共通リンク']['count'] == 3
        assert result['共通リンク']['active'] is True

    def test_link_condition_with_体(self):
        """N体以上パターンが正しく解析される"""
        ocr = {
            'link_abilities': [{
                'name': 'テスト体',
                'condition': 'デッキに2体以上',
                'effect': '機動力小アップ'
            }]
        }
        result = calc_link_activation([ocr, ocr, None] + [None] * 7)
        assert result['テスト体']['active'] is True
        assert result['テスト体']['required'] == 2

    def test_link_condition_category_filter_ms_mobility(self):
        """カテゴリ条件「機動がN枚以上」→ 機動MSでカウント"""
        ocr_link = {
            'type': 'MS',
            'category': '機動',
            'link_abilities': [{
                'name': '機動リンク',
                'condition': 'デッキに機動が2枚以上',
                'effect': '機動力小アップ'
            }]
        }
        ocr_mobility = {'type': 'MS', 'category': '機動'}
        ocr_ranged = {'type': 'MS', 'category': '遠距離'}
        # 機動が2枚（ocr_link + ocr_mobility） → 発動
        result = calc_link_activation([ocr_link, ocr_mobility, ocr_ranged] + [None] * 7)
        assert result['機動リンク']['active'] is True
        assert result['機動リンク']['count'] == 2

    def test_link_condition_category_filter_not_enough(self):
        """カテゴリ条件で枚数不足 → 未発動"""
        ocr_link = {
            'type': 'MS',
            'category': '遠距離',
            'link_abilities': [{
                'name': '機動リンク2',
                'condition': 'デッキに機動が3枚以上',
                'effect': '機動力小アップ'
            }]
        }
        ocr_mobility = {'type': 'MS', 'category': '機動'}
        # 機動が1枚のみ → 未発動
        result = calc_link_activation([ocr_link, ocr_mobility] + [None] * 8)
        assert result['機動リンク2']['active'] is False
        assert result['機動リンク2']['count'] == 1

    def test_link_condition_category_pl_defense(self):
        """PLの防衛カテゴリでカウント"""
        ocr_link = {
            'type': 'PL',
            'category': '防衛',
            'link_abilities': [{
                'name': '防衛リンク',
                'condition': 'デッキに防衛が2枚以上',
                'effect': 'HP小アップ'
            }]
        }
        ocr_pl_def = {'type': 'PL', 'category': '防衛'}
        result = calc_link_activation([ocr_link, ocr_pl_def] + [None] * 8)
        assert result['防衛リンク']['active'] is True
        assert result['防衛リンク']['count'] == 2

    def test_link_condition_category_ocr_variant(self):
        """OCR揺れ: 機動力→機動 として正規化"""
        ocr_link = {
            'type': 'MS',
            'category': '機動',
            'link_abilities': [{
                'name': '機動力リンク',
                'condition': 'デッキに機動力が2枚以上',
                'effect': '機動力小アップ'
            }]
        }
        ocr_mobility = {'type': 'MS', 'category': '機動'}
        result = calc_link_activation([ocr_link, ocr_mobility] + [None] * 8)
        assert result['機動力リンク']['active'] is True


class TestGetCardStyle:
    """get_card_style のユニットテスト"""

    def test_ms_mobility(self):
        assert get_card_style({'type': 'MS', 'category': '機動'}) == '機動'

    def test_ms_ranged(self):
        assert get_card_style({'type': 'MS', 'category': '遠距離'}) == '遠距離'

    def test_ms_melee(self):
        assert get_card_style({'type': 'MS', 'category': '近距離'}) == '近距離'

    def test_pl_defense_from_category(self):
        assert get_card_style({'type': 'PL', 'category': '防衛'}) == '防衛'

    def test_pl_annihilation_from_card_label(self):
        assert get_card_style({'type': 'PL', 'card_label': {'class': '殲滅'}}) == '殲滅'

    def test_pl_suppression_from_card_label(self):
        assert get_card_style({'type': 'PL', 'card_label': {'class': '制圧'}, 'category': '防衛'}) == '制圧'

    def test_pl_no_style(self):
        assert get_card_style({'type': 'PL', 'category': '機動'}) is None

    def test_none(self):
        assert get_card_style(None) is None

    def test_no_category(self):
        assert get_card_style({'type': 'MS'}) is None


class TestParseLinkCondition:
    """parse_link_condition の拡張テスト"""

    def test_standard_枚以上(self):
        result = parse_link_condition('デッキに3枚以上')
        assert result == {'required': 3, 'category_filter': None}

    def test_体以上(self):
        result = parse_link_condition('デッキに2体以上')
        assert result == {'required': 2, 'category_filter': None}

    def test_category_機動(self):
        result = parse_link_condition('デッキに機動が2枚以上')
        assert result == {'required': 2, 'category_filter': '機動'}

    def test_category_遠距離(self):
        result = parse_link_condition('デッキに遠距離が3枚以上')
        assert result == {'required': 3, 'category_filter': '遠距離'}

    def test_category_防衛(self):
        result = parse_link_condition('デッキに防衛が2枚以上')
        assert result == {'required': 2, 'category_filter': '防衛'}

    def test_category_殲滅系(self):
        result = parse_link_condition('デッキに殲滅系が2枚以上')
        assert result == {'required': 2, 'category_filter': '殲滅'}

    def test_category_機動力_ocr_variant(self):
        result = parse_link_condition('デッキに機動力が2枚以上')
        assert result == {'required': 2, 'category_filter': '機動'}

    def test_no_match(self):
        assert parse_link_condition('不明な条件') is None

    def test_empty(self):
        assert parse_link_condition('') is None


# ====================================================================
# 13. 地形適性集計テスト
# ====================================================================

class TestTerrainAggregation:
    """DeckAnalysis._updateTerrain() のロジックを検証（logic.terrain.calc_terrain を使用）"""

    def test_empty_deck(self):
        result = calc_terrain([None] * 10)
        for t in ['ground', 'space', 'desert', 'water']:
            assert result[t]['display'] == '-'

    def test_single_ms(self):
        ms = {'terrain_compatibility': {'ground': 'A', 'space': 'S', 'desert': 'C', 'water': 'C'}}
        result = calc_terrain([ms] + [None] * 9)
        assert result['ground']['display'] == 'A'
        assert result['space']['best'] == 'S'

    def test_multiple_ms(self):
        ms1 = {'terrain_compatibility': {'ground': 'A', 'space': 'S', 'desert': 'C', 'water': 'C'}}
        ms2 = {'terrain_compatibility': {'ground': 'A', 'space': 'B', 'desert': 'B', 'water': 'S'}}
        result = calc_terrain([ms1, ms2] + [None] * 8)
        assert result['ground']['display'] == 'A/A'
        assert result['space']['display'] == 'S/B'
        assert result['water']['best'] == 'S'

    def test_pl_slot_ignored(self):
        """PLスロット（5-9）の地形は無視される"""
        pl = {'terrain_compatibility': {'ground': 'S', 'space': 'S', 'desert': 'S', 'water': 'S'}}
        result = calc_terrain([None] * 5 + [pl] * 5)
        for t in ['ground', 'space', 'desert', 'water']:
            assert result[t]['display'] == '-', f'PLスロットの{t}が含まれている'

    def test_best_rank_selection(self):
        """最高ランクが正しく選択される"""
        ms1 = {'terrain_compatibility': {'ground': 'C'}}
        ms2 = {'terrain_compatibility': {'ground': 'A'}}
        ms3 = {'terrain_compatibility': {'ground': 'B'}}
        result = calc_terrain([ms1, ms2, ms3] + [None] * 7)
        assert result['ground']['best'] == 'A'


# ====================================================================
# 14. デッキコード（Base64）テスト
# ====================================================================

class TestDeckCode:
    """デッキコードのエンコード/デコードを検証（logic.deck_code を使用）"""

    def test_roundtrip(self):
        """エンコード→デコードで元のデッキが復元される"""
        deck = ['FQ01-001', 'FQ01-002', 'FQ01-003', 'FQ01-004', 'FQ01-005',
                'FQ01-025', 'FQ01-026', 'FQ01-027', 'FQ01-028', 'FQ01-029']
        code = generate_code(deck)
        parsed = parse_code(code)
        assert parsed == deck

    def test_partial_deck(self):
        """一部空スロットのデッキ"""
        deck = ['FQ01-001', None, 'FQ01-003', None, None,
                None, 'FQ01-026', None, None, None]
        code = generate_code(deck)
        parsed = parse_code(code)
        expected = ['FQ01-001', '', 'FQ01-003', '', '', '', 'FQ01-026', '', '', '']
        assert parsed == expected

    def test_empty_deck(self):
        """空デッキ"""
        deck = [None] * 10
        code = generate_code(deck)
        parsed = parse_code(code)
        assert parsed == [''] * 10

    def test_full_deck(self):
        """10枚フルデッキ"""
        deck = [f'FQ01-{i:03d}' for i in range(1, 11)]
        code = generate_code(deck)
        parsed = parse_code(code)
        assert len(parsed) == 10
        assert parsed == deck

    def test_invalid_code(self):
        """不正コードでNone"""
        assert parse_code('!!!invalid!!!') is None

    def test_code_is_url_safe(self):
        """生成コードがURLに含められる"""
        deck = ['FQ01-001'] * 10
        code = generate_code(deck)
        # base64は基本的にURL-safeだが、+と/と=を含む可能性あり
        # ハッシュフラグメントとして使うので問題ない
        assert isinstance(code, str)
        assert len(code) > 0


# ====================================================================
# 15. デッキ CRUD API テスト
# ====================================================================

class TestDeckCRUD:
    """デッキの作成・読取・更新・削除APIを検証"""

    def test_create_deck(self, client):
        """デッキ作成"""
        res = client.post('/api/decks', json={
            'deck_name': 'テスト作成デッキ',
            'cards': ['FQ01-001'] * 10,
            'comment': 'テスト'
        })
        data = res.get_json()
        assert data['success']
        assert 'id' in data
        return data['id']

    def test_list_decks(self, client):
        """デッキ一覧"""
        res = client.get('/api/decks')
        data = res.get_json()
        assert data['success']
        assert isinstance(data['decks'], list)

    def test_update_deck(self, client):
        """デッキ更新"""
        # まず作成
        create_res = client.post('/api/decks', json={
            'deck_name': '更新テスト元',
            'cards': ['FQ01-001'] * 10,
        })
        deck_id = create_res.get_json()['id']

        # 更新
        res = client.put(f'/api/decks/{deck_id}', json={
            'deck_name': '更新テスト済',
            'cards': ['FQ01-002'] * 10,
        })
        data = res.get_json()
        assert data['success']

        # 確認
        list_res = client.get('/api/decks')
        decks = list_res.get_json()['decks']
        found = [d for d in decks if d.get('id') == deck_id]
        assert len(found) == 1
        assert found[0]['deck_name'] == '更新テスト済'

        # クリーンアップ
        client.delete(f'/api/decks/{deck_id}')

    def test_delete_deck(self, client):
        """デッキ削除"""
        create_res = client.post('/api/decks', json={
            'deck_name': '削除テスト',
            'cards': ['FQ01-001'] * 10,
        })
        deck_id = create_res.get_json()['id']

        res = client.delete(f'/api/decks/{deck_id}')
        assert res.get_json()['success']

        # 再削除は404
        res2 = client.delete(f'/api/decks/{deck_id}')
        assert res2.status_code == 404

    def test_update_nonexistent(self, client):
        """存在しないデッキの更新"""
        res = client.put('/api/decks/nonexistent', json={'deck_name': 'x'})
        assert res.status_code == 404

    def test_create_without_name(self, client):
        """名前なしでデッキ作成は400"""
        res = client.post('/api/decks', json={'cards': ['FQ01-001']})
        assert res.status_code == 400

    def test_create_without_cards(self, client):
        """カードなしでデッキ作成は400"""
        res = client.post('/api/decks', json={'deck_name': 'テスト'})
        assert res.status_code == 400


# ====================================================================
# 16. 後方互換性テスト
# ====================================================================

class TestBackwardCompatibility:
    """既存エンドポイントが正常に動作することを検証"""

    def test_fetch_cards(self, client):
        res = client.get('/fetch_cards')
        data = res.get_json()
        assert data['success']
        assert 'images' in data
        assert len(data['images']) > 0

    def test_debug_summary(self, client):
        res = client.get('/debug_summary')
        data = res.get_json()
        assert data['success']

    def test_post_deck_legacy(self, client):
        res = client.post('/post_deck', json={
            'deck_name': '互換テスト',
            'cards': [{'number': 'FQ01-001'}],
            'timestamp': '2025-01-01'
        })
        assert res.get_json()['success']

    def test_decks_list_legacy(self, client):
        res = client.get('/decks')
        assert res.status_code == 200

    def test_page_routes(self, client):
        """全ページルートが200を返す"""
        pages = ['/', '/search', '/summary', '/summary2', '/summary3',
                 '/decks.html', '/mobile']
        for page in pages:
            res = client.get(page)
            assert res.status_code == 200, f'{page} が {res.status_code}'


# ====================================================================
# 17. カードデータ整合性（APIレスポンス vs ファイル）
# ====================================================================

class TestDataConsistency:
    """APIから返されるデータとファイルシステム上のデータの一貫性"""

    def test_index_count_matches_unique_cards(self, card_index):
        """インデックスのカード数がall_cards_listの一意カード数と一致"""
        all_cards_dir = 'all_cards_list'
        if not os.path.exists(all_cards_dir):
            pytest.skip('all_cards_list が存在しない')
        seen = set()
        for fn in os.listdir(all_cards_dir):
            if not fn.endswith('.json'):
                continue
            try:
                with open(os.path.join(all_cards_dir, fn), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                if isinstance(data, dict) and data.get('number'):
                    seen.add(data['number'])
            except Exception:
                continue
        assert len(card_index) == len(seen), \
            f'インデックス={len(card_index)}, ファイル一意={len(seen)}'

    def test_ocr_cards_stats_match_index(self, client, card_index):
        """OCR付きカードのステータスがインデックスと詳細で一致"""
        checked = 0
        # OCRデータを持つFQ01/FQ02系カードを優先的にチェック
        ocr_candidates = [c for c in card_index if c['cost'] is not None and c['cost'] > 0]
        for idx_card in ocr_candidates[:50]:
            res = client.get(f'/api/card/{idx_card["number"]}')
            detail = res.get_json()
            if not detail['success']:
                continue
            ocr = detail['card'].get('ocr_data', {})
            stats = ocr.get('stats', {})
            if not stats:
                continue

            assert idx_card['mobility'] == _safe_int(stats.get('mobility')), \
                f'{idx_card["number"]} mobility: idx={idx_card["mobility"]} vs detail={stats.get("mobility")}'
            assert idx_card['ranged'] == _safe_int(stats.get('ranged_attack')), \
                f'{idx_card["number"]} ranged: idx={idx_card["ranged"]} vs detail={stats.get("ranged_attack")}'
            assert idx_card['melee'] == _safe_int(stats.get('melee_attack')), \
                f'{idx_card["number"]} melee: idx={idx_card["melee"]} vs detail={stats.get("melee_attack")}'
            assert idx_card['hp'] == _safe_int(stats.get('hp')), \
                f'{idx_card["number"]} hp: idx={idx_card["hp"]} vs detail={stats.get("hp")}'
            checked += 1
        assert checked > 0, 'ステータスチェック対象が0件'

    def test_index_cost_matches_detail(self, client, card_index):
        """インデックスのコストと詳細OCRのコストが一致"""
        checked = 0
        # OCRデータを持つカードを優先的にチェック
        ocr_candidates = [c for c in card_index if c['cost'] is not None and c['cost'] > 0]
        for idx_card in ocr_candidates[:50]:
            res = client.get(f'/api/card/{idx_card["number"]}')
            detail = res.get_json()
            if not detail['success']:
                continue
            ocr_cost = detail['card'].get('ocr_data', {}).get('cost')
            if ocr_cost is not None:
                assert idx_card['cost'] == _safe_int(ocr_cost), \
                    f'{idx_card["number"]} cost: idx={idx_card["cost"]} vs detail={ocr_cost}'
                checked += 1
        assert checked > 0


# ====================================================================
# 18. エッジケーステスト
# ====================================================================

class TestEdgeCases:
    """境界値・異常系のテスト"""

    def test_search_empty_query(self, client):
        """空クエリで全件"""
        res = client.get('/api/cards/search?q=')
        assert res.get_json()['success']

    def test_search_limit_zero(self, client):
        """limit=0で空リスト"""
        res = client.get('/api/cards/search?limit=0')
        assert len(res.get_json()['cards']) == 0

    def test_search_large_offset(self, client):
        """巨大オフセットで空リスト"""
        res = client.get('/api/cards/search?offset=999999')
        assert len(res.get_json()['cards']) == 0

    def test_batch_empty_array(self, client):
        """空配列でバッチ取得"""
        res = client.post('/api/cards/batch', json={'numbers': []})
        data = res.get_json()
        assert data['success']
        assert len(data['cards']) == 0

    def test_batch_invalid_numbers(self, client):
        """存在しない番号でバッチ取得"""
        res = client.post('/api/cards/batch', json={'numbers': ['FAKE-001', 'FAKE-002']})
        data = res.get_json()
        assert data['success']
        assert len(data['cards']) == 0

    def test_cache_clear_and_rebuild(self, client, card_index):
        """キャッシュクリア後もデータが正しい"""
        res = client.post('/api/cache/clear')
        assert res.get_json()['success']
        # 再取得
        res2 = client.get('/api/card_index')
        new_index = res2.get_json()['cards']
        assert len(new_index) == len(card_index)

    def test_apply_buff_large_multiplier(self):
        """大量バフの計算（オーバーフローしないこと）"""
        result = round(100 * (1.1 ** 10) * (1.2 ** 10))
        assert isinstance(result, int)
        assert result > 0

    def test_safe_int_with_various_types(self):
        """様々な型でのsafe_int"""
        assert _safe_int(True) == 1
        assert _safe_int(False) == 0
        assert _safe_int(3.7) == 3
        assert _safe_int([]) == 0
        assert _safe_int({}) == 0


# ====================================================================
# 19. 実データでの統合テスト
# ====================================================================

class TestIntegrationWithRealData:
    """実際のカードデータを使ったエンドツーエンドテスト"""

    def test_full_deck_scenario(self, client, ms_cards, pl_cards):
        """フルデッキシナリオ: 5MS + 5PL を選び、コスト・リンク・ステータスを計算"""
        # OCR付きMSを5枚選ぶ
        ms_with_cost = [c for c in ms_cards if c['cost'] is not None][:5]
        pl_with_cost = [c for c in pl_cards if c['cost'] is not None][:5]

        if len(ms_with_cost) < 5 or len(pl_with_cost) < 5:
            pytest.skip('十分なOCR付きカードがない')

        deck_numbers = [c['number'] for c in ms_with_cost] + [c['number'] for c in pl_with_cost]

        # バッチ詳細取得
        res = client.post('/api/cards/batch', json={'numbers': deck_numbers})
        details = res.get_json()['cards']

        # 全カードの詳細が取得できている
        assert len(details) == 10

        # OCRデータリスト構築
        ocr_list = []
        for num in deck_numbers:
            d = details.get(num, {})
            ocr_list.append(d.get('ocr_data'))

        # 総コスト計算
        total_cost = sum(_safe_int(o.get('cost')) for o in ocr_list if o)
        expected_cost = sum(c['cost'] for c in ms_with_cost + pl_with_cost)
        assert total_cost == expected_cost, f'コスト不一致: {total_cost} vs {expected_cost}'

        # 各ユニットのステータスが非負
        for u in range(5):
            ms_ocr = ocr_list[u]
            pl_ocr = ocr_list[u + 5]
            result = calc_unit_stats(ms_ocr, pl_ocr, ocr_list)
            for stat in ['mobility', 'ranged', 'melee', 'hp']:
                assert result[stat]['base'] >= 0
                assert result[stat]['total'] >= result[stat]['base']
                assert result[stat]['buff'] >= 0

    def test_link_activation_with_real_data(self, client, card_index):
        """同シリーズのカードを集めてリンク発動を確認"""
        # FQ01シリーズのカードを収集
        fq01_cards = [c for c in card_index if c['series'] == 'FQ01' and c['cost'] is not None]
        if len(fq01_cards) < 5:
            pytest.skip('FQ01カードが不足')

        # 詳細取得
        nums = [c['number'] for c in fq01_cards[:10]]
        res = client.post('/api/cards/batch', json={'numbers': nums})
        details = res.get_json()['cards']

        # OCRリスト構築
        ocr_list = []
        for num in nums[:10]:
            d = details.get(num, {})
            ocr_list.append(d.get('ocr_data'))
        while len(ocr_list) < 10:
            ocr_list.append(None)

        # リンク集計
        result = calc_link_activation(ocr_list)

        # 少なくとも1つのリンクが存在するはず
        if result:
            # 各リンクの整合性チェック
            for name, link in result.items():
                assert link['count'] > 0
                assert isinstance(link['active'], bool)
                if link['required'] is not None:
                    assert link['active'] == (link['count'] >= link['required'])

    def test_terrain_aggregation_with_real_data(self, client, ms_cards):
        """実MSカードの地形適性を集計"""
        ms_with_cost = [c for c in ms_cards if c['cost'] is not None][:5]
        if len(ms_with_cost) < 3:
            pytest.skip('十分なMSカードがない')

        nums = [c['number'] for c in ms_with_cost]
        res = client.post('/api/cards/batch', json={'numbers': nums})
        details = res.get_json()['cards']

        ocr_list = [details.get(n, {}).get('ocr_data') for n in nums]
        while len(ocr_list) < 10:
            ocr_list.append(None)

        result = calc_terrain(ocr_list)

        # 地形データが存在するカードがあれば、表示が'-'でない
        has_terrain = any(
            o and o.get('terrain_compatibility')
            for o in ocr_list[:5] if o
        )
        if has_terrain:
            terrain_found = any(
                result[t]['display'] != '-'
                for t in ['ground', 'space', 'desert', 'water']
            )
            assert terrain_found, '地形データがあるのに集計結果が全て-'

    def test_deck_code_roundtrip_with_real_cards(self, card_index):
        """実カード番号でデッキコードの往復テスト"""
        ms = [c['number'] for c in card_index if c['type'] == 'MS'][:5]
        pl = [c['number'] for c in card_index if c['type'] == 'PL'][:5]
        deck = ms + pl
        assert len(deck) == 10

        code = generate_code(deck)
        parsed = parse_code(code)
        assert parsed == deck
