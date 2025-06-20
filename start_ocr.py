#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OCR処理開始スクリプト
マスタースクリプトを簡単に実行するためのラッパー
"""

import os
import sys
import subprocess
from pathlib import Path

def check_api_key():
    """APIキーの存在確認"""
    api_key_file = Path("APIkey.txt")
    if not api_key_file.exists():
        print("❌ APIキーファイルが見つかりません: APIkey.txt")
        print("APIkey.txtファイルを作成してAPIキーを設定してください")
        return False
    
    # APIキーの内容確認
    try:
        with open(api_key_file, 'r') as f:
            api_key = f.read().strip()
        if not api_key:
            print("❌ APIキーが空です: APIkey.txt")
            return False
        print("✅ APIキーが設定されています")
        return True
    except Exception as e:
        print(f"❌ APIキーファイルの読み込みエラー: {e}")
        return False

def check_card_data():
    """カードデータの存在確認"""
    all_cards_dir = Path("all_cards_list")
    if not all_cards_dir.exists():
        print("❌ カードデータディレクトリが見つかりません: all_cards_list")
        print("先にfetch_cards.pyを実行してカードデータを収集してください")
        return False
    
    card_files = list(all_cards_dir.glob("*.json"))
    if not card_files:
        print("❌ カードデータファイルが見つかりません: all_cards_list")
        print("先にfetch_cards.pyを実行してカードデータを収集してください")
        return False
    
    print(f"✅ カードデータが見つかりました: {len(card_files)}件")
    return True

def check_dependencies():
    """依存関係の確認"""
    try:
        import openai
        print("✅ openaiライブラリが利用可能です")
    except ImportError:
        print("❌ openaiライブラリがインストールされていません")
        print("以下のコマンドでインストールしてください:")
        print("pip install openai")
        return False
    
    return True

def main():
    """メイン処理"""
    print("🚀 OCR処理開始スクリプト")
    print("=" * 50)
    
    # 事前チェック
    print("\n📋 事前チェック中...")
    
    if not check_dependencies():
        sys.exit(1)
    
    if not check_api_key():
        sys.exit(1)
    
    if not check_card_data():
        sys.exit(1)
    
    print("\n✅ すべての事前チェックが完了しました")
    
    # OCR処理の実行
    print("\n🔄 OCR処理を開始します...")
    print("注意: 処理には時間がかかります。中断する場合はCtrl+Cを押してください")
    print("-" * 50)
    
    try:
        # マスタースクリプトを実行
        cmd = [
            sys.executable, "run_ocr_master.py",
            "--batch-size", "5",           # バッチサイズを小さく設定
            "--delay", "2",                # 遅延を少し長めに設定
            "--batch-delay", "10",         # バッチ間遅延を長めに設定
            "--log-level", "INFO"          # ログレベル
        ]
        
        # 実行
        result = subprocess.run(cmd, check=True)
        
        print("\n✅ OCR処理が完了しました！")
        print("結果は ocr_results/ ディレクトリに保存されています")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ OCR処理でエラーが発生しました: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️ 処理が中断されました")
        print("進捗は保存されているので、後で再開できます")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 予期しないエラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 