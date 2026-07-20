#!/usr/bin/env python3
"""
Normalize special_attack fields in card_details.json.

Consolidates various legacy representations of united_sp, squad_sp,
and echoes_beat into a consistent schema.
"""

import json
import copy
import sys
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "card_details.json"

# --- Statistics ---
stats = {
    "total": 0,
    "united_normalized": 0,
    "united_nullified": 0,
    "united_uncertain": 0,
    "squad_normalized": 0,
    "squad_uncertain": 0,
    "eb_normalized": 0,
    "eb_uncertain": 0,
    "power_objects_flattened": 0,
    "keys_cleaned": 0,
}

# Keys to remove from special_attack after migration
SA_CLEANUP_KEYS = {
    # sq_sp_* flat keys
    "sq_sp_name", "sq_sp_target", "sq_sp_range", "sq_sp_power", "sq_sp_description",
    # squad_sp_* flat keys
    "squad_sp_name", "squad_sp_condition", "squad_sp_target", "squad_sp_range",
    "squad_sp_power", "squad_sp_description",
    # sq_target2 etc
    "sq_target2", "sq_range2", "sq_power",
    # eb flat keys
    "eb_level", "eb_power", "eb_description", "eb_target", "eb_range", "eb_note", "eb_name",
    # echoes_beat legacy
    "echoes_beat_sp", "echoes_beat_lv", "echo", "power_eb", "power_enhanced",
    # squad_rush
    "squad_rush_condition",
}

# Keys to keep (not clean up)
# attack_type is explicitly kept


def normalize_power(sa, united_sp_out, squad_sp_out):
    """Normalize power field. Returns the normalized power value."""
    power = sa.get("power")
    if not isinstance(power, dict):
        return power  # already int or null

    if not power:  # empty dict
        stats["power_objects_flattened"] += 1
        return None

    stats["power_objects_flattened"] += 1

    # Extract united/squad power for sub-SP objects
    united_power = power.get("united")
    squad_power = power.get("squad")

    if united_power is not None and united_sp_out is not None:
        # Handle list values like [null]
        if isinstance(united_power, list):
            united_power = united_power[0] if united_power else None
        if united_power is not None:
            united_sp_out["power"] = united_power

    if squad_power is not None and squad_sp_out is not None:
        if isinstance(squad_power, list):
            squad_power = squad_power[0] if squad_power else None
        if squad_power is not None:
            squad_sp_out["power"] = squad_power

    return power.get("normal")


def normalize_united_sp(sa, sp_type):
    """Normalize united_sp. Returns (united_sp_dict_or_None, extracted_squad_sp_or_None)."""
    usp = sa.get("united_sp")
    extracted_squad = None

    if usp is None:
        return None, None

    if not isinstance(usp, dict):
        return None, None

    # All null → null
    if all(v is None for v in usp.values()):
        return None, None

    # If sp_type is "normal" but united_sp exists with some data,
    # only nullify if ALL meaningful fields are null
    if sp_type == "normal":
        return None, None

    # Extract squad_sp info from inside united_sp (FQ06-021 pattern)
    if usp.get("squad_sp") or usp.get("squad_sp_condition"):
        extracted_squad = {}
        if usp.get("squad_sp_condition"):
            extracted_squad["condition"] = usp["squad_sp_condition"]
        # The united_sp itself may serve as squad_sp data in some cases
        # but we keep the united_sp data as-is minus the squad keys

    # Extract type/sp_type that indicate squad (FQ05-002, FQ06-020)
    usp_type = usp.get("type") or usp.get("sp_type")
    if usp_type and "SQUAD" in str(usp_type).upper():
        # This united_sp is actually describing a squad_sp
        extracted_squad = extracted_squad or {}
        extracted_squad["name"] = usp.get("name")
        extracted_squad["condition"] = extracted_squad.get("condition") or usp.get("condition")
        extracted_squad["target"] = usp.get("target")
        extracted_squad["range"] = usp.get("range")
        extracted_squad["power"] = usp.get("power")
        extracted_squad["description"] = usp.get("description")
        extracted_squad["_uncertain"] = True

    # Flatten partners
    partners = []
    for key in ["partner1", "partner2", "partner3", "partner4"]:
        val = usp.get(key)
        if val is not None:
            partners.append(val)

    # Build normalized united_sp
    result = {}
    if usp.get("name") is not None:
        result["name"] = usp["name"]
    if usp.get("condition") is not None:
        result["condition"] = usp["condition"]
    if partners:
        result["partners"] = partners
    if usp.get("target") is not None:
        result["target"] = usp["target"]
    if usp.get("range") is not None:
        result["range"] = usp["range"]
    if usp.get("power") is not None:
        result["power"] = usp["power"]
    if usp.get("description") is not None:
        result["description"] = usp["description"]

    # If after extraction it was actually a squad_sp type, nullify united_sp
    if usp_type and "SQUAD" in str(usp_type).upper():
        return None, extracted_squad

    # Check if all result fields are empty
    if not result or all(v is None for v in result.values()):
        return None, extracted_squad

    # Mark uncertain if power or description is missing while other fields exist
    has_some_data = any(result.get(k) is not None for k in ["name", "target", "range", "partners"])
    missing_key_info = result.get("power") is None or result.get("description") is None
    if has_some_data and missing_key_info:
        result["_uncertain"] = True

    return result, extracted_squad


