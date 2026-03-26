#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
card_ocr_cc.py — Claude Code CLI (定額プラン) を使ったカードOCR 2段階パイプライン

■ 2段階アーキテクチャ:
  Stage 1 (raw)       : カード画像 → 生テキスト抽出 → _ocr_raw.json に保存
  Stage 2 (structure)  : 生テキスト → 構造化JSON     → _basic.json に保存

  ゲームアップデートでデータ構造が変わった場合、Stage 2 のみ再実行すれば
  画像の再OCR なしで全カードを再構造化できる。

■ Usage:
  # 通常実行（Stage 1 + 2 を連続実行）
  python card_ocr_cc.py --series AB01 --limit 10

  # Stage 1 のみ（RAW テキスト抽出だけ）
  python card_ocr_cc.py --stage raw --series AB01

  # Stage 2 のみ（既存 RAW から構造化）
  python card_ocr_cc.py --stage structure --series AB01

  # 全 RAW データから構造化を再実行（データ構造変更時）
  python card_ocr_cc.py --restructure
  python card_ocr_cc.py --restructure --series FQ01

  # その他
  python card_ocr_cc.py --status
  python card_ocr_cc.py --dry-run --series AB01
  python card_ocr_cc.py --force --limit 5
  python card_ocr_cc.py --model sonnet --delay 5
"""

import os
import sys
import json
import re
import time
import argparse
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    import requests
except ImportError:
    print("Error: requests パッケージが必要です。 pip install requests を実行してください。")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALL_CARDS_DIR = Path("all_cards_list")
OCR_RESULTS_DIR = Path("ocr_results_debug")
IMAGES_DIR = Path("card_images_temp")
PROGRESS_FILE = Path("ocr_cc_progress.json")

DEFAULT_DELAY = 2.0          # claude CLI 呼び出し間隔（秒）
MAX_RETRIES = 3              # リトライ回数
SUBPROCESS_TIMEOUT = 300     # claude CLI のタイムアウト（秒）
MIN_IMAGE_SIZE = 1000        # ダミー画像判定用の最小バイト数
DEFAULT_OCR_MODEL = "opus" # OCR用モデル（sonnet 4.6 はVision精度低下のため opus を使用）

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ---------------------------------------------------------------------------
# Stage 1 Prompt — 画像から生テキストを忠実に抽出する
# ---------------------------------------------------------------------------
RAW_OCR_PROMPT = r"""あなたはカードゲーム「ガンダム アーセナルベース」のカード画像を読み取るOCRエキスパートです。

この画像はカードの **裏面** です。

画像に表示されている **すべてのテキスト** を、セクションごとに忠実に書き起こしてください。

## 出力ルール

1. カード上のテキストを **上から下へ、左から右へ** の順に読み取る
2. セクションの区切りは **空行** で表現する
3. 数値・記号・英語・日本語をすべて **そのまま** 書き起こす
4. 読み取れない文字は [?] と記す
5. アイコンや図形は [アイコン:内容] の形式で記述する（例: [アイコン:地上A]）
6. セクション名（WEAPON, MS ABILITY, LINK ABILITY, SPECIAL ATTACK, IMPACT AREA, PL SKILL, UNITED SP 等）は見出しとして記録する
7. カード右上の「MS」または「PL」の種別を最初に記録する
8. カード右下のカード番号・レアリティ・イラストレーター情報も記録する
9. テキスト以外の説明や解釈は **一切加えない**
10. 出力はプレーンテキストのみ（JSONやマークダウン記法は不要）
"""

# ---------------------------------------------------------------------------
# Stage 2 Prompt — 生テキストから構造化JSONを生成する
# ---------------------------------------------------------------------------
STRUCTURE_PROMPT = r"""カード裏面のOCR生テキストを解析し、JSON形式で構造化してください。
カードは「MS（モビルスーツ）」と「PL（パイロット）」の2種類があります。

## MSカードの場合
```json
{
  "card_id": "AB01-001", "type": "MS",
  "card_label": { "class": "近距離", "cost_label": "コスト4" },
  "name": "ガンダム", "model": "RX-78-2 GUNDAM", "cost": 4, "category": "近距離",
  "affiliation": "地球連邦軍", "pilot": "アムロ・レイ",
  "stats": { "height": "18.0m", "weight": "43.4t", "mobility": 200, "ranged_attack": 110, "melee_attack": 370, "hp": 380 },
  "terrain_compatibility": { "ground": "A", "space": "A", "desert": "C", "water": null },
  "weapon": {
    "main": { "name": "ビーム・サーベル", "range": 1, "type": "近距離" },
    "sub": { "name": "ビーム・ライフル", "range": 3, "type": "遠距離" }
  },
  "ms_ability": { "name": "連撃", "activation": "任意発動", "target": "単体(敵)", "range": 2, "cost": 3, "description": "ロックオン中の敵に単体攻撃でダメージを与える。" },
  "link_ability": [ { "name": "機動戦士ガンダム", "condition": "デッキに3枚以上", "effect": "[機動力]小アップ" } ],
  "special_attack": { "name": "ビーム・サーベル強撃", "target": "単体(敵)", "range": 2, "sp_cost": 2, "power": 3400, "description": "敵単体に格闘攻撃でダメージを与える。", "united_sp": null },
  "rarity": "M", "illustrator": "toriyufu",
  "raw": "（元の生テキストをそのまま記録）"
}
```
UNITED SP がある場合（FQ/UT系）: special_attack.united_sp = { "partner1", "partner2", "range", "power", "description" }。連携相手が「ー」なら null。
ECHOES BEAT がある場合: special_attack に以下のフィールドを追加（キー名は必ずこの通りにすること）:
- "eb_level": EBレベル（整数。例: 2）
- "eb_power": EB時の威力（整数。通常威力とEB威力が「3200 / 3800」のように併記される場合、後者がeb_power）
- "eb_description": EB発動時の効果説明（通常説明と「／」で区切られている場合、「／」以降がEB説明）
- "eb_target": EB時の対象（例: "単体(敵)"。通常と同じ場合も記載）
- "eb_range": EB時の射程（整数。通常と同じ場合も記載）
- "sp_type": "ECHOES BEAT SP"（ECHOES BEAT SPの場合のみ。通常のECHOES BEATにはこのフィールドを付けない）
※ echoes_beat_lv, power_eb 等の別名は使わないこと。必ず上記のキー名を使用する。

## PLカードの場合
```json
{
  "card_id": "AB01-051", "type": "PL",
  "card_label": { "class": "制圧", "cost_label": "コスト4" },
  "name": "アムロ・レイ", "english_name": "AMURO RAY", "cost": 4, "category": "制圧",
  "affiliation": "地球連邦軍",
  "physical": { "height": "168cm", "age": 15 },
  "units": ["ガンダム"],
  "stats": { "mobility": 150, "ranged_attack": 200, "melee_attack": 240, "hp": 160 },
  "pilot_skill": { "name": "決定的な一撃", "trigger": "敵戦艦／拠点をロックオン時", "effect": "敵戦艦／拠点へのダメージを中アップする。", "has_sq_skill": false, "sq_skill_details": null, "is_eb_skill": false },
  "link_ability": [ { "name": "機動戦士ガンダム", "condition": "デッキに3枚以上", "effect": "[機動力]小アップ", "is_eb_link": false } ],
  "rarity": "M", "illustrator": null,
  "raw": "（元の生テキストをそのまま記録）"
}
```
SQ関連スキル (has_sq_skill: true): sq_skill_details = { "sq_gauge_effect", "sq_max_effect", "squad_rush_effect" }。SQ/SQUAD/ゲージ がスキルテキストにあれば true。
EB PL SKILL (is_eb_skill: true): カード上に「EB PL SKILL」と表記されている場合、またはtriggerに「EBLv.」を含む場合。
EB LINK ABILITY (is_eb_link: true): カード上に「EB LINK ABILITY」と表記されている場合、またはeffectに「ECHOES BEAT」「EBLv.」を含む場合。

