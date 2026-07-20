#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_card_images.py — カード画像をローカルキャッシュにダウンロード

既存の card_ocr_cc.load_unique_cards() を使用してカード一覧を取得し、
公式サイトから画像をダウンロードして card_images/ に保存する。

Usage:
  python download_card_images.py              # 全カード画像をダウンロード
  python download_card_images.py --series AB01  # 特定シリーズのみ
  python download_card_images.py --front-only   # 表面のみ
"""

import argparse
import time
from pathlib import Path

import requests

from card_ocr_cc import load_unique_cards, setup_logging

CARD_IMAGES_DIR = Path("card_images")
MIN_IMAGE_SIZE = 1000   # ダミー画像判定用の最小バイト数
DEFAULT_DELAY = 0.3     # リクエスト間ディレイ（秒）


def download_image(url: str, filepath: Path, logger) -> str:
    """画像を1枚ダウンロード。結果文字列を返す。"""
    if filepath.exists() and filepath.stat().st_size > MIN_IMAGE_SIZE:
        return "cached"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        if len(resp.content) < MIN_IMAGE_SIZE:
            return "too_small"
        filepath.write_bytes(resp.content)
        return "downloaded"
    except Exception as e:
        logger.warning(f"  DL失敗: {url} - {e}")
        return "error"


def main():
    parser = argparse.ArgumentParser(description="カード画像をローカルにダウンロード")
    parser.add_argument("--series", help="対象シリーズ (例: AB01)")
    parser.add_argument("--front-only", action="store_true", help="表面画像のみダウンロード")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="リクエスト間ディレイ秒")
    args = parser.parse_args()

    logger = setup_logging()
    CARD_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    cards = load_unique_cards()
    if not cards:
        logger.error("カードデータが見つかりません。先に fetch_cards.py を実行してください。")
        return

    if args.series:
        cards = [c for c in cards if c["card_number"].startswith(args.series)]
        logger.info(f"シリーズ {args.series} に絞り込み: {len(cards)}枚")

    logger.info(f"{len(cards)}枚のカード画像をダウンロードします → {CARD_IMAGES_DIR}/")

    downloaded = 0
    cached = 0
    failed = 0
    total_items = 0

    for i, card in enumerate(cards):
        card_number = card["card_number"]
        front_url = card.get("front_url")
        back_url = card.get("back_url")

        sides = [("front", front_url, f"{card_number}.jpg")]
        if not args.front_only:
            sides.append(("back", back_url, f"{card_number}_b.jpg"))

        for side, url, filename in sides:
            if not url:
                continue
            total_items += 1
            filepath = CARD_IMAGES_DIR / filename
            result = download_image(url, filepath, logger)
            if result == "downloaded":
                downloaded += 1
                time.sleep(args.delay)
            elif result == "cached":
                cached += 1
            else:
                failed += 1

        if (i + 1) % 50 == 0:
            logger.info(
                f"  進捗: {i + 1}/{len(cards)} カード "
                f"(DL: {downloaded}, キャッシュ: {cached}, 失敗: {failed})"
            )

    logger.info(
        f"完了: 合計{total_items}件 — DL: {downloaded}, キャッシュ済: {cached}, 失敗: {failed}"
    )


if __name__ == "__main__":
    main()
