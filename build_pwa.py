#!/usr/bin/env python3
"""PWA用の静的JSONデータを生成するビルドスクリプト。

app.py の _build_card_index() を呼び出してインメモリキャッシュを構築し、
pwa/data/ 配下にJSON形式で書き出す。
"""

import hashlib
import json
import os
import shutil
import sys
import time

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    print("[build_pwa] カードインデックスを構築中...")

    # app.py から必要なキャッシュ変数と構築関数をインポート
    import app as app_module

    app_module._build_card_index()

    card_index = app_module._card_index_cache
    card_details = app_module._card_detail_cache
    link_index = app_module._link_index_cache

    if not card_index:
        print("[build_pwa] エラー: カードインデックスが空です")
        sys.exit(1)

    print(f"[build_pwa] カード数: {len(card_index)}")
    print(f"[build_pwa] 詳細データ数: {len(card_details)}")
    print(f"[build_pwa] リンクアビリティ数: {len(link_index)}")

    # 出力ディレクトリ作成
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pwa', 'data')
    os.makedirs(out_dir, exist_ok=True)

    # 1. card_index.json — 軽量インデックス配列
    index_path = os.path.join(out_dir, 'card_index.json')
    index_json = json.dumps(card_index, ensure_ascii=False, separators=(',', ':'))
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_json)
    print(f"[build_pwa] card_index.json: {len(index_json) / 1024:.0f} KB")

    # 2. card_details.json — 全カード詳細（rawフィールド除去でサイズ削減）
    cleaned_details = {}
    for num, detail in card_details.items():
        d = dict(detail)
        ocr = d.get('ocr_data')
        if isinstance(ocr, dict):
            ocr = dict(ocr)
            ocr.pop('raw', None)
            d['ocr_data'] = ocr
        cleaned_details[num] = d

    details_path = os.path.join(out_dir, 'card_details.json')
    details_json = json.dumps(cleaned_details, ensure_ascii=False, separators=(',', ':'))
    with open(details_path, 'w', encoding='utf-8') as f:
        f.write(details_json)
    print(f"[build_pwa] card_details.json: {len(details_json) / 1024:.0f} KB")

    # 3. link_index.json — リンクアビリティ索引
    link_path = os.path.join(out_dir, 'link_index.json')
    link_json = json.dumps(link_index, ensure_ascii=False, separators=(',', ':'))
    with open(link_path, 'w', encoding='utf-8') as f:
        f.write(link_json)
    print(f"[build_pwa] link_index.json: {len(link_json) / 1024:.0f} KB")

    # 4. tactics_cards.json — 作戦カードデータのコピー
    tactics_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tactics_cards.json')
    tactics_dst = os.path.join(out_dir, 'tactics_cards.json')
    if os.path.exists(tactics_src):
        shutil.copy2(tactics_src, tactics_dst)
        print(f"[build_pwa] tactics_cards.json: コピー完了")
    else:
        # 空のデフォルトを作成
        with open(tactics_dst, 'w', encoding='utf-8') as f:
            json.dump({"main": [], "sub": []}, f, ensure_ascii=False)
        print(f"[build_pwa] tactics_cards.json: デフォルト作成（元ファイルなし）")

    # 5. version.json — ビルドメタデータ
    index_hash = hashlib.md5(index_json.encode('utf-8')).hexdigest()[:12]
    version_data = {
        "version": time.strftime("%Y%m%d-%H%M%S"),
        "card_count": len(card_index),
        "detail_count": len(cleaned_details),
        "link_count": len(link_index),
        "index_hash": index_hash,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    version_path = os.path.join(out_dir, 'version.json')
    with open(version_path, 'w', encoding='utf-8') as f:
        json.dump(version_data, f, ensure_ascii=False, indent=2)
    print(f"[build_pwa] version.json: v{version_data['version']} hash={index_hash}")

    print(f"\n[build_pwa] 完了! 出力先: {out_dir}")


if __name__ == '__main__':
    main()