def build_squad_sp(sa, extracted_from_united):
    """Build normalized squad_sp from all sources. Returns dict or None."""
    candidates = []

    # Source 1: special_attack.squad_sp dict (highest priority, no uncertain)
    sq_dict = sa.get("squad_sp")
    if isinstance(sq_dict, dict) and sq_dict:
        entry = {}
        entry["name"] = sq_dict.get("name")
        entry["condition"] = sq_dict.get("note") or sq_dict.get("condition") or sq_dict.get("squad_rush_condition")
        entry["target"] = sq_dict.get("target")
        entry["range"] = sq_dict.get("range")
        entry["power"] = sq_dict.get("power")
        entry["description"] = sq_dict.get("description")
        # Source 1 is standard representation, no _uncertain
        candidates.append(("dict", entry))

    # Source 2: sq_sp_* flat keys
    if any(sa.get(k) for k in ["sq_sp_name", "sq_sp_target", "sq_sp_range", "sq_sp_power", "sq_sp_description"]):
        entry = {
            "name": sa.get("sq_sp_name"),
            "condition": sa.get("sq_sp_description") if sa.get("sq_sp_description") and "SQUAD" in str(sa.get("sq_sp_description", "")).upper() else None,
            "target": sa.get("sq_sp_target"),
            "range": sa.get("sq_sp_range"),
            "power": sa.get("sq_sp_power"),
            "description": sa.get("sq_sp_description"),
            "_uncertain": True,
        }
        candidates.append(("sq_sp", entry))

    # Source 3: squad_sp_* flat keys
    if any(sa.get(k) for k in ["squad_sp_name", "squad_sp_condition", "squad_sp_target", "squad_sp_range", "squad_sp_power", "squad_sp_description"]):
        entry = {
            "name": sa.get("squad_sp_name"),
            "condition": sa.get("squad_sp_condition"),
            "target": sa.get("squad_sp_target"),
            "range": sa.get("squad_sp_range"),
            "power": sa.get("squad_sp_power"),
            "description": sa.get("squad_sp_description"),
            "_uncertain": True,
        }
        candidates.append(("squad_sp_flat", entry))

    # Source 4: sq_target2/sq_range2/sq_power
    if any(sa.get(k) for k in ["sq_target2", "sq_range2", "sq_power"]):
        entry = {
            "name": None,
            "condition": None,
            "target": sa.get("sq_target2"),
            "range": sa.get("sq_range2"),
            "power": sa.get("sq_power"),
            "description": None,
            "_uncertain": True,
        }
        candidates.append(("sq_target2", entry))

    # Source 5: from inside united_sp
    if extracted_from_united:
        if "_uncertain" not in extracted_from_united:
            extracted_from_united["_uncertain"] = True
        candidates.append(("united_extract", extracted_from_united))

    # squad_rush_condition (standalone)
    if sa.get("squad_rush_condition") and not candidates:
        entry = {
            "name": None,
            "condition": sa.get("squad_rush_condition"),
            "target": None,
            "range": None,
            "power": None,
            "description": None,
            "_uncertain": True,
        }
        candidates.append(("rush_cond", entry))

    if not candidates:
        return None

    # Use first (highest priority) candidate as base, merge missing fields from others
    result = candidates[0][1]
    is_uncertain = result.get("_uncertain", False)

    for _, other in candidates[1:]:
        for key in ["name", "condition", "target", "range", "power", "description"]:
            if result.get(key) is None and other.get(key) is not None:
                result[key] = other[key]
        if other.get("_uncertain"):
            is_uncertain = True

    # Apply squad_rush_condition if we have it and no condition yet
    if result.get("condition") is None and sa.get("squad_rush_condition"):
        result["condition"] = sa["squad_rush_condition"]
        is_uncertain = True

    # Clean None fields but keep the structure
    final = {}
    for key in ["name", "condition", "target", "range", "power", "description"]:
        final[key] = result.get(key)
    if is_uncertain:
        final["_uncertain"] = True

    # If all content fields are None, return None
    if all(final.get(k) is None for k in ["name", "condition", "target", "range", "power", "description"]):
        return None

    return final


