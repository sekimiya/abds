#!/usr/bin/env python3
"""
Comprehensive OCR data format analysis for /ocr_results_debug/_basic.json files.
Research only - reads files, does not modify anything.
"""

import json
import os
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

OCR_DIR = Path("/Users/sekimiya/workspace/abds/ocr_results_debug")

# ── helpers ────────────────────────────────────────────────────────────────────

def extract_series(filename: str) -> str:
    """Extract series code like AB01, VE01, VEB02, FQ01, PR, BP04, LX01 …"""
    m = re.search(r'_((?:AB|VE(?:B)?|FQ|BP|PR|LX|VEB)[A-Z0-9]*)-(\d+)', filename)
    if m:
        return m.group(1)
    # fallback: grab card-number prefix before the hyphen
    m2 = re.search(r'_(([A-Z]+[0-9]+)-\d+)', filename)
    if m2:
        return m2.group(2).split('-')[0]
    # PR cards have no number
    if re.search(r'_PR-\d+_', filename):
        return 'PR'
    return 'UNKNOWN'

def get_type_label(value) -> str:
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, int):
        return 'int'
    if isinstance(value, float):
        return 'float'
    if isinstance(value, str):
        return 'str'
    if isinstance(value, list):
        return 'list'
    if isinstance(value, dict):
        return 'dict'
    return type(value).__name__

def flatten_paths(obj, prefix='ocr_data', depth=0, max_depth=3):
    """Yield (path, type_label) for every node up to max_depth."""
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}"
            yield path, get_type_label(v)
            if isinstance(v, (dict, list)) and depth < max_depth:
                yield from flatten_paths(v, path, depth + 1, max_depth)
    elif isinstance(obj, list):
        if obj:
            v = obj[0]
            path = f"{prefix}[]"
            yield path, get_type_label(v)
            if isinstance(v, (dict, list)) and depth < max_depth:
                yield from flatten_paths(v, path, depth + 1, max_depth)

def top_keys(obj) -> frozenset:
    if isinstance(obj, dict):
        return frozenset(obj.keys())
    return frozenset()

def sub_keys(obj, key) -> frozenset:
    v = obj.get(key) if isinstance(obj, dict) else None
    if isinstance(v, dict):
        return frozenset(v.keys())
    if isinstance(v, list) and v and isinstance(v[0], dict):
        all_k = set()
        for item in v:
            if isinstance(item, dict):
                all_k.update(item.keys())
        return frozenset(all_k)
    return frozenset()

# ── load all files ─────────────────────────────────────────────────────────────

print("Loading _basic.json files …", flush=True)
records = []
errors = []

for fname in sorted(OCR_DIR.iterdir()):
    if not fname.name.endswith('_basic.json'):
        continue
    try:
        with open(fname, encoding='utf-8') as f:
            data = json.load(f)
        series = extract_series(fname.name)
        records.append({
            'filename': fname.name,
            'series': series,
            'engine': data.get('ocr_engine', 'UNKNOWN'),
            'card_type': data.get('ocr_data', {}).get('type', 'UNKNOWN'),
            'ocr_data': data.get('ocr_data', {}),
            'top_keys': top_keys(data.get('ocr_data', {})),
        })
    except Exception as e:
        errors.append((fname.name, str(e)))

print(f"Loaded {len(records)} records. Errors: {len(errors)}")
if errors:
    for fn, err in errors[:10]:
        print(f"  ERROR {fn}: {err}")

# ── section separator ──────────────────────────────────────────────────────────

SEP = '=' * 80
SEP2 = '-' * 60

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Per-engine breakdown
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n{SEP}")
print("SECTION 1: PER-ENGINE BREAKDOWN")
print(SEP)

by_engine = defaultdict(list)
for r in records:
    by_engine[r['engine']].append(r)

# Determine majority top-key set across ALL records
all_topkeys_counter = Counter()
for r in records:
    all_topkeys_counter[r['top_keys']] += 1
majority_topkeys = all_topkeys_counter.most_common(1)[0][0]