## ルール
- 読み取れないフィールドは null（空文字列ではなく）
- 数値は数値型（cost, range, power, stats等）
- card_label.class: MSは「近距離/遠距離/機動」、PLは「殲滅/制圧/防衛」
- category は card_label.class と同じ値
- raw には入力された生テキストをそのまま記録
- rarity はカード番号の右に記載（M, R, C, P, U, SR, PR, LR, LE, CP 等。1〜2文字）
- ms_ability は1カードにつき1つ（オブジェクト）。link_ability は1カードにつき通常2つ（配列）。生テキスト上のセクション見出し位置ではなく内容形式で分類すること。ms_ability は発動条件（任意発動等）・対象・射程・コストを持つ戦闘アビリティ。link_ability はデッキ条件とバフ効果を持つ。セクション内に混在している場合も内容に基づいて正しいフィールドに振り分けること
- 出力は ```json ``` で囲み、JSON以外のテキストは出力しない
"""

# ---------------------------------------------------------------------------
# OCR_PROMPT_DIRECT — card_ocr_claude.py 互換の詳細プロンプト（画像→構造化JSON直接出力）
# ---------------------------------------------------------------------------
OCR_PROMPT_DIRECT = r"""カードゲーム「ガンダム アーセナルベース」のカード裏面画像です。
以下の項目を画像から正確に読み取ってください。推測や解釈はせず、読めないものは null としてください。

## 読み取り項目

### 共通項目
1. カード左上の分類テキストとコスト数値
2. カード右上の種別（「MS」または「PL」）
3. キャラクター名または機体名（日本語・英語両方）
4. 右下の4つのステータス数値: 機動力、遠距離攻撃、近距離攻撃、HP
5. リンクアビリティ: 名前、条件（「デッキにX枚以上」等）、効果テキスト（複数ある場合すべて）
6. 「EB LINK ABILITY」と表記されているか、通常の「LINK ABILITY」か
7. カード番号、レアリティ（番号の右の1〜2文字）
8. イラストレーター名（illust.の後の名前）

### MSカード追加項目
9. 型式番号（英語表記、例: RX-78-2 GUNDAM）
10. 全高、本体重量、所属、パイロット名
11. 地形適性（地上/宇宙/砂漠/水中 の A/B/C/S）
12. WEAPON: MAIN名・射程・タイプ、SUB名・射程・タイプ
13. MS ABILITY: 名前、発動条件、対象、射程、コスト、効果テキスト
14. SPECIAL ATTACK: 名前、対象、射程、SPコスト、威力、効果テキスト
15. ECHOES BEAT がある場合: EB名、EBレベル、EB威力、EB対象、EB射程、EB効果テキスト、EB種別（normalまたはsp）
16. UNITED SP がある場合: 連携相手1、連携相手2、射程、威力、効果テキスト

### PLカード追加項目
9. 身長、年齢（数値のみ）、所属、搭乗機体（複数の場合すべて）
10. PL SKILL: スキル名（赤背景の小さいテキスト）、発動条件、効果テキスト
11. 「EB PL SKILL」と表記されているか、通常の「PL SKILL」か
12. スキルテキストに SQ/SQUAD/ゲージ の記述があるか

## 出力形式
読み取った結果を以下のJSON形式で出力してください。

MSカードの場合:
```json
{
  "card_id": "", "type": "MS",
  "card_label": { "class": "近距離/遠距離/機動", "cost_label": "コストN" },
  "name": "", "model": "", "cost": 0, "category": "",
  "affiliation": "", "pilot": "",
  "stats": { "height": "", "weight": "", "mobility": 0, "ranged_attack": 0, "melee_attack": 0, "hp": 0 },
  "terrain_compatibility": { "ground": "", "space": "", "desert": "", "water": null },
  "weapon": {
    "main": { "name": "", "range": 0, "type": "" },
    "sub": { "name": "", "range": 0, "type": "" }
  },
  "ms_ability": { "name": "", "activation": "", "target": "", "range": 0, "cost": 0, "description": "" },
  "link_ability": [ { "name": "", "condition": "", "effect": "" } ],
  "special_attack": { "name": "", "target": "", "range": 0, "sp_cost": 0, "power": 0, "description": "", "echoes_beat": null, "united_sp": null },
  "rarity": "", "illustrator": "", "raw": ""
}
```

echoes_beat がある場合の構造:
```json
"echoes_beat": { "eb_type": "normal/sp", "eb_name": "", "eb_level": 0, "eb_note": "", "eb_target": "", "eb_range": 0, "eb_power": 0, "eb_description": "" }
```
- eb_type: "normal"（ECHOES BEAT）または "sp"（ECHOES BEAT SP）
- 威力が「3300 / 3600」のように2つある場合、前半がspecial_attack.power、後半がeb_power
- 説明文が「/」区切りの場合、前半がspecial_attack.description、後半がeb_description
- ECHOES BEAT表記がない場合は echoes_beat = null

united_sp がある場合: { "partner1": "", "partner2": "", "range": 0, "power": 0, "description": "" }。「ー」なら null。

PLカードの場合:
```json
{
  "card_id": "", "type": "PL",
  "card_label": { "class": "殲滅/制圧/防衛", "cost_label": "コストN" },
  "name": "", "english_name": "", "cost": 0, "category": "",
  "affiliation": "",
  "physical": { "height": "", "age": null },
  "units": [],
  "stats": { "mobility": 0, "ranged_attack": 0, "melee_attack": 0, "hp": 0 },
  "pilot_skill": { "name": "", "trigger": "", "effect": "", "has_sq_skill": false, "sq_skill_details": null, "is_eb_skill": false },
  "link_ability": [ { "name": "", "condition": "", "effect": "", "is_eb_link": false } ],
  "rarity": "", "illustrator": "", "raw": ""
}
```
- is_eb_skill: 「EB PL SKILL」表記 or triggerに「EBLv.」含む場合 true
- is_eb_link: 「EB LINK ABILITY」表記 or effectに「ECHOES BEAT」「EBLv.」含む場合 true
- has_sq_skill: スキルテキストにSQ/SQUAD/ゲージ記述がある場合 true → sq_skill_details: { "sq_gauge_effect": "", "sq_max_effect": "", "squad_rush_effect": "" }

## ルール
- 読み取れないフィールドは null
- 数値は数値型
- category は card_label.class と同じ値（作品名ではない）
- raw は空文字列 "" でよい
- link_ability は通常2つ（配列で全て含める）
- 出力は ```json ``` で囲み、JSON以外のテキストは出力しない
"""

# ---------------------------------------------------------------------------
# Combined Prompt — (レガシー) 1回の呼び出しで画像→生テキスト＋構造化JSONを同時生成
# ---------------------------------------------------------------------------
COMBINED_PROMPT = r"""カードゲーム「ガンダム アーセナルベース」のカード裏面画像を読み取り、以下の2パートを出力してください。

## PART A: 生テキスト抽出
画像上の全テキストを上から下、左から右の順に忠実に書き起こす。
===RAW_START===
（生テキスト）
===RAW_END===

## PART B: 構造化JSON
画像の全情報を正確に読み取り、以下のJSON形式で出力してください（```json```で囲む）。

