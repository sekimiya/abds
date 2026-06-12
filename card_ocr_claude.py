#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
card_ocr_claude.py — Anthropic API (Claude Vision) を使ったカードOCRバッチ処理スクリプト

アーセナルベースのカード裏面画像をClaude Visionで解析し、
構造化データ(JSON)として ocr_results_debug/ に保存する。

Usage:
  python card_ocr_claude.py --force                # 全カードをOCR（既存上書き）
  python card_ocr_claude.py --status               # 進捗表示
  python card_ocr_claude.py --dry-run              # 対象一覧だけ表示
  python card_ocr_claude.py --limit 10             # 最大10件
  python card_ocr_claude.py --series AB01          # シリーズ絞り込み
  python card_ocr_claude.py --delay 2              # API間隔(秒)
"""

import os
import sys
import json
import re
import time
import base64
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from schema import canonicalize_ocr_data

try:
    import anthropic
except ImportError:
    print("Error: anthropic パッケージが必要です。 pip install anthropic を実行してください。")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALL_CARDS_DIR = Path("all_cards_list")
OCR_RESULTS_DIR = Path("ocr_results_debug")
PROGRESS_FILE = Path("ocr_claude_progress.json")
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_DELAY = 1.0
DEFAULT_BATCH_SIZE = 10
MAX_RETRIES = 3

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
# OCR Prompt — カード画像から全フィールドを抽出するプロンプト
# ---------------------------------------------------------------------------
OCR_PROMPT = """カードゲーム「ガンダム アーセナルベース」のカード裏面画像です。
カードは「MS（モビルスーツ）」と「PL（パイロット）」の2種類があります。
画像の全情報を正確に読み取り、以下のJSON形式で出力してください。

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
  "link_ability": [ { "name": "機動戦士ガンダム", "condition": "デッキに3枚以上", "effect": "[機動力]小アップ", "is_eb_link": false, "is_sq_link": false, "is_ab_link": false } ],
  "special_attack": { "name": "ビーム・サーベル強撃", "target": "単体(敵)", "range": 2, "sp_cost": 2, "power": 3400, "description": "敵単体に格闘攻撃でダメージを与える。", "echoes_beat": null, "united_sp": null },
  "rarity": "M", "illustrator": "toriyufu",
  "raw": "（カード上の全テキストをそのまま記録）"
}
```
UNITED SP がある場合（FQ/UT系）: special_attack.united_sp = { "partner1", "partner2", "range", "power", "description" }。連携相手が「ー」なら null。

### ECHOES BEAT がある場合（VE系等）
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
  "link_ability": [ { "name": "機動戦士ガンダム", "condition": "デッキに3枚以上", "effect": "[機動力]小アップ", "is_eb_link": false, "is_sq_link": false, "is_ab_link": false } ],
  "rarity": "M", "illustrator": null,
  "raw": "（カード上の全テキストをそのまま記録）"
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
- raw にはカード上の全テキストをプレーンテキストで記録
- rarity はカード番号の右に印字された記号のみ（C, U, R, M, P, PR, A, LX, VE, SN, LE 等。1〜2文字。AR弾は「A」、LXR弾は「LX」、VEパラレルの一部は「VE」「SN」）
- カード番号の左に大きく書かれた「SECRET」「PARALLEL」はバナー表記でありレアリティではない。rarity に入れないこと（その場合も番号右の記号を読む）
- link_ability の各要素には is_eb_link, is_sq_link（[SQ]表記またはeffectにSQゲージ）, is_ab_link（AB LINK表記）のboolフラグを必ず含める
- ms_ability は1カードにつき1つ（オブジェクト）。link_ability は1カードにつき通常2つ（配列）。生テキスト上のセクション見出し位置ではなく内容形式で分類すること。ms_ability は発動条件（任意発動等）・対象・射程・コストを持つ戦闘アビリティ。link_ability はデッキ条件とバフ効果を持つ。セクション内に混在している場合も内容に基づいて正しいフィールドに振り分けること
- 出力は ```json ``` で囲み、JSON以外のテキストは出力しない
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


def read_api_key(file_path: str) -> str:
    with open(file_path, "r") as f:
        return f.read().strip()


def extract_json_from_text(text: str) -> Optional[dict]:
    """APIレスポンスのテキストからJSONを抽出してパース"""
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
            logger.debug(f"スキップ (非dict): {json_file.name}")
            continue

        card_number = data.get("number")
        card_name = data.get("name")
        front_url = None
        back_url = None

        back_data = data.get("back") or {}
        front_data = data.get("front") or {}

        if card_number and "image_url" in front_data:
            # Format B: number, front.image_url, back.image_url
            front_url = front_data.get("image_url")
            back_url = back_data.get("image_url")
        elif "url" in front_data:
            # Format A: front.url, back.url
            card_number = card_number or front_data.get("number")
            card_name = card_name or front_data.get("name")
            front_url = front_data.get("url")
            back_url = back_data.get("url")
        else:
            match = re.match(r"([A-Za-z0-9_]+-\d+(?:_p\d+)?)", json_file.stem)
            if match:
                card_number = match.group(1)

        if not card_number:
            logger.debug(f"カード番号不明: {json_file.name}")
            continue

        if not card_name:
            card_name = json_file.stem.split("_")[-1] if "_" in json_file.stem else json_file.stem

        if card_number not in cards_by_number:
            cards_by_number[card_number] = {
                "card_number": card_number,
                "card_name": card_name,
                "front_url": front_url,
                "back_url": back_url,
            }

    cards = sorted(cards_by_number.values(), key=lambda c: c["card_number"])
    logger.info(f"ユニークカード数: {len(cards)}")
    return cards


def get_existing_ocr_numbers() -> set:
    """ocr_results_debug/ の既存 _basic.json からカード番号セットを返す"""
    existing = set()
    if not OCR_RESULTS_DIR.exists():
        return existing
    for f in OCR_RESULTS_DIR.iterdir():
        if f.name.endswith("_basic.json"):
            match = re.search(r"([A-Z0-9]+-[A-Z]?\d+(?:_p\d+)?)", f.name)
            if match:
                existing.add(match.group(1))
    return existing


# ---------------------------------------------------------------------------
# Image download
# ---------------------------------------------------------------------------
def download_image_as_base64(url: str) -> Tuple[Optional[str], Optional[str]]:
    """画像URLをダウンロードしてbase64エンコード。(base64_data, media_type) を返す"""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        # 画像が極端に小さい場合（ダミー画像等）はスキップ
        if len(resp.content) < 1000:
            logger.warning(f"  画像サイズが小さすぎます ({len(resp.content)} bytes): {url}")
            return None, None
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        if "png" in content_type:
            media_type = "image/png"
        elif "webp" in content_type:
            media_type = "image/webp"
        elif "gif" in content_type:
            media_type = "image/gif"
        else:
            media_type = "image/jpeg"
        b64 = base64.b64encode(resp.content).decode("utf-8")
        return b64, media_type
    except Exception as e:
        logger.error(f"画像ダウンロード失敗: {url} - {e}")
        return None, None


# ---------------------------------------------------------------------------
# Anthropic API call
# ---------------------------------------------------------------------------
def call_claude_ocr(
    client: anthropic.Anthropic,
    image_base64: str,
    media_type: str,
    model: str = DEFAULT_MODEL,
) -> str:
    """Claude Vision APIを呼び出してOCRテキストを取得"""
    message = client.messages.create(
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": OCR_PROMPT,
                    },
                ],
            }
        ],
    )
    return "".join(block.text for block in message.content if block.type == "text")


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
# Core processing
# ---------------------------------------------------------------------------
def process_card(
    client: anthropic.Anthropic,
    card: Dict,
    model: str,
    force: bool = False,
) -> bool:
    """1枚のカードをOCR処理して保存する。成功ならTrue"""
    card_number = card["card_number"]
    card_name = card["card_name"]
    back_url = card["back_url"]
    front_url = card["front_url"]

    if not back_url:
        logger.warning(f"  裏面画像URLなし: {card_number} {card_name}")
        return False

    # 画像ダウンロード
    image_b64, media_type = download_image_as_base64(back_url)
    if not image_b64:
        return False

    # API呼び出し（リトライ付き）
    raw_response = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw_response = call_claude_ocr(client, image_b64, media_type, model)
            break
        except anthropic.RateLimitError:
            wait = 2 ** attempt * 5
            logger.warning(f"  レート制限。{wait}秒待機... (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
        except Exception as e:
            wait = 2 ** attempt
            logger.error(f"  API呼び出しエラー (attempt {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(wait)

    if raw_response is None:
        logger.error(f"  API呼び出し全リトライ失敗: {card_number}")
        return False

    # JSONパース
    try:
        ocr_data = extract_json_from_text(raw_response)
    except (json.JSONDecodeError, IndexError) as e:
        logger.error(f"  JSONパース失敗: {card_number} - {e}")
        safe_num = sanitize_filename(card_number)
        safe_name = sanitize_filename(card_name)
        err_path = OCR_RESULTS_DIR / f"{safe_num}_{safe_name}_error.txt"
        with open(err_path, "w", encoding="utf-8") as f:
            f.write(raw_response)
        logger.info(f"  生レスポンスを保存: {err_path}")
        return False

    # カノニカル形式に変換
    if isinstance(ocr_data, dict):
        ocr_data = canonicalize_ocr_data(ocr_data, card_name)

    # 出力JSON構築（app.py互換形式）
    output = {
        "card_number": card_number,
        "card_name": card_name,
        "series": card.get("series", ""),
        "front_image_url": front_url,
        "back_image_url": back_url,
        "ocr_data": ocr_data,
        "ocr_timestamp": datetime.now().isoformat(),
        "ocr_type": "basic",
        "ocr_engine": "claude_api_direct",
    }

    # ファイル保存
    safe_num = sanitize_filename(card_number)
    safe_name = sanitize_filename(card_name)
    out_path = OCR_RESULTS_DIR / f"{safe_num}_{safe_name}_basic.json"

    OCR_RESULTS_DIR.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info(f"  保存完了: {out_path.name}")

    # 派生ファイル (_sp.json / _sq_analysis.json) を生成
    try:
        from generate_derivatives import generate_derivatives_for_basic
        generate_derivatives_for_basic(str(out_path))
    except ImportError:
        logger.debug("generate_derivatives.py が見つかりません。派生ファイル生成をスキップ。")
    except Exception as e:
        logger.warning(f"  派生ファイル生成エラー: {e}")

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Anthropic Claude Vision を使ったカードOCRバッチ処理"
    )
    parser.add_argument("--status", action="store_true", help="進捗表示のみ")
    parser.add_argument("--dry-run", action="store_true", help="対象一覧を表示（API呼び出しなし）")
    parser.add_argument("--limit", type=int, default=0, help="処理する最大件数")
    parser.add_argument("--series", type=str, default="", help="シリーズ絞り込み (例: AB01)")
    parser.add_argument("--force", action="store_true", help="既存結果を上書き")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="バッチサイズ（ログ用）")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="API呼び出し間隔(秒)")
    parser.add_argument("--api-key-file", type=str, default="", help="Anthropic APIキーファイル")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="使用するモデル")
    parser.add_argument("--verbose", action="store_true", help="詳細ログ")
    parser.add_argument("--cards", type=str, default="", help="カード番号をカンマ区切りで指定 (例: VE01-004,VE01-008)")
    args = parser.parse_args()

    global logger
    logger = setup_logging(args.verbose)

    # --- status mode ---
    if args.status:
        progress = load_progress()
        all_cards = load_unique_cards()
        existing = get_existing_ocr_numbers()
        print(f"ユニークカード総数:    {len(all_cards)}")
        print(f"OCR済み (_basic.json): {len(existing)}")
        print(f"未処理:                {len(all_cards) - len(existing)}")
        print(f"進捗ファイル処理済み:  {len(progress.get('processed', []))}")
        print(f"進捗ファイル失敗:      {len(progress.get('failed', []))}")
        print(f"進捗ファイルスキップ:  {len(progress.get('skipped', []))}")
        print(f"最終更新:              {progress.get('last_update', 'N/A')}")
        return

    # --- load cards ---
    all_cards = load_unique_cards()
    existing = get_existing_ocr_numbers()

    # フィルタリング
    card_number_set = set()
    if args.cards:
        card_number_set = {c.strip() for c in args.cards.split(",") if c.strip()}

    targets = []
    for card in all_cards:
        num = card["card_number"]
        if card_number_set:
            if num not in card_number_set:
                continue
        elif args.series and not num.startswith(args.series):
            continue
        if not args.force and num in existing:
            continue
        if not card["back_url"]:
            continue
        targets.append(card)

    logger.info(f"処理対象: {len(targets)} 件 (既存OCR: {len(existing)} 件)")

    if args.limit > 0:
        targets = targets[: args.limit]
        logger.info(f"--limit {args.limit} 適用 → {len(targets)} 件")

    # --- dry-run mode ---
    if args.dry_run:
        print(f"\n=== ドライラン: 対象 {len(targets)} 件 ===\n")
        for i, card in enumerate(targets, 1):
            print(f"  {i:4d}. {card['card_number']}  {card['card_name']}")
        return

    if not targets:
        logger.info("処理対象カードがありません。")
        return

    # --- API key ---
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if args.api_key_file:
        api_key = read_api_key(args.api_key_file)
    if not api_key:
        logger.error("APIキーが設定されていません。環境変数 ANTHROPIC_API_KEY または --api-key-file を指定してください。")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # --- process ---
    progress = load_progress()
    if progress["start_time"] is None:
        progress["start_time"] = datetime.now().isoformat()

    processed_set = set(progress.get("processed", []))
    failed_set = set(progress.get("failed", []))

    success_count = 0
    fail_count = 0
    total = len(targets)

    for i, card in enumerate(targets, 1):
        num = card["card_number"]
        if num in processed_set and not args.force:
            logger.debug(f"進捗ファイルで処理済み: {num}")
            continue

        logger.info(f"[{i}/{total}] {num} {card['card_name']}")

        ok = process_card(client, card, model=args.model, force=args.force)

        if ok:
            success_count += 1
            processed_set.add(num)
            if num in failed_set:
                failed_set.discard(num)
        else:
            fail_count += 1
            failed_set.add(num)

        # 進捗を定期保存
        if i % args.batch_size == 0 or i == total:
            progress["processed"] = sorted(processed_set)
            progress["failed"] = sorted(failed_set)
            save_progress(progress)

        # API間隔
        if i < total:
            time.sleep(args.delay)

    # 最終保存
    progress["processed"] = sorted(processed_set)
    progress["failed"] = sorted(failed_set)
    save_progress(progress)

    logger.info(f"\n=== 完了 ===")
    logger.info(f"成功: {success_count}  失敗: {fail_count}  合計: {total}")


if __name__ == "__main__":
    main()
