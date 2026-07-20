#!/usr/bin/env python3
"""
Comprehensive data integrity check for ABDS card data.
Checks card_details.json and card_index.json for anomalies.
READ-ONLY: does not modify any files.
"""

import json
import re
from collections import defaultdict

DETAILS_PATH = "/Users/sekimiya/workspace/abds/data/card_details.json"
INDEX_PATH = "/Users/sekimiya/workspace/abds/data/card_index.json"

KNOWN_SP_TYPES = {"ECHOES BEAT", "ECHOES BEAT SP", "SQUAD SP", "UNITED SP", ""}
CONDITION_PATTERN = re.compile(r"^デッキに\d+枚以上$")
STAT_EFFECT_PATTERN = re.compile(r"\[(HP|機動力|射撃攻撃力|格闘攻撃力)\]")

# ─────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────
with open(DETAILS_PATH, encoding="utf-8") as f:
    details: dict = json.load(f)

with open(INDEX_PATH, encoding="utf-8") as f:
    index_list: list = json.load(f)

# Build index dict keyed by card number
index_by_number: dict[str, dict] = {c["number"]: c for c in index_list}

print(f"Loaded {len(details)} cards in card_details.json")
print(f"Loaded {len(index_list)} cards in card_index.json")
print()

# ─────────────────────────────────────────────
# Helper: collect all link ability names per type globally
# ─────────────────────────────────────────────
def collect_link_name_by_type(details: dict):
    """Return {link_name: set_of_card_types} mapping."""
    mapping: dict[str, set] = defaultdict(set)
    for card_num, card in details.items():
        ocr = card.get("ocr_data", {})
        card_type = ocr.get("type", "")
        for la in ocr.get("link_ability", []) or []:
            name = la.get("name", "")
            if name:
                mapping[name].add(card_type)
    return mapping

link_name_to_types = collect_link_name_by_type(details)

# Names that appear ONLY on PL cards or ONLY on MS cards
pl_only_links = {name for name, types in link_name_to_types.items()
                 if types == {"PL"}}
ms_only_links = {name for name, types in link_name_to_types.items()
                 if types == {"MS"}}

# ─────────────────────────────────────────────
# Anomaly collection
# ─────────────────────────────────────────────
anomalies: dict[str, list[str]] = defaultdict(list)

def add(category: str, msg: str):
    anomalies[category].append(msg)

# ═════════════════════════════════════════════
# 1. Link Ability Anomalies
# ═════════════════════════════════════════════
for card_num, card in details.items():
    ocr = card.get("ocr_data", {})
    card_type = ocr.get("type", "")
    card_name = ocr.get("name", card.get("name", ""))

    for i, la in enumerate(ocr.get("link_ability", []) or []):
        la_name = la.get("name", "")
        la_cond = la.get("condition", "")
        la_effect = la.get("effect", "")
        tag = f"{card_num}({card_name}) link[{i}]"

        # Empty fields
        if not la_name:
            add("1_link_empty_name", f"{tag}: name is empty, cond='{la_cond}' effect='{la_effect}'")
        if not la_cond:
            add("1_link_empty_condition", f"{tag}: condition is empty, name='{la_name}'")
        if not la_effect:
            add("1_link_empty_effect", f"{tag}: effect is empty, name='{la_name}'")

        # Name contains stat-effect pattern (likely OCR merge)
        if la_name and STAT_EFFECT_PATTERN.search(la_name):
            add("1_link_name_contains_effect", f"{tag}: name looks like it has effect text: '{la_name}'")

        # Condition doesn't match standard pattern
        if la_cond and not CONDITION_PATTERN.match(la_cond):
            add("1_link_condition_nonstandard", f"{tag}: condition='{la_cond}' (name='{la_name}')")

        # MS card has PL-only link ability
        if card_type == "MS" and la_name and la_name in pl_only_links:
            add("1_link_ms_has_pl_only", f"{tag}: MS card has PL-only link '{la_name}'")

        # PL card has MS-only link ability
        if card_type == "PL" and la_name and la_name in ms_only_links:
            add("1_link_pl_has_ms_only", f"{tag}: PL card has MS-only link '{la_name}'")

