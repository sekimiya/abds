"""
GAB デッキシミュレーター 型定義

TypedDict による構造化データ型を定義する。
"""

from typing import TypedDict, Optional, List, Dict


class LinkCondition(TypedDict):
    required: int                      # 必要枚数
    category_filter: Optional[str]     # None = リンク名カウント, str = カテゴリカウント


class StatValues(TypedDict):
    mobility: int
    ranged: int
    melee: int
    hp: int


class BuffCounts(TypedDict):
    small: int
    medium: int


class LinkBuffResult(TypedDict):
    mobility: BuffCounts
    ranged: BuffCounts
    melee: BuffCounts
    hp: BuffCounts


class UnitStatDetail(TypedDict):
    base: int
    total: int
    buff: int


class UnitStatResult(TypedDict):
    mobility: UnitStatDetail
    ranged: UnitStatDetail
    melee: UnitStatDetail
    hp: UnitStatDetail


class LinkActivationInfo(TypedDict):
    count: int
    required: Optional[int]
    active: bool
    effect: str


class TerrainInfo(TypedDict):
    display: str
    best: Optional[str]


class TerrainResult(TypedDict):
    ground: TerrainInfo
    space: TerrainInfo
    desert: TerrainInfo
    water: TerrainInfo


class WeaponInfo(TypedDict, total=False):
    name: str
    range: str
    power: str
    type: str


class MSAbilityInfo(TypedDict, total=False):
    name: str
    activation_type: str
    category: str
    description: str


class PLSkillInfo(TypedDict, total=False):
    trigger: str
    trigger_type: str
    effect: str
    effect_type: str
    description: str
    raw: str


class SPAttackInfo(TypedDict, total=False):
    name: str
    power: Dict
    description: str
    cost: int


class LinkAbility(TypedDict, total=False):
    name: str
    condition: str
    effect: str
    count: int
    required: int
    active: bool


class DeckValidationError(TypedDict):
    code: str
    message: str
    slot: Optional[int]


class DeckValidationResult(TypedDict):
    valid: bool
    errors: List[DeckValidationError]
