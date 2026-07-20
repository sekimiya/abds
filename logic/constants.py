"""
GAB デッキシミュレーター 定数定義

ゲームメカニクスに関する定数、Enum、データテーブルを管理する。

数値の出典:
  - バフ倍率: Yahoo知恵袋 検証情報 (小=1.1, 中=1.2~1.4, 大=1.45~1.5)
  - 防衛軽減: 初心者用ガイド (gundamab.swiki.jp) 「あらゆる受けるダメージが0.2倍」
  - 指揮官経験値: 指揮官レベル (gundamab.swiki.jp) 「勝利+20, 引分+15, 敗北+10」
  - 指揮官レベル上限: 指揮官レベル (gundamab.swiki.jp)
  - 指揮官HP: 指揮官レベル (gundamab.swiki.jp) 「5レベルごとに+5」
  - MSアビリティ分類・コスト: MSアビリティ (gundamab.swiki.jp)
  - タイプ相性/地形補正倍率: 公式に未公開。プランの仮値を使用（要検証）
  - ガード軽減: 用語集 (gundamab.swiki.jp) 「基本30%カット、シールド持ち70%カット」
  - クリティカル: 用語集 (gundamab.swiki.jp) 「約1.5倍」
"""

from enum import Enum


# ====================================================================
# カード種別
# ====================================================================

class CardType(str, Enum):
    MS = 'MS'
    PL = 'PL'


# ====================================================================
# 戦闘スタイル
# ====================================================================

class CombatStyle(str, Enum):
    ANNIHILATION = '殲滅'
    SUPPRESSION = '制圧'
    DEFENSE = '防衛'


# ====================================================================
# MSカテゴリ
# ====================================================================

class MSCategory(str, Enum):
    MOBILITY = '機動'
    RANGED = '遠距離'
    MELEE = '近距離'


# ====================================================================
# ステータス名
# ====================================================================

class StatName(str, Enum):
    MOBILITY = 'mobility'
    RANGED = 'ranged'
    MELEE = 'melee'
    HP = 'hp'


# ====================================================================
# バフサイズ
# ====================================================================

class BuffSize(str, Enum):
    SMALL = 'small'
    MEDIUM = 'medium'


BUFF_MULTIPLIER = {
    BuffSize.SMALL: 1.1,
    BuffSize.MEDIUM: 1.2,
}


# ====================================================================
# 地形
# ====================================================================

class TerrainType(str, Enum):
    GROUND = 'ground'
    SPACE = 'space'
    DESERT = 'desert'
    WATER = 'water'


class TerrainRank(str, Enum):
    S = 'S'
    A = 'A'
    B = 'B'
    C = 'C'
    D = 'D'


TERRAIN_RANK_VALUE = {
    TerrainRank.S: 5,
    TerrainRank.A: 4,
    TerrainRank.B: 3,
    TerrainRank.C: 2,
    TerrainRank.D: 1,
}

# 地形適性によるステータス補正倍率
# NOTE: 公式には「全パラメータに微量の補正」とのみ公開。具体的倍率は未公開（要検証）。
TERRAIN_EFFECT_MULTIPLIER = {
    TerrainRank.S: 1.15,
    TerrainRank.A: 1.05,
    TerrainRank.B: 1.0,
    TerrainRank.C: 0.90,
    TerrainRank.D: 0.80,
}


# ====================================================================
# タイプ相性
# ====================================================================

# 攻撃側→防御側 のダメージ倍率
# NOTE: 公式に具体的倍率は未公開。以下はプランの仮値（要検証）。
# 制圧→拠点は1.3倍との情報あり。
TYPE_MATCHUP = {
    (CombatStyle.ANNIHILATION, CombatStyle.ANNIHILATION): 1.0,
    (CombatStyle.ANNIHILATION, CombatStyle.SUPPRESSION): 2.0,
    (CombatStyle.ANNIHILATION, CombatStyle.DEFENSE): 0.7,
    (CombatStyle.SUPPRESSION, CombatStyle.ANNIHILATION): 0.7,
    (CombatStyle.SUPPRESSION, CombatStyle.SUPPRESSION): 1.0,
    (CombatStyle.SUPPRESSION, CombatStyle.DEFENSE): 2.0,
    (CombatStyle.DEFENSE, CombatStyle.ANNIHILATION): 2.0,
    (CombatStyle.DEFENSE, CombatStyle.SUPPRESSION): 0.7,
    (CombatStyle.DEFENSE, CombatStyle.DEFENSE): 1.0,
}

# 制圧タイプの拠点ダメージ倍率
SUPPRESSION_BASE_MULTIPLIER = 1.3

# 拠点守備時ダメージ軽減倍率
# 出典: 初心者用ガイド「あらゆる受けるダメージが0.2倍」
# NOTE: 0.2 = 受けるダメージが0.2倍（80%軽減）。軽減"率"ではなく軽減後の"倍率"。
DEFENSE_BASE_DAMAGE_MULTIPLIER = 0.2


# ====================================================================
# 指揮官
# ====================================================================

# 出典: 指揮官レベル (gundamab.swiki.jp)「勝利時+20、引き分けで+15、敗北時+10」
COMMANDER_EXP = {
    'win': 20,
    'draw': 15,
    'loss': 10,
}