# ═════════════════════════════════════════════
# 2. Stats Anomalies
# ═════════════════════════════════════════════
for card_num, card in details.items():
    ocr = card.get("ocr_data", {})
    card_type = ocr.get("type", "")
    card_name = ocr.get("name", card.get("name", ""))
    stats = ocr.get("stats", {}) or {}
    tag = f"{card_num}({card_name})"

    mob = stats.get("mobility", None)
    rng = stats.get("ranged_attack", None)
    mel = stats.get("melee_attack", None)
    hp = stats.get("hp", None)

    stat_vals = [v for v in [mob, rng, mel, hp] if v is not None]

    # All zeros
    if stat_vals and all(v == 0 for v in stat_vals):
        add("2_stats_all_zero", f"{tag}: all stats are 0")

    # Negative stats
    for stat_name, val in [("mobility", mob), ("ranged_attack", rng),
                            ("melee_attack", mel), ("hp", hp)]:
        if val is not None and val < 0:
            add("2_stats_negative", f"{tag}: {stat_name}={val}")

    # Unreasonably high stats
    for stat_name, val in [("mobility", mob), ("ranged_attack", rng),
                            ("melee_attack", mel), ("hp", hp)]:
        if val is not None and val > 1000:
            add("2_stats_too_high", f"{tag}: {stat_name}={val}")

    # MS cards missing terrain data
    if card_type == "MS":
        terrain = ocr.get("terrain_compatibility", {}) or {}
        if terrain:
            all_empty = all(v == "" or v is None for v in terrain.values())
            if all_empty:
                add("2_terrain_all_empty", f"{tag}: all terrain_compatibility fields empty")
        else:
            add("2_terrain_missing", f"{tag}: no terrain_compatibility key at all")

# ═════════════════════════════════════════════
# 3. Name Anomalies
# ═════════════════════════════════════════════
# Cards with empty names
for card_num, card in details.items():
    ocr = card.get("ocr_data", {})
    top_name = card.get("name", "")
    ocr_name = ocr.get("name", "")
    tag = f"{card_num}"

    if not top_name:
        add("3_name_empty_top", f"{tag}: top-level name is empty")
    if not ocr_name:
        add("3_name_empty_ocr", f"{tag}: ocr_data.name is empty (top name='{top_name}')")

    # Name is likely a model number (all ASCII/alphanumeric with hyphens, no Japanese)
    def looks_like_model(s):
        if not s:
            return False
        # model names are like "RX-78-2 GUNDAM", "MSN-04 SAZABI"
        # card names should have Japanese
        has_japanese = bool(re.search(r'[\u3000-\u9fff\uff00-\uffef]', s))
        is_ascii_model = bool(re.match(r'^[A-Z0-9][A-Z0-9\-\s]+$', s.strip()))
        return is_ascii_model and not has_japanese

    if looks_like_model(ocr_name):
        add("3_name_looks_like_model", f"{tag}: ocr name '{ocr_name}' looks like model number, not Japanese display name")

# Duplicate card names within same series (excluding parallel variants)
from collections import Counter

series_name_cards: dict[tuple, list] = defaultdict(list)
for card_num, card in details.items():
    # Exclude parallel variants (_p1, _p2 suffix)
    if re.search(r'_p\d+$', card_num, re.IGNORECASE):
        continue
    ocr = card.get("ocr_data", {})
    card_type = ocr.get("type", "")
    name = ocr.get("name", card.get("name", ""))
    series = card.get("series", "") or ocr.get("series", "")
    if name and series:
        series_name_cards[(series, card_type, name)].append(card_num)

for (series, ctype, name), cards in series_name_cards.items():
    if len(cards) > 1:
        add("3_duplicate_name_in_series",
            f"Series {series} ({ctype}) name '{name}' appears {len(cards)} times: {cards}")

# ═════════════════════════════════════════════
# 4. Special Attack Anomalies (MS only)
# ═════════════════════════════════════════════
for card_num, card in details.items():
    ocr = card.get("ocr_data", {})
    card_type = ocr.get("type", "")
    card_name = ocr.get("name", card.get("name", ""))
    if card_type != "MS":
        continue

    sa = ocr.get("special_attack", None)
    if sa is None:
        continue

    sa_name = sa.get("name", "") or ""
    sa_power = sa.get("power", None)
    sa_desc = sa.get("description", "") or ""
    sp_type = sa.get("sp_type", "") or ""
    tag = f"{card_num}({card_name})"

    # Empty name but has power/description
    if not sa_name and (sa_power or sa_desc):
        add("4_sa_empty_name", f"{tag}: special_attack name empty but power={sa_power}, desc='{sa_desc[:40]}'")

    # power=0 or None when description exists
    if sa_desc and (sa_power is None or sa_power == 0):
        add("4_sa_zero_power", f"{tag}: special_attack power={sa_power} but description exists")

    # Unknown sp_type
    if sp_type not in KNOWN_SP_TYPES:
        add("4_sa_unknown_sp_type", f"{tag}: sp_type='{sp_type}' not in known types")