### MSカードの場合
```json
{
  "card_id": "AB01-001", "type": "MS",
  "card_label": { "class": "近距離", "cost_label": "コスト4" },
  "name": "ガンダム", "model": "RX-78-2 GUNDAM", "cost": 4, "category": "近距離",
  "affiliation": "地球連邦軍", "pilot": "アムロ・レイ",
  "stats": { "height": "18.0m", "weight": "43.4t", "mobility": 200, "ranged_attack": 110, "melee_attack": 370, "hp": 380 },
  "terrain_compatibility": { "ground": "A", "space": "A", "desert": "C", "water": null },
  "weapon": {
    "main": { "name": "ビーム・サーベル", "range": 1, "type": "近距離" },
    "sub": { "name": "ビーム・ライフル", "range": 3, "type": "遠距離" }
  },
  "ms_ability": { "name": "連撃", "activation": "任意発動", "target": "単体(敵)", "range": 2, "cost": 3, "description": "ロックオン中の敵に単体攻撃でダメージを与える。" },
  "link_ability": [ { "name": "機動戦士ガンダム", "condition": "デッキに3枚以上", "effect": "[機動力]小アップ" } ],
  "special_attack": { "name": "ビーム・サーベル強撃", "target": "単体(敵)", "range": 2, "sp_cost": 2, "power": 3400, "description": "敵単体に格闘攻撃でダメージを与える。", "echoes_beat": null, "united_sp": null },
  "rarity": "M", "illustrator": "toriyufu",
  "raw": ""
}
```
UNITED SP がある場合（FQ/UT系）: special_attack.united_sp = { "partner1", "partner2", "range", "power", "description" }。連携相手が「ー」なら null。
SQUAD SP がある場合: sp_type:"SQUAD SP"を追加。squad_sp:{name,target,range,power(整数),description}を別途追加。

#### ECHOES BEAT がある場合（VE系等）
カード上に「ECHOES BEAT」または「ECHOES BEAT SP」の表記がある場合、通常SPとEBを明確に分離する。

**description の分離ルール:**
- カード上の説明文は「通常SP説明 / EB説明」の形式で「/」区切りで2つ並んでいる
- `special_attack.description` には通常SPの説明文のみを格納する（"/"より前の部分）
- EB側の説明文は `echoes_beat.eb_description` に格納する（"/"より後の部分）
- 「ECHOES BEAT Lv.を下げることで、Lv.戦術技が発動する。」等のシステム説明文は `echoes_beat.eb_note` に格納し、description には含めない

**power の分離ルール:**
- 威力が「3300 / 3600」のように2つ表記されている場合、前半が通常SP威力、後半がEB威力
- `special_attack.power` には通常SP威力（前半の数値）
- `echoes_beat.eb_power` にはEB威力（後半の数値）
- EB威力が「ー」なら null

**echoes_beat 構造:**
```json
"echoes_beat": {
  "eb_type": "normal",
  "eb_name": "ファンネル・ミサイル斉射 Lv.1",
  "eb_level": 1,
  "eb_note": "ECHOES BEAT Lv.を下げることで、Lv.戦術技が発動する。",
  "eb_target": "範囲(敵)",
  "eb_range": 3,
  "eb_power": 3600,
  "eb_description": "EBLv.を1下げる。ロックオン中の敵を中心に扇状の範囲攻撃を行い、..."
}
```
- `eb_type`: "normal"（ECHOES BEAT）または "sp"（ECHOES BEAT SP）
- `eb_level`: EB名に含まれる Lv.X の数値（1, 2, 3）
- `eb_name`: EB側のSP名（例: "ファンネル・ミサイル斉射 Lv.1"）
- `eb_note`: システム説明文（"ECHOES BEAT Lv.を下げることで..."）
- `eb_target`, `eb_range`: EB側の対象・射程（通常SPと異なる場合がある）
- `eb_power`: EB威力（数値）
- `eb_description`: EB側の効果説明（"EBLv.をX下げる。..."で始まる文）
- ECHOES BEAT表記がない、または「ー」のみの場合は echoes_beat = null

### PLカードの場合
```json
{
  "card_id": "AB01-051", "type": "PL",
  "card_label": { "class": "制圧", "cost_label": "コスト4" },
  "name": "アムロ・レイ", "english_name": "AMURO RAY", "cost": 4, "category": "制圧",
  "affiliation": "地球連邦軍",
  "physical": { "height": "168cm", "age": 15 },
  "units": ["ガンダム"],
  "stats": { "mobility": 150, "ranged_attack": 200, "melee_attack": 240, "hp": 160 },
  "pilot_skill": { "name": "決定的な一撃", "trigger": "敵戦艦／拠点をロックオン時", "effect": "敵戦艦／拠点へのダメージを中アップする。", "has_sq_skill": false, "sq_skill_details": null, "is_eb_skill": false },
  "link_ability": [ { "name": "機動戦士ガンダム", "condition": "デッキに3枚以上", "effect": "[機動力]小アップ", "is_eb_link": false } ],
  "rarity": "M", "illustrator": null,
  "raw": ""
}
```
SQ関連スキル (has_sq_skill: true): sq_skill_details = { "sq_gauge_effect", "sq_max_effect", "squad_rush_effect" }。SQ/SQUAD/ゲージ がスキルテキストにあれば true。
EB PL SKILL (is_eb_skill: true): カード上に「EB PL SKILL」と表記されている場合、またはtriggerに「EBLv.」を含む場合。
EB LINK ABILITY (is_eb_link: true): カード上に「EB LINK ABILITY」と表記されている場合、またはeffectに「ECHOES BEAT」「EBLv.」を含む場合。

### 共通ルール
- 読み取れないフィールドは null（空文字列ではなく）
- 数値は数値型（cost, range, power, stats等）
- card_label.class: MSは「近距離/遠距離/機動」、PLは「殲滅/制圧/防衛」
- category は card_label.class と同じ値（作品名ではない）
- raw にはPART Aの生テキストをそのまま記録
- rarity はカード番号の右に記載（M, R, C, P, U, SR, PR, LR, LE, CP 等。1〜2文字）
- ms_ability は1カードにつき1つ（オブジェクト）。link_ability は1カードにつき通常2つ（配列）。内容形式で分類：発動条件+射程+コスト→ms_ability、デッキ条件+バフ→link_ability
- link_abilityが複数ある場合はすべて配列に含める。EB LINKと通常LINKが混在する場合も個別にis_eb_linkを設定
- 出力は ```json ``` で囲み、JSON以外のテキストは出力しない

