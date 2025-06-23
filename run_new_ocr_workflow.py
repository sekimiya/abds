#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
新しい3段階OCRワークフローを実行するための簡単なスクリプト
"""

import sys
import os
import argparse
from card_ocr import ocr_all_cards_new_workflow

def main():
    """新しいOCRワークフローを実行"""
    
    parser = argparse.ArgumentParser(description='新しい3段階OCRワークフローを実行')
    parser.add_argument('--inputdir', default='all_cards_list', help='入力カードリストディレクトリ (デフォルト: all_cards_list)')
    parser.add_argument('--outputdir', default='ocr_results', help='OCR結果保存ディレクトリ (デフォルト: ocr_results)')
    
    args = parser.parse_args()
    
    # APIキーファイルの確認
    api_key_path = 'APIkey.txt'
    if not os.path.exists(api_key_path):
        print(f"エラー: APIキーファイル '{api_key_path}' が見つかりません")
        print("APIkey.txtファイルを作成して、OpenAI APIキーを設定してください。")
        return 1
    
    # カードリストディレクトリの確認
    if not os.path.exists(args.inputdir):
        print(f"エラー: カードリストディレクトリ '{args.inputdir}' が見つかりません")
        print(f"'{args.inputdir}' ディレクトリを作成して、カードデータを配置してください。")
        return 1
    
    print("=== 新しい3段階OCRワークフローを開始します ===")
    print(f"入力ディレクトリ: {args.inputdir}")
    print(f"出力ディレクトリ: {args.outputdir}")
    print()
    
    try:
        # 新しいワークフローを実行
        ocr_all_cards_new_workflow(api_key_path, args.inputdir, args.outputdir)
        
        print(f"\n=== 処理完了 ===")
        print(f"結果は '{args.outputdir}' ディレクトリに保存されています")
        print()
        print("生成されたファイル:")
        print("- *_basic.json: 基本OCR結果")
        print("- *_sp_raw.json: SP生データ")
        print("- *_sp.json: SPパース済みデータ")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n処理が中断されました。")
        return 1
    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 