for engine, recs in sorted(by_engine.items(), key=lambda x: -len(x[1])):
    series_in_engine = Counter(r['series'] for r in recs)
    topkey_shapes = Counter(r['top_keys'] for r in recs)
    card_types = Counter(r['card_type'] for r in recs)

    print(f"\nEngine: {engine}")
    print(f"  File count : {len(recs)}")
    print(f"  Card types : {dict(card_types.most_common())}")
    print(f"  Series     : {', '.join(f'{s}({n})' for s,n in series_in_engine.most_common())}")
    print(f"  Top-key shapes ({len(topkey_shapes)} distinct):")
    for shape, cnt in topkey_shapes.most_common():
        diff_from_majority = (shape - majority_topkeys, majority_topkeys - shape)
        diff_str = ''
        if diff_from_majority[0]:
            diff_str += f' +EXTRA:{sorted(diff_from_majority[0])}'
        if diff_from_majority[1]:
            diff_str += f' -MISSING:{sorted(diff_from_majority[1])}'
        if not diff_str:
            diff_str = ' [matches majority]'
        print(f"    {cnt:4d}x  keys={sorted(shape)}{diff_str}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Per-series breakdown
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n{SEP}")
print("SECTION 2: PER-SERIES BREAKDOWN")
print(SEP)

NESTED_KEYS = ['stats', 'special_attack', 'ms_ability', 'pilot_skill', 'link_ability',
               'weapon', 'terrain_compatibility', 'card_label']

by_series = defaultdict(list)
for r in records:
    by_series[r['series']].append(r)

# Compute majority top-keys across all series
majority_top_set = majority_topkeys

for series, recs in sorted(by_series.items()):
    engines = Counter(r['engine'] for r in recs)
    card_types = Counter(r['card_type'] for r in recs)
    all_topkeys_in_series = set()
    for r in recs:
        all_topkeys_in_series.update(r['top_keys'])

    # Subkey analysis
    nested_analysis = {}
    for nk in NESTED_KEYS:
        subkey_counter = Counter()
        present = 0
        for r in recs:
            v = r['ocr_data'].get(nk)
            if v is not None:
                present += 1
            sk = sub_keys(r['ocr_data'], nk)
            if sk:
                subkey_counter[sk] += 1
        if subkey_counter:
            nested_analysis[nk] = (present, len(recs), subkey_counter)

    # Unique keys vs majority
    unique_keys = all_topkeys_in_series - majority_top_set
    missing_keys = majority_top_set - all_topkeys_in_series

    print(f"\n{SEP2}")
    print(f"Series: {series}  ({len(recs)} files)")
    print(f"  Engines    : {dict(engines.most_common())}")
    print(f"  Card types : {dict(card_types.most_common())}")
    print(f"  All top-level keys in ocr_data: {sorted(all_topkeys_in_series)}")
    if unique_keys:
        print(f"  ** UNIQUE keys (not in majority): {sorted(unique_keys)}")
    if missing_keys:
        print(f"  ** MISSING keys (in majority but not here): {sorted(missing_keys)}")

    for nk, (present, total, sk_counter) in nested_analysis.items():
        print(f"  [{nk}] present in {present}/{total} files")
        for shape, cnt in sk_counter.most_common():
            print(f"    {cnt:3d}x  sub-keys={sorted(shape)}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Field name census
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n{SEP}")
print("SECTION 3: FIELD NAME CENSUS")
print(SEP)

total = len(records)
# path -> set of type labels seen, count of files
path_types = defaultdict(set)    # path -> set of type labels
path_count = Counter()           # path -> file count

for r in records:
    seen_paths = set()
    for path, tlabel in flatten_paths(r['ocr_data']):
        if path not in seen_paths:
            path_count[path] += 1
            seen_paths.add(path)
        path_types[path].add(tlabel)

# Sort by frequency descending
print(f"\n{'Path':<60} {'Count':>6}  {'%':>5}  Types")
print('-' * 90)
for path, cnt in sorted(path_count.items(), key=lambda x: -x[1]):
    pct = cnt / total * 100
    types = sorted(path_types[path])
    flag = ''
    if pct < 10:
        flag = '  << RARE (<10%)'
    elif pct > 90:
        flag = '  >> COMMON (>90%)'
    print(f"{path:<60} {cnt:>6}  {pct:>5.1f}%  {types}{flag}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Value type inconsistencies
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n{SEP}")
print("SECTION 4: VALUE TYPE INCONSISTENCIES")
print(SEP)

inconsistent = {p: ts for p, ts in path_types.items() if len(ts) > 1}
print(f"\n{len(inconsistent)} paths with mixed types:\n")
for path in sorted(inconsistent.keys()):
    types = sorted(inconsistent[path])
    cnt = path_count[path]
    pct = cnt / total * 100
    # get per-type counts
    type_counts = Counter()
    for r in records:
        found = False
        for pp, tl in flatten_paths(r['ocr_data']):
            if pp == path:
                type_counts[tl] += 1
                found = True
                break
    print(f"  {path}")
    print(f"    files={cnt} ({pct:.1f}%)  types seen: {types}")
    print(f"    per-type count: {dict(type_counts)}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Canonical format
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n{SEP}")
print("SECTION 5: CANONICAL FORMAT")
print(SEP)

def canonical_for_type(card_type_filter):
    filtered = [r for r in records if r['card_type'] == card_type_filter]
    if not filtered:
        return None, None
    n = len(filtered)

    path_type_for_type = defaultdict(set)
    path_count_for_type = Counter()
    for r in filtered:
        seen = set()
        for path, tl in flatten_paths(r['ocr_data']):
            if path not in seen:
                path_count_for_type[path] += 1
                seen.add(path)
            path_type_for_type[path].add(tl)

    # Fields present in >50% of this type
    canon_fields = {p: (path_count_for_type[p], path_type_for_type[p])
                    for p in path_count_for_type
                    if path_count_for_type[p] / n > 0.5}
    return canon_fields, n

for card_type in ['MS', 'PL']:
    fields, n = canonical_for_type(card_type)
    if not fields:
        print(f"\n{card_type}: no records found")
        continue
    print(f"\nCanonical format for {card_type} cards (n={n}):")
    print(f"  (fields present in >50% of {card_type} cards, sorted by frequency)")
    print(f"  {'Field Path':<55} {'Count':>6}  {'%':>5}  Dominant Type")
    print(f"  {'-'*80}")
    for path, (cnt, types) in sorted(fields.items(), key=lambda x: -x[1][0]):
        pct = cnt / n * 100
        # pick most common type
        tc = Counter()
        for r in records:
            if r['card_type'] != card_type:
                continue
            for pp, tl in flatten_paths(r['ocr_data']):
                if pp == path:
                    tc[tl] += 1
                    break
        dom_type = tc.most_common(1)[0][0] if tc else '?'
        type_detail = f"{dom_type}" if len(types) == 1 else f"{dom_type}(*mixed:{sorted(types)})"
        print(f"  {path:<55} {cnt:>6}  {pct:>5.1f}%  {type_detail}")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Deviation summary per series
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n{SEP}")
print("SECTION 6: DEVIATION SUMMARY PER SERIES")
print(SEP)

# Build canonical sets for MS and PL (fields >50%)
canon_by_type = {}
for card_type in ['MS', 'PL']:
    fields, n = canonical_for_type(card_type)
    if fields:
        canon_by_type[card_type] = set(fields.keys())

print(f"\nCanonical MS field paths ({len(canon_by_type.get('MS', set()))}):")
for p in sorted(canon_by_type.get('MS', set())):
    print(f"  {p}")
print(f"\nCanonical PL field paths ({len(canon_by_type.get('PL', set()))}):")
for p in sorted(canon_by_type.get('PL', set())):
    print(f"  {p}")

print(f"\n{'Series':<10} {'Type':<4}  {'Files':>5}  {'Deviant fields'}")
print('-' * 80)

for series, recs in sorted(by_series.items()):
    for card_type in ['MS', 'PL']:
        type_recs = [r for r in recs if r['card_type'] == card_type]
        if not type_recs:
            continue
        canon = canon_by_type.get(card_type, set())

        # Per-file path presence
        series_paths = defaultdict(int)
        for r in type_recs:
            seen = set()
            for path, tl in flatten_paths(r['ocr_data']):
                if path not in seen:
                    series_paths[path] += 1
                    seen.add(path)
        n = len(type_recs)

        # Fields in canon but present in <50% of this series
        missing_in_series = {p for p in canon
                             if series_paths.get(p, 0) / n < 0.5}
        # Fields in this series (>50%) but not in canon
        extra_in_series = {p for p, cnt in series_paths.items()
                          if cnt / n > 0.5 and p not in canon}

        total_deviations = len(missing_in_series) + len(extra_in_series)
        if total_deviations > 0:
            print(f"\n{series:<10} {card_type:<4}  {n:>5}")
            if missing_in_series:
                print(f"  MISSING from canon : {sorted(missing_in_series)}")
            if extra_in_series:
                print(f"  EXTRA vs canon     : {sorted(extra_in_series)}")
        else:
            print(f"{series:<10} {card_type:<4}  {n:>5}  [no deviations]")

print(f"\n{SEP}")
print("END OF REPORT")
print(SEP)