# ═════════════════════════════════════════════
# 5. Pilot Skill Anomalies (PL only)
# ═════════════════════════════════════════════
for card_num, card in details.items():
    ocr = card.get("ocr_data", {})
    card_type = ocr.get("type", "")
    card_name = ocr.get("name", card.get("name", ""))
    if card_type != "PL":
        continue

    ps = ocr.get("pilot_skill", None)
    tag = f"{card_num}({card_name})"

    if ps is None:
        add("5_ps_missing", f"{tag}: PL card has no pilot_skill")
        continue

    ps_trigger = ps.get("trigger", "") or ""
    ps_effect = ps.get("effect", "") or ""
    has_sq = ps.get("has_sq_skill", False)
    sq_details = ps.get("sq_skill_details", None)
    is_eb = ps.get("is_eb_skill", False)
    eb_trigger_level = ps.get("eb_trigger_level", None)

    # Empty trigger AND empty effect
    if not ps_trigger and not ps_effect:
        add("5_ps_empty_trigger_and_effect", f"{tag}: pilot_skill trigger='' and effect=''")

    # has_sq_skill=true but sq_skill_details is null/empty
    if has_sq and (sq_details is None or sq_details == "" or sq_details == {}):
        add("5_ps_sq_skill_missing_details",
            f"{tag}: has_sq_skill=true but sq_skill_details is null/empty")

    # is_eb_skill=true but no eb_trigger_level and trigger doesn't mention EB
    if is_eb:
        trigger_mentions_eb = "EB" in ps_trigger or "ECHOES" in ps_trigger.upper()
        if eb_trigger_level is None and not trigger_mentions_eb:
            add("5_ps_eb_skill_no_level",
                f"{tag}: is_eb_skill=true but eb_trigger_level=null and trigger='{ps_trigger}'")

# ═════════════════════════════════════════════
# 6. Cross-reference Checks
# ═════════════════════════════════════════════
details_nums = set(details.keys())
index_nums = set(index_by_number.keys())

# In details but not in index
for num in sorted(details_nums - index_nums):
    add("6_in_details_not_index", f"{num}: in card_details.json but not in card_index.json")

# In index but not in details
for num in sorted(index_nums - details_nums):
    add("6_in_index_not_details", f"{num}: in card_index.json but not in card_details.json")

# Stats mismatch between index and details
STAT_MAP = {
    "mobility": "mobility",
    "ranged": "ranged_attack",
    "melee": "melee_attack",
    "hp": "hp",
}
for card_num in sorted(details_nums & index_nums):
    details_card = details[card_num]
    index_card = index_by_number[card_num]
    ocr = details_card.get("ocr_data", {})
    details_stats = ocr.get("stats", {}) or {}

    for idx_key, det_key in STAT_MAP.items():
        idx_val = index_card.get(idx_key, None)
        det_val = details_stats.get(det_key, None)
        if idx_val != det_val:
            add("6_stats_mismatch",
                f"{card_num}: {idx_key} index={idx_val} vs details={det_val}")

# Name mismatch
for card_num in sorted(details_nums & index_nums):
    details_name = details[card_num].get("name", "")
    index_name = index_by_number[card_num].get("name", "")
    if details_name != index_name:
        add("6_name_mismatch",
            f"{card_num}: details name='{details_name}' vs index name='{index_name}'")

# ═════════════════════════════════════════════
# 7. Series/Type Consistency
# ═════════════════════════════════════════════
# Type mismatch between index and details
for card_num in sorted(details_nums & index_nums):
    details_ocr_type = details[card_num].get("ocr_data", {}).get("type", "")
    index_type = index_by_number[card_num].get("type", "")
    if details_ocr_type and index_type and details_ocr_type != index_type:
        add("7_type_mismatch",
            f"{card_num}: details type='{details_ocr_type}' vs index type='{index_type}'")