出力順序: PART A → PART B
"""

# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------
def sanitize_filename(s: str) -> str:
    """ファイル名に使用できない文字を置換"""
    return (
        s.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("*", "_")
        .replace("?", "_")
        .replace('"', "_")
        .replace("<", "_")
        .replace(">", "_")
        .replace("|", "_")
        .replace(" ", "_")
    )


def extract_json_from_text(text: str) -> Optional[dict]:
    """テキストからJSONを抽出してパース"""
    if "```json" in text:
        json_str = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            json_str = parts[1].strip()
        else:
            json_str = text.strip()
    else:
        json_str = text.strip()

    return json.loads(json_str)


def _parse_combined_response(response: str) -> tuple:
    """
    統合プロンプトのレスポンスから raw_text と ocr_data を分離する。
    戻り値: (raw_text, ocr_data) — どちらか欠けたら (None, None)
    """
    # ===RAW_START=== 〜 ===RAW_END=== を抽出
    raw_match = re.search(
        r"===RAW_START===\s*\n(.*?)\n\s*===RAW_END===",
        response,
        re.DOTALL,
    )
    if not raw_match:
        return (None, None)
    raw_text = raw_match.group(1).strip()
    if not raw_text:
        return (None, None)

    # RAWマーカー以降の部分からJSONを抽出
    after_raw = response[raw_match.end():]
    try:
        ocr_data = extract_json_from_text(after_raw)
    except (json.JSONDecodeError, IndexError):
        return (None, None)

    if not isinstance(ocr_data, dict):
        return (None, None)

    return (raw_text, ocr_data)


def make_file_prefix(card_number: str, card_name: str, series: str) -> str:
    """ファイル名プレフィックスを生成"""
    safe_num = sanitize_filename(card_number)
    safe_name = sanitize_filename(card_name)
    series_prefix = ""
    if series:
        series_clean = sanitize_filename(series.replace(":", "_"))
        series_prefix = f"{series_clean}_"
    return f"{series_prefix}{safe_num}_{safe_name}"


# ---------------------------------------------------------------------------
# Card loading
# ---------------------------------------------------------------------------
def load_unique_cards() -> List[Dict]:
    """all_cards_list/ から重複排除したカード一覧を構築"""
    if not ALL_CARDS_DIR.exists():
        logger.error(f"ディレクトリが見つかりません: {ALL_CARDS_DIR}")
        return []

    cards_by_number: Dict[str, Dict] = {}

    for json_file in sorted(ALL_CARDS_DIR.glob("*.json")):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"読み込み失敗: {json_file.name} - {e}")
            continue

        if not isinstance(data, dict):
            continue

        card_number = data.get("number")
        card_name = data.get("name")
        front_url = None
        back_url = None

        back_data = data.get("back") or {}
        front_data = data.get("front") or {}

        if card_number and "image_url" in front_data:
            front_url = front_data.get("image_url")
            back_url = back_data.get("image_url")
        elif "url" in front_data:
            card_number = card_number or front_data.get("number")
            card_name = card_name or front_data.get("name")
            front_url = front_data.get("url")
            back_url = back_data.get("url")
        else:
            match = re.match(r"([A-Za-z0-9_]+-\d+(?:_p\d+)?)", json_file.stem)
            if match:
                card_number = match.group(1)

        if not card_number:
            continue

        if not card_name:
            card_name = json_file.stem.split("_")[-1] if "_" in json_file.stem else json_file.stem

        series = data.get("series", "")

        if card_number not in cards_by_number:
            cards_by_number[card_number] = {
                "card_number": card_number,
                "card_name": card_name,
                "series": series,
                "front_url": front_url,
                "back_url": back_url,
            }

    cards = sorted(cards_by_number.values(), key=lambda c: c["card_number"])
    logger.info(f"ユニークカード数: {len(cards)}")
    return cards


def get_existing_numbers(suffix: str) -> set:
    """ocr_results_debug/ の指定サフィックスのファイルからカード番号セットを返す。
    イラスト違い(_p1等)はベース番号のOCRがあれば処理済みとみなす。"""
    existing = set()
    if not OCR_RESULTS_DIR.exists():
        return existing
    for f in OCR_RESULTS_DIR.iterdir():
        if f.name.endswith(suffix):
            match = re.search(r"([A-Z0-9]+-[A-Z]?\d+(?:_p\d+)?)", f.name)
            if match:
                existing.add(match.group(1))
    # _pバリアントはベース番号のOCRがあれば処理済みとみなす
    if existing and ALL_CARDS_DIR.exists():
        for json_file in ALL_CARDS_DIR.glob("*_p[0-9]*.json"):
            m = re.search(r"([A-Z0-9]+-[A-Z]?\d+_p\d+)", json_file.name)
            if m:
                p_num = m.group(1)
                base_num = re.sub(r'_p\d+$', '', p_num)
                if base_num in existing:
                    existing.add(p_num)
    return existing


def get_existing_ocr_numbers() -> set:
    return get_existing_numbers("_basic.json")


def get_existing_raw_numbers() -> set:
    return get_existing_numbers("_ocr_raw.json")


# ---------------------------------------------------------------------------
# Image download
# ---------------------------------------------------------------------------
def download_image(url: str, card_number: str) -> Optional[Path]:
    """画像をダウンロードしてローカルパスを返す"""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    ext = ".jpg"
    if ".png" in url:
        ext = ".png"
    filepath = IMAGES_DIR / f"{sanitize_filename(card_number)}_b{ext}"

    if filepath.exists() and filepath.stat().st_size > MIN_IMAGE_SIZE:
        logger.debug(f"  画像キャッシュ使用: {filepath.name}")
        return filepath

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        if len(resp.content) < MIN_IMAGE_SIZE:
            logger.warning(f"  画像サイズが小さすぎます ({len(resp.content)} bytes): {url}")
            return None
        with open(filepath, "wb") as f:
            f.write(resp.content)
        logger.debug(f"  画像ダウンロード完了: {filepath.name}")
        return filepath
    except Exception as e:
        logger.error(f"  画像ダウンロード失敗: {url} - {e}")
        return None


# ---------------------------------------------------------------------------
# マスターデータ辞書（Stage2 プロンプト注入用）
# ---------------------------------------------------------------------------
def load_master_names() -> dict:
    """official_master_data.json からリンク名・MSアビリティ名のリストを読み込む"""
    master_path = Path(__file__).parent / "official_master_data.json"
    if not master_path.exists():
        return {"link_names": [], "ms_abilities": []}
    with open(master_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "link_names": data.get("link_names", []),
        "ms_abilities": data.get("ms_abilities", []),
    }


def build_master_dict_section() -> str:
    """プロンプトに追加するマスター辞書テキストを生成"""
    master = load_master_names()
    if not master["link_names"] and not master["ms_abilities"]:
        return ""

    sections = []
    sections.append("## 公式マスター辞書（名前の正規化に使用）")
    sections.append("")
    sections.append("以下は公式データベースに登録されている正式名称のリストです。")
    sections.append("link_ability.name および ms_ability.name は、**必ずこのリストの中から最も近いものを選んで**ください。")
    sections.append("OCR生テキストの表記が多少異なっていても（括弧の種類違い、類似漢字の誤読、プレフィックス欠落等）、正式名称に修正してください。")
    sections.append("")

    if master["link_names"]:
        sections.append("### リンクアビリティ名（正式名称一覧）")
        for name in master["link_names"]:
            sections.append(f"- {name}")
        sections.append("")

    if master["ms_abilities"]:
        sections.append("### MSアビリティ名（正式名称一覧）")
        for name in master["ms_abilities"]:
            sections.append(f"- {name}")
        sections.append("")

    sections.append("### 正規化ルール")
    sections.append("- link_ability.name に [EB]/[SQ]/[AB] プレフィックスは付けない。EBリンクかどうかは is_eb_link フラグで判定する")
    sections.append("- 【】（隅付き括弧）は[]（角括弧）に統一する")
    sections.append("- 半角スラッシュ(/)は全角スラッシュ(／)に統一する")
    sections.append("- リストに完全一致する名称がない場合のみ、OCR生テキストの値をそのまま使用する")
    sections.append("")
    sections.append("### 重要：マスター辞書に存在しないリンクアビリティ名はOCR誤認識の可能性が極めて高い")
    sections.append("- link_ability.name は必ず上記マスターリストに存在する名前を使用すること")
    sections.append("- マスターリストにない名前が出た場合、EB条件テキスト（例:「ECHOES BEAT lv.が前世代以上」）やセクション見出しをリンク名と誤認識している可能性がある")
    sections.append("- EB LINK ABILITYセクションでは、小さい文字で書かれたリンク名（例:「宇宙に響く鼓動」）を正しく読み取り、EB条件テキストとリンク名を混同しないこと")
    sections.append("")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Claude Code CLI call (共通)
# ---------------------------------------------------------------------------
def _run_claude_cli(
    prompt: str,
    model: Optional[str] = None,
    allowed_tools: str = "Read",
) -> Optional[str]:
    """
    claude CLI のパイプモード (-p) を呼び出す共通関数。
    プロンプトは stdin 経由で渡す（Windows コマンドライン長・エンコーディング問題を回避）。
    戻り値: レスポンステキスト、失敗時は None
    """
    # プロンプトは stdin 経由で渡す（-p フラグのみ、値なし）
    cmd = [
        "claude",
        "-p",
        "--output-format", "json",
    ]
    if allowed_tools:
        cmd.extend(["--allowedTools", allowed_tools])
    cmd.append("--no-session-persistence")

    effective_model = model or DEFAULT_OCR_MODEL
    cmd.extend(["--model", effective_model])

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    logger.debug(f"  CLI cmd: {' '.join(cmd[:6])}... (prompt {len(prompt)} chars)")

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
            cwd=str(Path.cwd()),
            env=env,
            encoding="utf-8",
        )

        logger.debug(
            f"  CLI exit={result.returncode}, "
            f"stdout={len(result.stdout or '')}B, "
            f"stderr={len(result.stderr or '')}B"
        )

        if result.returncode != 0:
            logger.error(f"  claude CLI エラー (exit={result.returncode})")
            if result.stderr:
                logger.error(f"  stderr: {result.stderr[:500]}")
            return None

        if not result.stdout:
            logger.error("  claude CLI: 空のレスポンス")
            logger.error(f"  returncode={result.returncode}, stderr={result.stderr[:500] if result.stderr else '(なし)'}")
            return None
        stdout = result.stdout.strip()

        try:
            cli_output = json.loads(stdout)
            if isinstance(cli_output, dict) and "result" in cli_output:
                text = cli_output["result"]
                if text is None:
                    logger.error("  claude CLI: result フィールドが null")
                    return None
                return text
            return stdout
        except json.JSONDecodeError:
            return stdout

    except subprocess.TimeoutExpired:
        logger.error(f"  claude CLI タイムアウト ({SUBPROCESS_TIMEOUT}秒)")
        return None
    except FileNotFoundError:
        logger.error("  claude コマンドが見つかりません。")
        sys.exit(1)
    except Exception as e:
        logger.error(f"  claude CLI 実行エラー: {e}")
        return None


def _call_with_retry(
    prompt: str,
    model: Optional[str] = None,
    allowed_tools: str = "Read",
) -> Optional[str]:
    """リトライ付きで claude CLI を呼び出す"""
    for attempt in range(1, MAX_RETRIES + 1):
        result = _run_claude_cli(prompt, model=model, allowed_tools=allowed_tools)
        if result:
            return result
        if attempt < MAX_RETRIES:
            wait = 2 ** attempt * 3
            logger.warning(f"  リトライ待機 {wait}秒... (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# Stage 1: RAW OCR — 画像から生テキストを抽出
# ---------------------------------------------------------------------------
def stage1_extract_raw(
    card: Dict,
    model: Optional[str] = None,
    force: bool = False,
) -> Optional[str]:
    """
    Stage 1: カード画像から生テキストを抽出し _ocr_raw.json に保存する。
    戻り値: 抽出された生テキスト。失敗時は None。
    """
    card_number = card["card_number"]
    card_name = card["card_name"]
    series = card.get("series", "")
    back_url = card["back_url"]
    front_url = card["front_url"]

    prefix = make_file_prefix(card_number, card_name, series)
    raw_path = OCR_RESULTS_DIR / f"{prefix}_ocr_raw.json"

    # 既存RAWがあり、forceでなければ読み込んで返す
    if raw_path.exists() and not force:
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            raw_text = existing.get("raw_ocr_text", "")
            if raw_text:
                logger.info(f"  [Stage1] 既存RAW使用: {raw_path.name}")
                return raw_text
        except Exception:
            pass

    if not back_url:
        logger.warning(f"  裏面画像URLなし: {card_number} {card_name}")
        return None

    # 画像ダウンロード
    image_path = download_image(back_url, card_number)
    if not image_path:
        return None

    # Claude CLI で生テキスト抽出
    prompt = (
        f"以下の画像ファイルを読み取って、カードに書かれたすべてのテキストを書き起こしてください。\n"
        f"画像ファイルパス: {image_path.resolve()}\n\n"
        f"カード番号: {card_number}\n\n"
        f"{RAW_OCR_PROMPT}"
    )

    raw_text = _call_with_retry(prompt, model=model)
    if not raw_text:
        logger.error(f"  [Stage1] RAWテキスト抽出失敗: {card_number}")
        return None

    # RAW データを保存
    raw_output = {
        "card_number": card_number,
        "card_name": card_name,
        "series": series,
        "front_image_url": front_url,
        "back_image_url": back_url,
        "raw_ocr_text": raw_text,
        "ocr_timestamp": datetime.now().isoformat(),
        "ocr_engine": "claude_code_cli",
    }

    OCR_RESULTS_DIR.mkdir(exist_ok=True)
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_output, f, ensure_ascii=False, indent=2)

    logger.info(f"  [Stage1] RAW保存完了: {raw_path.name}")
    return raw_text


# ---------------------------------------------------------------------------
# Stage 2: Structure — 生テキストから構造化JSONを生成
# ---------------------------------------------------------------------------
def stage2_structure(
    card: Dict,
    raw_text: str,
    model: Optional[str] = None,
    force: bool = False,
) -> bool:
    """
    Stage 2: 生テキストを構造化JSONに変換し _basic.json に保存する。
    戻り値: 成功なら True。
    """
    card_number = card["card_number"]
    card_name = card["card_name"]
    series = card.get("series", "")
    front_url = card.get("front_url", "")
    back_url = card.get("back_url", "")

    prefix = make_file_prefix(card_number, card_name, series)
    basic_path = OCR_RESULTS_DIR / f"{prefix}_basic.json"

    # 既存があり、forceでなければスキップ
    if basic_path.exists() and not force:
        logger.info(f"  [Stage2] 既存スキップ: {basic_path.name}")
        return True

    # Claude CLI でテキストを構造化 (画像不要 → allowed_tools を空に)
    master_section = build_master_dict_section()
    prompt = (
        f"以下はカード番号 {card_number} の裏面OCR生テキストです。\n"
        f"このテキストを解析して構造化JSONを生成してください。\n\n"
        f"--- 生テキスト開始 ---\n"
        f"{raw_text}\n"
        f"--- 生テキスト終了 ---\n\n"
        f"{STRUCTURE_PROMPT}\n\n"
        f"{master_section}"
    )

    response = _call_with_retry(prompt, model=model, allowed_tools="")
    if not response:
        logger.error(f"  [Stage2] 構造化失敗: {card_number}")
        return False

    # JSONパース
    try:
        ocr_data = extract_json_from_text(response)
    except (json.JSONDecodeError, IndexError) as e:
        logger.error(f"  [Stage2] JSONパース失敗: {card_number} - {e}")
        err_path = OCR_RESULTS_DIR / f"{prefix}_structure_error.txt"
        with open(err_path, "w", encoding="utf-8") as f:
            f.write(response)
        logger.info(f"  生レスポンスを保存: {err_path}")
        return False

    # raw フィールドに生テキストを設定
    if isinstance(ocr_data, dict):
        ocr_data["raw"] = raw_text

    # 出力JSON構築（app.py 互換形式）
    output = {
        "card_number": card_number,
        "card_name": card_name,
        "series": series,
        "front_image_url": front_url,
        "back_image_url": back_url,
        "ocr_data": ocr_data,
        "ocr_raw_file": f"{prefix}_ocr_raw.json",
        "ocr_timestamp": datetime.now().isoformat(),
        "ocr_type": "basic",
        "ocr_engine": "claude_code_cli",
    }

    OCR_RESULTS_DIR.mkdir(exist_ok=True)
    with open(basic_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info(f"  [Stage2] 構造化保存完了: {basic_path.name}")

    # 派生ファイル (_sp.json / _sq_analysis.json) を生成
    try:
        from generate_derivatives import generate_derivatives_for_basic
        generate_derivatives_for_basic(str(basic_path))
    except ImportError:
        logger.debug("generate_derivatives.py が見つかりません。派生ファイル生成をスキップ。")
    except Exception as e:
        logger.warning(f"  派生ファイル生成エラー: {e}")

    return True


# ---------------------------------------------------------------------------
# Card image preprocessing — 領域クロップ+拡大で OCR 精度を向上
# ---------------------------------------------------------------------------
PL_CROP_REGIONS = {
    "header":  (0, 0, 300, 50),
    "name":    (0, 50, 400, 115),
    "profile": (0, 115, 350, 250),
    "skill":   (0, 400, 430, 620),
    "link":    (0, 620, 430, 800),
    "stats":   (430, 680, 600, 800),
    "footer":  (0, 830, 600, 875),
}

MS_CROP_REGIONS = {
    "header_name":  (0, 0, 420, 100),       # 近距離/コスト + 型式番号 + 機体名
    "specs_terrain": (0, 100, 600, 200),     # 全高/重量/所属 + 地形適性 + 機動力
    "pilot_stats":  (0, 200, 600, 300),      # パイロット + 遠距離/近距離/HP
    "weapon_link":  (0, 300, 600, 400),      # WEAPON + LINK ABILITY
    "ability_link2": (0, 400, 600, 530),     # MS ABILITY + LINK 2
    "sp_attack":    (0, 530, 430, 800),      # SPECIAL ATTACK / UNITED SP 全体
    "footer":       (0, 830, 600, 875),      # illustrator + カード番号
}

CROP_SCALE = 3  # 3x拡大


def _detect_card_type(image_path: Path) -> str:
    """カード画像の右上領域から MS/PL を判定する。
    MSカードは右上に 'MS' + 機体イラスト、PLカードは 'PL' + 作品ロゴがある。
    ヘッダー左上の分類テキストで判定: 近距離/遠距離/機動 → MS、殲滅/制圧/防衛 → PL。
    """
    try:
        from PIL import Image
        img = Image.open(image_path)
        # 右上の MS/PL マーク領域 (約 550-600, 0-30)
        type_region = img.crop((540, 0, 600, 35))
        # ピクセル平均色で判定: MS マークは青系、PL マークはピンク/紫系
        # より確実に: 左上の分類テキスト領域をチェック
        header_region = img.crop((0, 0, 200, 35))
        pixels = list(header_region.getdata())
        # 殲滅/制圧/防衛 の背景は赤系、近距離/遠距離/機動 の背景は青/緑系
        avg_r = sum(p[0] for p in pixels) / len(pixels)
        avg_g = sum(p[1] for p in pixels) / len(pixels)
        avg_b = sum(p[2] for p in pixels) / len(pixels)
        # PLカードのヘッダーは赤背景（殲滅=赤、制圧=青、防衛=緑）
        # MSカードのヘッダーは青/緑背景（近距離=青、遠距離=緑、機動=黄）
        # より確実: 右上に "MS" テキストがあるか "PL" テキストがあるか
        # 簡易判定: 右上領域の色で判定
        type_pixels = list(type_region.getdata())
        type_avg_r = sum(p[0] for p in type_pixels) / len(type_pixels)
        type_avg_b = sum(p[2] for p in type_pixels) / len(type_pixels)
        # MS マークは濃い青/緑背景、PL マークは暗い背景にピンク文字
        # 実際にはテキスト認識が必要だが、画像サイズ600x875のカードでは
        # 右上 y=5付近に "MS" or "PL" の白文字がある
        # 別のアプローチ: WEAPON セクションの有無で判定（y=300-350 左側にWEAPON表記）
        weapon_region = img.crop((0, 300, 200, 350))
        weapon_pixels = list(weapon_region.getdata())
        # WEAPON見出しは明るい水色背景
        weapon_brightness = sum(sum(p[:3]) for p in weapon_pixels) / len(weapon_pixels) / 3
        if weapon_brightness > 80:  # WEAPONセクションが明るい = MSカード
            return "MS"
        return "PL"
    except Exception as e:
        logger.debug(f"  カードタイプ判定失敗、デフォルトPL: {e}")
        return "PL"


def _create_crop_composite(image_path: Path, card_type: str = "PL") -> Optional[Path]:
    """カード画像を領域ごとにクロップ・拡大し、ラベル付きコンポジット画像を生成する"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("  Pillow が必要です。pip install Pillow を実行してください。")
        return None

    try:
        img = Image.open(image_path)
    except Exception as e:
        logger.error(f"  画像読み込み失敗: {image_path} - {e}")
        return None

    regions = PL_CROP_REGIONS if card_type == "PL" else MS_CROP_REGIONS

    # 各領域をクロップ・拡大
    crops = []
    label_height = 30
    for name, box in regions.items():
        crop = img.crop(box)
        crop = crop.resize((crop.width * CROP_SCALE, crop.height * CROP_SCALE), Image.LANCZOS)
        crops.append((name, crop))

    # コンポジット画像の幅・高さを計算
    max_w = max(c.width for _, c in crops)
    total_h = sum(c.height + label_height for _, c in crops) + 10
    composite = Image.new("RGB", (max_w, total_h), (30, 30, 30))
    draw = ImageDraw.Draw(composite)

    y = 0
    for name, crop in crops:
        # ラベル描画
        draw.rectangle([(0, y), (max_w, y + label_height)], fill=(80, 80, 80))
        draw.text((10, y + 5), f"[{name.upper()}]", fill=(102, 242, 197))
        y += label_height
        # クロップ画像貼り付け
        composite.paste(crop, (0, y))
        y += crop.height

    # 保存
    composite_path = image_path.parent / f"{image_path.stem}_composite.jpg"
    composite.save(composite_path, quality=95)
    logger.debug(f"  コンポジット画像生成: {composite_path.name} ({max_w}x{total_h})")
    return composite_path


