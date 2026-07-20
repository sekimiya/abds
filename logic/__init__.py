"""
GAB デッキシミュレーター 計算ロジックパッケージ

全モジュールの公開APIを re-export する。
"""

# constants
from .constants import (
    CardType,
    CombatStyle,
    MSCategory,
    StatName,
    BuffSize,
    BUFF_MULTIPLIER,
    TerrainType,
    TerrainRank,
    TERRAIN_RANK_VALUE,
    TERRAIN_EFFECT_MULTIPLIER,
    TYPE_MATCHUP,
    DEFENSE_BASE_DAMAGE_MULTIPLIER,
    SUPPRESSION_BASE_MULTIPLIER,
    COMMANDER_EXP,
    COMMANDER_LEVEL_CAP,
    COMMANDER_HP_BONUS_INTERVAL,
    COMMANDER_HP_BONUS_PER_STEP,
    AbilityActivationType,
    DECK_SIZE,
    MS_SLOT_COUNT,
    PL_SLOT_COUNT,
    BUFF_PATTERNS,
    OCR_STAT_KEY_MAP,
    GUARD_REDUCTION,
    SHIELD_GUARD_REDUCTION,
    CRITICAL_MULTIPLIER,
    REPAIR_TIME_SECONDS,
    BATTLE_TIME_LIMIT,
    DEFENSE_MOVE_COST,
    ABILITY_COOLDOWN_DEFAULT,
    ABILITY_COOLDOWN_LONG,
    ABILITY_DATA,
    LINK_CONDITION_CATEGORY_MAP,
)

# types
from .types import (
    StatValues,
    BuffCounts,
    LinkBuffResult,
    UnitStatDetail,
    UnitStatResult,
    LinkActivationInfo,
    TerrainInfo,
    TerrainResult,
    WeaponInfo,
    MSAbilityInfo,
    PLSkillInfo,
    SPAttackInfo,
    LinkCondition,
    LinkAbility,
    DeckValidationError,
    DeckValidationResult,
)

# utils
from .utils import (
    safe_int,
    get_nested,
    extract_stats,
    get_link_abilities,
    parse_link_condition,
    get_card_style,
    count_for_condition,
)

# buff
from .buff import (
    get_link_buffs,
    apply_buff,
)

# stats
from .stats import (
    calc_unit_stats,
    calc_all_unit_stats,
    calc_total_cost,
    calc_cost_breakdown,
)

# link
from .link import (
    calc_link_activation,
    get_active_links,
)

# terrain
from .terrain import (
    calc_terrain,
)

# deck_code
from .deck_code import (
    generate_code,
    parse_code,
)

# deck_validation
from .deck_validation import (
    validate_deck,
    check_pilot_duplicates,
)

# matchup
from .matchup import (
    get_type_multiplier,
    calc_defense_base_damage,
    analyze_deck_matchup,
)

# terrain_effect
from .terrain_effect import (
    apply_terrain_effect,
    get_terrain_compatibility_rank,
)

# commander
from .commander import (
    calc_exp_gain,
    get_level_cap,
    calc_hp_bonus,
)

# ability
from .ability import (
    classify_ability,
    get_sp_attack_info,
    calc_deck_sp_costs,
)

# pilot_skill
from .pilot_skill import (
    classify_skill_trigger,
    classify_skill_effect,
    get_skill_info,
)

# card_index_builder
from .card_index_builder import (
    build_card_index,
    classify_sp_effects,
)
