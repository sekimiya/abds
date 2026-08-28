#!/usr/bin/env python3
"""
ocr_results_debug/*_basic.json を、元の体裁を保ったまま編集するためのヘルパー。

このリポジトリの _basic.json はインデント幅が2と4で混在している(2026-08時点で
2スペース2,814件 / 4スペース622件)。json.dump()で決め打ちすると
ファイル全体が差分になり、PRのレビューが事実上できなくなる。

修正箇所だけが差分に出るよう、必ずこのヘルパー経由で読み書きすること。

使い方:
    from scripts.ocr_source_edit import load_source, save_source

    data, fmt = load_source(path)
    data['ocr_data']['name'] = '...'
    save_source(path, data, fmt)
"""

import json
import re

DEFAULT_INDENT = 2


def detect_indent(text):
    """JSONテキストの先頭階層から、使われているインデント幅を推定する。"""
    for line in text.splitlines()[1:]:
        m = re.match(r'^( +)\S', line)
        if m:
            return len(m.group(1))
    return DEFAULT_INDENT


def load_source(path):
    """(data, fmt) を返す。fmt は save_source にそのまま渡す。"""
    with open(path, encoding='utf-8') as f:
        text = f.read()
    fmt = {
        'indent': detect_indent(text),
        'trailing_newline': text.endswith('\n'),
    }
    return json.loads(text), fmt


def save_source(path, data, fmt):
    """元の体裁(インデント幅・末尾改行)を保って書き戻す。"""
    text = json.dumps(data, ensure_ascii=False, indent=fmt.get('indent', DEFAULT_INDENT))
    if fmt.get('trailing_newline', True):
        text += '\n'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def replace_in_field(data, path_keys, replacements):
    """ネストしたテキストフィールドに対して、順に置換を適用する。

    path_keys: ['ocr_data', 'special_attack', 'echoes_beat', 'description']
    replacements: [(before, after), ...]
    見つからない置換があれば KeyError/AssertionError で落とす(黙って通さない)。
    Returns: (before_text, after_text)
    """
    node = data
    for k in path_keys[:-1]:
        node = node[k]
    key = path_keys[-1]
    before = node[key]
    after = before
    for a, b in replacements:
        assert a in after, f'置換対象が見つかりません: {a!r} in {".".join(path_keys)}'
        after = after.replace(a, b)
    node[key] = after
    return before, after