# ---------------------------------------------------------------------------
# Combined processing
# ---------------------------------------------------------------------------
def _process_card_combined(
    card: Dict,
    model: Optional[str] = None,
    force: bool = False,
) -> bool:
    """
    統合版: 1回のCLI呼び出しで画像→生テキスト＋構造化JSONを同時に取得する。
    """
    card_number = card["card_number"]
    card_name = card["card_name"]
    series = card.get("series", "")
    back_url = card.get("back_url", "")
    front_url = card.get("front_url", "")

    prefix = make_file_prefix(card_number, card_name, series)
    basic_path = OCR_RESULTS_DIR / f"{prefix}_basic.json"
    raw_path = OCR_RESULTS_DIR / f"{prefix}_ocr_raw.json"

    # 既存 _basic.json あり & force=False → スキップ
    if basic_path.exists() and not force:
        logger.info(f"  [Combined] 既存スキップ: {basic_path.name}")
        return True

    if not back_url:
        logger.warning(f"  裏面画像URLなし: {card_number} {card_name}")
        return False

    # 画像ダウンロード
    image_path = download_image(back_url, card_number)
    if not image_path:
        return False

    # カードタイプを推定（PLかMSか）— 画像右上の MS/PL マークで判定
    card_type = _detect_card_type(image_path)

    # コンポジット画像を生成（領域クロップ+3x拡大）
    composite_path = _create_crop_composite(image_path, card_type)
    ocr_image = composite_path if composite_path else image_path

    # 構造化抽出プロンプトでOCR
    master_section = build_master_dict_section()
    prompt = (
        f"画像ファイル {ocr_image.resolve()} を Read ツールで読み取ってください。\n"
        f"この画像はカード裏面を領域ごとにクロップ・拡大したものです。各セクションは [HEADER], [NAME], [SKILL], [LINK], [STATS] 等のラベルで区切られています。\n\n"
        f"カード番号: {card_number}\n\n"
        f"{OCR_PROMPT_DIRECT}\n\n"
        f"{master_section}"
    )

    response = _call_with_retry(prompt, model=model, allowed_tools="Read")
    if not response:
        logger.error(f"  [Combined] CLI呼び出し失敗: {card_number}")
        return False

    # JSONパース
    try:
        ocr_data = extract_json_from_text(response)
    except (json.JSONDecodeError, IndexError) as e:
        logger.error(f"  [Combined] JSONパース失敗: {card_number} - {e}")
        err_path = OCR_RESULTS_DIR / f"{prefix}_combined_error.txt"
        OCR_RESULTS_DIR.mkdir(exist_ok=True)
        with open(err_path, "w", encoding="utf-8") as f:
            f.write(response)
        logger.info(f"  生レスポンスを保存: {err_path}")
        return False

    raw_text = ocr_data.get("raw", "")

    OCR_RESULTS_DIR.mkdir(exist_ok=True)

    # _ocr_raw.json に保存（従来Stage1と同じ形式）
    raw_output = {
        "card_number": card_number,
        "card_name": card_name,
        "series": series,
        "front_image_url": front_url,
        "back_image_url": back_url,
        "raw_ocr_text": raw_text,
        "ocr_timestamp": datetime.now().isoformat(),
        "ocr_engine": "claude_code_cli_combined",
    }
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_output, f, ensure_ascii=False, indent=2)
    logger.info(f"  [Combined] RAW保存完了: {raw_path.name}")

    # ocr_data に raw テキストを設定
    ocr_data["raw"] = raw_text

    # _basic.json に保存（従来Stage2と同じ形式）
    output = {
        "card_number": card_number,
        "card_name": card_name,
        "series": series,
        "front_image_url": front_url,
        "back_image_url": back_url,
        "ocr_data": ocr_data,
        "ocr_raw_file": f"{prefix}_ocr_raw.json",
        "ocr_timestamp": datetime.now().isoformat(),
        "ocr_type": "basic",
        "ocr_engine": "claude_code_cli_combined",
    }
    with open(basic_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info(f"  [Combined] 構造化保存完了: {basic_path.name}")

    # 派生ファイル生成
    try:
        from generate_derivatives import generate_derivatives_for_basic
        generate_derivatives_for_basic(str(basic_path))
    except ImportError:
        logger.debug("generate_derivatives.py が見つかりません。派生ファイル生成をスキップ。")
    except Exception as e:
        logger.warning(f"  派生ファイル生成エラー: {e}")

    return True


def process_card(
    card: Dict,
    model: Optional[str] = None,
    force: bool = False,
    stage: str = "both",
) -> bool:
    """
    カード1枚を処理する。
    stage: "raw" = Stage1のみ, "structure" = Stage2のみ, "both" = 両方(統合版)
    """
    card_number = card["card_number"]

    # 統合版: 1回のCLI呼び出しで完結
    if stage == "both":
        return _process_card_combined(card, model=model, force=force)

    # Stage 1 のみ
    if stage == "raw":
        raw_text = stage1_extract_raw(card, model=model, force=force)
        return raw_text is not None

    # Stage 2 のみ
    if stage == "structure":
        raw_text = load_raw_text(card)
        if raw_text is None:
            logger.error(f"  [Stage2] RAWデータなし: {card_number} (先に --stage raw を実行)")
            return False
        return stage2_structure(card, raw_text, model=model, force=force)

    return True


def load_raw_text(card: Dict) -> Optional[str]:
    """既存の _ocr_raw.json からテキストを読み込む"""
    card_number = card["card_number"]
    card_name = card["card_name"]
    series = card.get("series", "")
    prefix = make_file_prefix(card_number, card_name, series)
    raw_path = OCR_RESULTS_DIR / f"{prefix}_ocr_raw.json"

    if not raw_path.exists():
        return None

    try:
        with open(raw_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("raw_ocr_text")
    except Exception as e:
        logger.warning(f"  RAWファイル読み込みエラー: {raw_path.name} - {e}")
        return None


# ---------------------------------------------------------------------------
# Restructure — 既存RAWから一括再構造化
# ---------------------------------------------------------------------------
def restructure_all(
    all_cards: List[Dict],
    model: Optional[str] = None,
    series_filter: str = "",
    limit: int = 0,
    delay: float = DEFAULT_DELAY,
    force: bool = True,
):
    """既存の _ocr_raw.json をすべて読み込み、Stage 2 を再実行する"""
    existing_raw = get_existing_raw_numbers()
    logger.info(f"既存RAWデータ: {len(existing_raw)} 件")

    # カード情報とRAWのマッチング
    cards_by_number = {c["card_number"]: c for c in all_cards}
    targets = []
    for num in sorted(existing_raw):
        if series_filter and not num.upper().startswith(series_filter.upper()):
            continue
        if num in cards_by_number:
            targets.append(cards_by_number[num])

    if limit > 0:
        targets = targets[:limit]

    if not targets:
        logger.info("再構造化の対象がありません。")
        return

    total = len(targets)
    success_count = 0
    fail_count = 0
    start_time = time.time()

    print(f"\n{'='*60}")
    print(f" 再構造化開始: {total} 件 (RAW → 構造化JSON)")
    print(f"{'='*60}\n")

    for i, card in enumerate(targets, 1):
        num = card["card_number"]
        raw_text = load_raw_text(card)
        if not raw_text:
            logger.error(f"  RAWテキスト読み込み失敗: {num}")
            fail_count += 1
            continue

        ok = stage2_structure(card, raw_text, model=model, force=force)
        if ok:
            success_count += 1
        else:
            fail_count += 1

        elapsed = time.time() - start_time
        eta = elapsed / i * (total - i) if i else 0
        eta_str = time.strftime("%H:%M:%S", time.gmtime(eta))
        logger.info(f"[{i}/{total}] {num} {card['card_name']}  {'OK' if ok else 'FAIL'}  (ETA: {eta_str})")

        if delay > 0:
            time.sleep(delay)

    total_time = time.time() - start_time
    print(f"\n{'='*60}")
    print(f" 再構造化完了")
    print(f"{'='*60}")
    print(f"成功: {success_count}  失敗: {fail_count}  合計: {total}")
    print(f"所要時間: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
    print()


# ---------------------------------------------------------------------------
# Progress management
# ---------------------------------------------------------------------------
def load_progress() -> Dict:
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "processed": [],
        "failed": [],
        "skipped": [],
        "start_time": None,
        "last_update": None,
    }


def save_progress(progress: Dict):
    progress["last_update"] = datetime.now().isoformat()
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------
def show_status():
    progress = load_progress()
    all_cards = load_unique_cards()
    existing_basic = get_existing_ocr_numbers()
    existing_raw = get_existing_raw_numbers()

    print(f"\n{'='*55}")
    print(f" カードOCR進捗状況 (Claude Code CLI — 2段階パイプライン)")
    print(f"{'='*55}")
    print(f"ユニークカード総数:            {len(all_cards)}")
    print(f"Stage1 RAW済み (_ocr_raw.json): {len(existing_raw)}")
    print(f"Stage2 構造化済み (_basic.json): {len(existing_basic)}")
    print(f"RAWのみ（未構造化）:            {len(existing_raw - existing_basic)}")
    print(f"完全未処理:                     {len(all_cards) - len(existing_raw | existing_basic)}")
    print(f"進捗ファイル処理済み:           {len(progress.get('processed', []))}")
    print(f"進捗ファイル失敗:               {len(progress.get('failed', []))}")
    print(f"最終更新:                       {progress.get('last_update', 'N/A')}")

    # シリーズ別集計
    series_count: Dict[str, int] = {}
    series_prefix_map: Dict[str, str] = {}
    for card in all_cards:
        s = card.get("series", "不明")
        series_count[s] = series_count.get(s, 0) + 1
        if s not in series_prefix_map:
            series_prefix_map[s] = card["card_number"].split("-")[0]

    raw_by_prefix: Dict[str, int] = {}
    for num in existing_raw:
        p = num.split("-")[0]
        raw_by_prefix[p] = raw_by_prefix.get(p, 0) + 1

    basic_by_prefix: Dict[str, int] = {}
    for num in existing_basic:
        p = num.split("-")[0]
        basic_by_prefix[p] = basic_by_prefix.get(p, 0) + 1

    print(f"\n--- シリーズ別 OCR 状況 ---")
    print(f"  {'シリーズ':30s}  {'RAW':>5s}  {'構造化':>5s}  {'総数':>5s}")
    print(f"  {'-'*30}  {'-'*5}  {'-'*5}  {'-'*5}")
    for s_name, total in sorted(series_count.items()):
        prefix = series_prefix_map.get(s_name, "?")
        raw_done = raw_by_prefix.get(prefix, 0)
        basic_done = basic_by_prefix.get(prefix, 0)
        print(f"  {s_name:30s}  {raw_done:5d}  {basic_done:5d}  {total:5d}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Claude Code CLI (定額プラン) — カードOCR 2段階パイプライン"
    )
    parser.add_argument("--status", action="store_true", help="進捗表示のみ")
    parser.add_argument("--dry-run", action="store_true", help="対象一覧を表示（OCR実行なし）")
    parser.add_argument("--limit", type=int, default=0, help="処理する最大件数")
    parser.add_argument("--series", type=str, default="", help="シリーズ絞り込み (例: AB01)")
    parser.add_argument("--force", action="store_true", help="既存結果を上書き")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"呼び出し間隔(秒) [default: {DEFAULT_DELAY}]")
    parser.add_argument("--model", type=str, default="",
                        help="使用するモデル (例: sonnet, haiku, opus)")
    parser.add_argument("--verbose", action="store_true", help="詳細ログ")
    parser.add_argument("--clean-images", action="store_true",
                        help="処理後にダウンロード画像を削除")
    parser.add_argument("--stage", type=str, default="both",
                        choices=["raw", "structure", "both"],
                        help="実行ステージ: raw=Stage1のみ, structure=Stage2のみ, both=両方 [default: both]")
    parser.add_argument("--restructure", action="store_true",
                        help="既存RAWデータから構造化を再実行（データ構造変更時に使用）")
    args = parser.parse_args()

    global logger
    logger = setup_logging(args.verbose)

    # --- status mode ---
    if args.status:
        show_status()
        return

    # --- load cards ---
    all_cards = load_unique_cards()

    # --- restructure mode ---
    if args.restructure:
        model = args.model if args.model else None
        restructure_all(
            all_cards,
            model=model,
            series_filter=args.series,
            limit=args.limit,
            delay=args.delay,
            force=True,  # restructure は常に上書き
        )
        return

    # --- 通常モード: フィルタリング ---
    if args.stage == "structure":
        # Stage2 のみ: RAW が存在するものを対象
        existing_raw = get_existing_raw_numbers()
        existing_basic = get_existing_ocr_numbers()
        targets = []
        for card in all_cards:
            num = card["card_number"]
            if args.series and not num.upper().startswith(args.series.upper()):
                continue
            if num not in existing_raw:
                continue
            if not args.force and num in existing_basic:
                continue
            targets.append(card)
    else:
        # Stage1 (raw) or both: RAW がないものを対象
        if args.stage == "raw":
            existing = get_existing_raw_numbers()
        else:
            existing = get_existing_ocr_numbers()
        targets = []
        for card in all_cards:
            num = card["card_number"]
            if args.series and not num.upper().startswith(args.series.upper()):
                continue
            if not args.force and num in existing:
                continue
            if not card["back_url"]:
                continue
            targets.append(card)

    logger.info(f"処理対象: {len(targets)} 件")

    if args.limit > 0:
        targets = targets[: args.limit]
        logger.info(f"--limit {args.limit} 適用 → {len(targets)} 件")

    # --- dry-run mode ---
    if args.dry_run:
        stage_label = {"raw": "Stage1(RAW)", "structure": "Stage2(構造化)", "both": "Stage1+2"}
        print(f"\n=== ドライラン [{stage_label[args.stage]}]: 対象 {len(targets)} 件 ===\n")
        for i, card in enumerate(targets, 1):
            print(f"  {i:4d}. {card['card_number']:12s}  {card['card_name']}")
        return

    if not targets:
        logger.info("処理対象カードがありません。")
        return

    # --- claude CLI 確認 ---
    try:
        ver = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if ver.returncode != 0:
            logger.error("claude CLI が正常に動作しません。")
            sys.exit(1)
        logger.info(f"Claude Code CLI: {ver.stdout.strip()}")
    except FileNotFoundError:
        logger.error("claude コマンドが見つかりません。Claude Code をインストールしてください。")
        sys.exit(1)

    # --- process ---
    progress = load_progress()
    if progress["start_time"] is None:
        progress["start_time"] = datetime.now().isoformat()

    processed_set = set(progress.get("processed", []))
    failed_set = set(progress.get("failed", []))

    success_count = 0
    fail_count = 0
    skip_count = 0
    total = len(targets)

    model = args.model if args.model else None

    stage_label = {"raw": "Stage1(RAW)", "structure": "Stage2(構造化)", "both": "Stage1+2(RAW→構造化)"}
    print(f"\n{'='*60}")
    print(f" OCR開始: {total} 件 | {stage_label[args.stage]}")
    print(f" delay={args.delay}秒 | model={model or 'default'}")
    print(f"{'='*60}\n")

    start_time = time.time()
    done_count = 0

    for card in targets:
        num = card["card_number"]

        if num in processed_set and not args.force:
            logger.debug(f"進捗ファイルで処理済み: {num}")
            skip_count += 1
            continue

        try:
            ok = process_card(card, model=model, force=args.force, stage=args.stage)
        except Exception as e:
            logger.error(f"処理エラー: {num} - {e}")
            ok = False

        done_count += 1
        if ok:
            success_count += 1
            processed_set.add(num)
            failed_set.discard(num)
        else:
            fail_count += 1
            failed_set.add(num)

        elapsed = time.time() - start_time
        eta = elapsed / done_count * (total - done_count) if done_count else 0
        eta_str = time.strftime("%H:%M:%S", time.gmtime(eta))
        logger.info(f"[{done_count}/{total}] {num} {card['card_name']}  {'OK' if ok else 'FAIL'}  (ETA: {eta_str})")

        if done_count % 10 == 0 or done_count == total:
            progress["processed"] = sorted(processed_set)
            progress["failed"] = sorted(failed_set)
            save_progress(progress)

        if args.delay > 0:
            time.sleep(args.delay)

    # 最終保存
    progress["processed"] = sorted(processed_set)
    progress["failed"] = sorted(failed_set)
    save_progress(progress)

    # ダウンロード画像の削除
    if args.clean_images and IMAGES_DIR.exists():
        import shutil
        shutil.rmtree(IMAGES_DIR)
        logger.info(f"画像ディレクトリを削除: {IMAGES_DIR}")

    total_time = time.time() - start_time
    print(f"\n{'='*60}")
    print(f" OCR完了 [{stage_label[args.stage]}]")
    print(f"{'='*60}")
    print(f"成功: {success_count}  失敗: {fail_count}  スキップ: {skip_count}")
    print(f"所要時間: {time.strftime('%H:%M:%S', time.gmtime(total_time))}")
    print(f"進捗ファイル: {PROGRESS_FILE}")
    print()


if __name__ == "__main__":
    main()