# Parallel cards (_p1, _p2) with different type than base
parallel_re = re.compile(r'^(.+?)_p(\d+)$', re.IGNORECASE)
for card_num in sorted(details_nums):
    m = parallel_re.match(card_num)
    if not m:
        continue
    base_num = m.group(1)
    if base_num not in details:
        add("7_parallel_no_base",
            f"{card_num}: parallel card but base '{base_num}' not found in details")
        continue
    para_type = details[card_num].get("ocr_data", {}).get("type", "")
    base_type = details[base_num].get("ocr_data", {}).get("type", "")
    if para_type and base_type and para_type != base_type:
        add("7_parallel_type_mismatch",
            f"{card_num}: parallel type='{para_type}' differs from base '{base_num}' type='{base_type}'")

# ─────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────
CATEGORY_LABELS = {
    "1_link_empty_name":            "1a. Link Ability - Empty name",
    "1_link_empty_condition":       "1b. Link Ability - Empty condition",
    "1_link_empty_effect":          "1c. Link Ability - Empty effect",
    "1_link_name_contains_effect":  "1d. Link Ability - Name contains effect text",
    "1_link_condition_nonstandard": "1e. Link Ability - Non-standard condition",
    "1_link_ms_has_pl_only":        "1f. Link Ability - MS card has PL-only link",
    "1_link_pl_has_ms_only":        "1g. Link Ability - PL card has MS-only link",
    "2_stats_all_zero":             "2a. Stats - All zero",
    "2_stats_negative":             "2b. Stats - Negative value",
    "2_stats_too_high":             "2c. Stats - Unreasonably high (>1000)",
    "2_terrain_all_empty":          "2d. Stats - MS terrain all empty",
    "2_terrain_missing":            "2e. Stats - MS terrain key missing",
    "3_name_empty_top":             "3a. Name - Top-level name empty",
    "3_name_empty_ocr":             "3b. Name - ocr_data.name empty",
    "3_name_looks_like_model":      "3c. Name - Looks like model number",
    "3_duplicate_name_in_series":   "3d. Name - Duplicate within series",
    "4_sa_empty_name":              "4a. Special Attack - Empty name with content",
    "4_sa_zero_power":              "4b. Special Attack - Zero/null power with description",
    "4_sa_unknown_sp_type":         "4c. Special Attack - Unknown sp_type",
    "5_ps_missing":                 "5a. Pilot Skill - Missing entirely",
    "5_ps_empty_trigger_and_effect":"5b. Pilot Skill - Empty trigger AND effect",
    "5_ps_sq_skill_missing_details":"5c. Pilot Skill - has_sq_skill but no details",
    "5_ps_eb_skill_no_level":       "5d. Pilot Skill - is_eb_skill but no level/trigger",
    "6_in_details_not_index":       "6a. Cross-ref - In details not in index",
    "6_in_index_not_details":       "6b. Cross-ref - In index not in details",
    "6_stats_mismatch":             "6c. Cross-ref - Stats mismatch",
    "6_name_mismatch":              "6d. Cross-ref - Name mismatch",
    "7_type_mismatch":              "7a. Type - Mismatch between index and details",
    "7_parallel_no_base":           "7b. Type - Parallel card missing base",
    "7_parallel_type_mismatch":     "7c. Type - Parallel type differs from base",
}

total = 0
print("=" * 70)
print("DATA INTEGRITY REPORT")
print("=" * 70)

for key in sorted(anomalies.keys()):
    items = anomalies[key]
    label = CATEGORY_LABELS.get(key, key)
    print(f"\n[{label}] — {len(items)} anomaly(ies)")
    print("-" * 60)
    for item in items:
        print(f"  {item}")
    total += len(items)

print()
print("=" * 70)
print(f"TOTAL ANOMALIES: {total}")
print("=" * 70)

# Summary table
print("\nSUMMARY BY CATEGORY:")
print(f"{'Category':<55} {'Count':>6}")
print("-" * 63)
for key in sorted(anomalies.keys()):
    label = CATEGORY_LABELS.get(key, key)
    print(f"  {label:<53} {len(anomalies[key]):>6}")
print("-" * 63)
print(f"  {'TOTAL':<53} {total:>6}")