# 出典: 指揮官レベル (gundamab.swiki.jp)
# シーズン略称→レベル上限。S=SEASON, LXS=LINK×STAGE
COMMANDER_LEVEL_CAP = {
    'S01': 40,
    'S02': 40,
    'S03': 45,
    'S04': 50,
    'LXS01': 55,
    'LXS02': 60,
    'LXS03': 65,
    'LXS04': 70,
}

# 出典: 指揮官レベル (gundamab.swiki.jp)
# 「5レベルごとに+5」→拠点/戦艦HPが+5（ユニットHPではない）
COMMANDER_HP_BONUS_INTERVAL = 5   # レベル間隔
COMMANDER_HP_BONUS_PER_STEP = 5   # 1段階あたりHP増加


# ====================================================================
# アビリティ発動タイプ
# ====================================================================

class AbilityActivationType(str, Enum):
    MANUAL = '任意発動'
    ON_DEPLOY = '出撃時発動'


# ====================================================================
# デッキ構成定数
# ====================================================================

DECK_SIZE = 10
MS_SLOT_COUNT = 5
PL_SLOT_COUNT = 5


# ====================================================================
# リンクバフ解析パターン
# ====================================================================

# リンク条件のカテゴリフィルタ正規化マップ
# OCR揺れ（機動力→機動、殲滅系→殲滅、制圧/圧→制圧）を吸収
LINK_CONDITION_CATEGORY_MAP = {
    '機動': '機動',
    '機動力': '機動',
    '遠距離': '遠距離',
    '近距離': '近距離',
    '殲滅': '殲滅',
    '殲滅系': '殲滅',
    '制圧': '制圧',
    '制圧/圧': '制圧',
    '防衛': '防衛',
}


BUFF_PATTERNS = {
    ('mobility', 'small'): r'機動力.*小アップ',
    ('ranged', 'small'): r'遠距離攻撃力.*小アップ',
    ('melee', 'small'): r'近距離攻撃力.*小アップ',
    ('hp', 'small'): r'HP.*小アップ',
    ('mobility', 'medium'): r'機動力.*中アップ',
    ('ranged', 'medium'): r'遠距離攻撃力.*中アップ',
    ('melee', 'medium'): r'近距離攻撃力.*中アップ',
    ('hp', 'medium'): r'HP.*中アップ',
}


# ====================================================================
# OCRキーマッピング
# ====================================================================

OCR_STAT_KEY_MAP = {
    'ranged_attack': 'ranged',
    'melee_attack': 'melee',
    'mobility': 'mobility',
    'hp': 'hp',
}


# ====================================================================
# 戦闘パラメータ（出典: 用語集 gundamab.swiki.jp）
# ====================================================================

GUARD_REDUCTION = 0.30        # ガード軽減: 基本30%カット
SHIELD_GUARD_REDUCTION = 0.70 # シールド持ちガード: 70%カット
CRITICAL_MULTIPLIER = 1.5     # クリティカルダメージ: 約1.5倍
REPAIR_TIME_SECONDS = 30      # ユニット修理時間: 30秒
BATTLE_TIME_LIMIT = 180       # バトル制限時間: 180カウント
DEFENSE_MOVE_COST = 3         # 防衛ユニット拠点移動コスト: 3


# ====================================================================
# MSアビリティ詳細（出典: MSアビリティ gundamab.swiki.jp）
# ====================================================================

# 任意発動型の再発動間隔（秒）
ABILITY_COOLDOWN_DEFAULT = 30
ABILITY_COOLDOWN_LONG = 60     # 奇襲・オールレンジ

# アビリティ名→(射程, コスト) のテーブル
ABILITY_DATA = {
    '連射': {'range': 3, 'cost': 3},
    '連撃': {'range': '1-2', 'cost': 3},
    '精密射撃': {'range': '3-4', 'cost': 3},
    '妨撃': {'range': '1-2', 'cost': 3},
    '縛撃': {'range': '1-2', 'cost': 3},
    '縛射': {'range': '3-4', 'cost': 3},
    '強撃': {'range': 1, 'cost': 3},
    '逆襲': {'range': 1, 'cost': 4},
    '砕撃': {'range': 1, 'cost': 3},
    '撃滅': {'range': 2, 'cost': 4},
    '強襲': {'range': 4, 'cost': 4},
    '断砕': {'range': '1-2', 'cost': 3},
    '貫通': {'range': '3-4', 'cost': 3},
    '掃射[広角]': {'range': 3, 'cost': 3},
    '爆撃': {'range': 3, 'cost': 3},
    '砲撃': {'range': '4-5', 'cost': 4},
    '支援砲撃': {'range': 'MAP', 'cost': 5},
    '奇襲': {'range': 'MAP', 'cost': 6},
    '全弾発射': {'range': '3-4', 'cost': 5},
    'オールレンジ': {'range': 4, 'cost': 3},
    '砕撃[広角]': {'range': 4, 'cost': 4},
    '鼓舞[機動]': {'range': None, 'cost': 4},
    '鼓舞[遠距離]': {'range': None, 'cost': 4},
    '鼓舞[防御]': {'range': None, 'cost': 4},
    '鼓舞[攻撃]': {'range': None, 'cost': 5},
    '強化[近接]': {'range': None, 'cost': 4},
    '強化[遠隔]': {'range': None, 'cost': 4},
    '増援': {'range': None, 'cost': 3},
    '誘導': {'range': None, 'cost': 4},
    '補給': {'range': None, 'cost': 4},
    '集中砲火': {'range': None, 'cost': 4},
}