def build_echoes_beat(sa, ocr_data):
    """Build normalized echoes_beat from all sources. Returns dict or None."""
    layers = []  # (priority, data, uncertain)

    # Source 1 (highest priority): ocr_data.echoes_beat
    ocr_eb = ocr_data.get("echoes_beat")
    if isinstance(ocr_eb, dict) and ocr_eb.get("has_eb"):
        entry = {
            "level": ocr_eb.get("eb_level"),
            "name": ocr_eb.get("eb_sp_name") or None,  # empty string → None
            "target": ocr_eb.get("eb_target") or None,
            "range": ocr_eb.get("eb_range"),
            "power": ocr_eb.get("eb_power"),
            "description": ocr_eb.get("eb_description") or None,
        }
        is_sp = ocr_eb.get("eb_type") == "sp"
        layers.append((1, entry, False, is_sp))

    # Source 2: special_attack.echoes_beat dict
    eb_dict = sa.get("echoes_beat")
    if isinstance(eb_dict, dict) and eb_dict:
        entry = {
            "level": eb_dict.get("level"),
            "name": eb_dict.get("name"),
            "target": eb_dict.get("target"),
            "range": eb_dict.get("range"),
            "power": eb_dict.get("power"),
            "description": eb_dict.get("description"),
        }
        layers.append((2, entry, True, False))

    # Source 3: special_attack.echoes_beat_sp dict
    eb_sp = sa.get("echoes_beat_sp")
    if isinstance(eb_sp, dict) and eb_sp:
        entry = {
            "level": eb_sp.get("eb_level"),
            "name": eb_sp.get("name"),
            "target": eb_sp.get("target"),
            "range": eb_sp.get("range"),
            "power": eb_sp.get("power"),
            "description": eb_sp.get("description"),
        }
        layers.append((3, entry, True, False))

    # Source 4: eb_* flat keys in special_attack
    eb_flat_keys = ["eb_level", "eb_power", "eb_description", "eb_target", "eb_range", "eb_note", "eb_name"]
    if any(sa.get(k) is not None for k in eb_flat_keys):
        entry = {
            "level": sa.get("eb_level"),
            "name": sa.get("eb_name"),
            "target": sa.get("eb_target"),
            "range": sa.get("eb_range"),
            "power": sa.get("eb_power") or sa.get("power_eb"),
            "description": sa.get("eb_description"),
        }
        layers.append((4, entry, True, False))

    # Source 5: echoes_beat_lv, echo, power_eb, power_enhanced
    if sa.get("echoes_beat_lv") or sa.get("echo") or sa.get("power_eb") or sa.get("power_enhanced"):
        entry = {
            "level": sa.get("echoes_beat_lv"),
            "name": None,
            "target": None,
            "range": None,
            "power": sa.get("power_eb") or sa.get("power_enhanced"),
            "description": None,
        }
        layers.append((5, entry, True, False))

    if not layers:
        return None, False

    # Merge: priority 1 wins for conflicts
    layers.sort(key=lambda x: x[0])
    result = {}
    uncertain = False
    is_eb_sp = False

    for priority, entry, unc, is_sp in layers:
        for key in ["level", "name", "target", "range", "power", "description"]:
            if result.get(key) is None and entry.get(key) is not None:
                result[key] = entry[key]
        if unc:
            uncertain = True
        if is_sp:
            is_eb_sp = True

    # If only source 1 contributed, not uncertain
    if len(layers) == 1 and not layers[0][2]:
        uncertain = False

    # If all fields are None, return None
    if all(result.get(k) is None for k in ["level", "name", "target", "range", "power", "description"]):
        return None, is_eb_sp

    # Build final
    final = {}
    for key in ["level", "name", "target", "range", "power", "description"]:
        final[key] = result.get(key)

    if uncertain:
        final["_uncertain"] = True

    return final, is_eb_sp


def normalize_card(card_id, card):
    """Normalize one card's special_attack. Modifies card in-place."""
    ocr_data = card.get("ocr_data")
    if not ocr_data:
        return

    sa = ocr_data.get("special_attack")
    if not sa or not isinstance(sa, dict):
        return

    stats["total"] += 1

    # --- sp_type ---
    sp_type = sa.get("sp_type", "normal") or "normal"

    # --- united_sp ---
    united_sp, extracted_squad = normalize_united_sp(sa, sp_type)

    # --- squad_sp (from all sources) ---
    squad_sp = build_squad_sp(sa, extracted_squad)

    # --- echoes_beat (from all sources) ---
    echoes_beat, is_eb_sp = build_echoes_beat(sa, ocr_data)

    # --- sp_type update ---
    if is_eb_sp:
        sp_type = "ECHOES BEAT SP"

    # --- power normalization (needs references to united/squad for power injection) ---
    power = normalize_power(sa, united_sp, squad_sp)

    # --- Build new special_attack ---
    new_sa = {}

    # Preserve standard fields in order
    if "name" in sa:
        new_sa["name"] = sa["name"]
    new_sa["sp_type"] = sp_type
    if "target" in sa:
        new_sa["target"] = sa["target"]
    if "range" in sa:
        new_sa["range"] = sa["range"]
    if "sp_cost" in sa:
        new_sa["sp_cost"] = sa["sp_cost"]
    new_sa["power"] = power
    if "description" in sa:
        new_sa["description"] = sa["description"]

    # Preserve attack_type if present
    if "attack_type" in sa:
        new_sa["attack_type"] = sa["attack_type"]

    # Preserve impact_area if present
    if "impact_area" in sa:
        new_sa["impact_area"] = sa["impact_area"]

    # Set normalized sub-objects
    new_sa["united_sp"] = united_sp
    new_sa["squad_sp"] = squad_sp
    new_sa["echoes_beat"] = echoes_beat

    # --- Stats ---
    orig_usp = sa.get("united_sp")
    if isinstance(orig_usp, dict) and any(v is not None for v in orig_usp.values()):
        if united_sp is not None:
            stats["united_normalized"] += 1
            if united_sp.get("_uncertain"):
                stats["united_uncertain"] += 1
        else:
            stats["united_nullified"] += 1

    if squad_sp is not None:
        stats["squad_normalized"] += 1
        if squad_sp.get("_uncertain"):
            stats["squad_uncertain"] += 1

    if echoes_beat is not None:
        stats["eb_normalized"] += 1
        if echoes_beat.get("_uncertain"):
            stats["eb_uncertain"] += 1

    # Count cleaned keys
    for key in SA_CLEANUP_KEYS:
        if key in sa:
            stats["keys_cleaned"] += 1

    # Replace special_attack
    ocr_data["special_attack"] = new_sa

    # Remove ocr_data.echoes_beat
    if "echoes_beat" in ocr_data:
        del ocr_data["echoes_beat"]


def main():
    print(f"Loading {DATA_PATH} ...")
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Found {len(data)} cards. Normalizing ...")

    for card_id, card in data.items():
        normalize_card(card_id, card)

    print(f"Writing back to {DATA_PATH} ...")
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print()
    print("=== Normalization Statistics ===")
    print(f"Total cards processed:        {stats['total']}")
    print(f"united_sp normalized:         {stats['united_normalized']}")
    print(f"united_sp nullified:          {stats['united_nullified']}")
    print(f"united_sp marked uncertain:   {stats['united_uncertain']}")
    print(f"squad_sp normalized:          {stats['squad_normalized']}")
    print(f"squad_sp marked uncertain:    {stats['squad_uncertain']}")
    print(f"echoes_beat normalized:       {stats['eb_normalized']}")
    print(f"echoes_beat marked uncertain: {stats['eb_uncertain']}")
    print(f"power objects flattened:      {stats['power_objects_flattened']}")
    print(f"Keys cleaned up:             {stats['keys_cleaned']}")
    print()
    print("Done.")


if __name__ == "__main__":
    main()
