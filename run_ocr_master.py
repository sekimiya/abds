#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OCR実行マスタースクリプト
アーセナルベースのカード裏面画像OCR処理を実行する統合スクリプト
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path
import subprocess
from typing import Dict, List, Optional
import re
import openai
from openai import OpenAI

# ログ設定
def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """ログ設定を初期化"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"ocr_master_{timestamp}.log"
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)

def read_api_key(file_path: str) -> str:
    """APIキーを読み込み"""
    with open(file_path, 'r') as f:
        return f.read().strip()

def sanitize_filename(s: str) -> str:
    """ファイル名に使用できない文字を置換"""
    return s.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_').replace(' ', '_')

def extract_structured_data_from_url(image_url: str, api_key: str) -> str:
    """画像URLから構造化データを抽出"""
    client = OpenAI(api_key=api_key)

    prompt = """
この画像は「アーセナルベース」というカードゲームのカードです。
以下のいずれかの形式で構造化されたJSONを出力してください。

カードには「MS（モビルスーツ）」と「PL（パイロット）」の2種類があります。
読み取った情報に応じて、対応する形式を選んでください。

---

【MSカードのJSON構造】
{
  "type": "MS",
  "name": "string",
  "model": "string",
  "cost": integer,
  "category": "string",
  "pilot": "string",
  "stats": {
    "height": "string",
    "weight": "string",
    "mobility": integer,
    "ranged_attack": integer,
    "melee_attack": integer,
    "hp": integer
  },
  "terrain_compatibility": {
    "ground": "string",
    "space": "string",
    "desert": "string",
    "water": "string"
  },
  "weapon": {
    "main": {
      "name": "string",
      "range": integer,
      "type": "string"
    },
    "sub": {
      "name": "string",
      "range": integer,
      "type": "string"
    }
  },
  "ms_ability": {
    "name": "string",
    "cost": integer,
    "description": "string"
  },
  "special_attack": {
    "name": "string",
    "target": "string",
    "range": integer,
    "power": integer,
    "description": "string"
  },
  "link_abilities": [
    {
      "name": "string",
      "condition": "string",
      "effect": "string"
    }
  ],
  "illust": "string"
}

---

【PLカードのJSON構造】
{
  "type": "PL",
  "name": "string",
  "english_name": "string",
  "cost": integer,
  "category": "string",
  "age": integer,
  "height": "string",
  "units": ["string"],
  "pl_skill": {
    "name": "string",
    "trigger": "string",
    "effect": "string"
  },
  "link_abilities": [
    {
      "name": "string",
      "condition": "string",
      "effect": "string"
    }
  ],
  "stats": {
    "mobility": integer,
    "ranged_attack": integer,
    "melee_attack": integer,
    "hp": integer
  },
  "illust": "string"
}

出力は必ずこのJSON形式に従ってください。
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "あなたは画像からカード情報を抽出してJSONに変換するOCRアシスタントです。"},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]}
        ],
        max_tokens=4096,
        temperature=0.0,
    )

    return response.choices[0].message.content

class OCRMaster:
    """OCR実行マスタークラス"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = setup_logging(config.get('log_level', 'INFO'))
        self.all_cards_list_dir = Path("all_cards_list")
        self.ocr_results_dir = Path("ocr_results")
        self.progress_file = Path("ocr_progress.json")
        self.stats_file = Path("ocr_stats.json")
        
        # ディレクトリ作成
        self.ocr_results_dir.mkdir(exist_ok=True)
        
        # APIキー読み込み
        self.api_key = None
        if config.get('api_key'):
            self.api_key = config['api_key']
        elif config.get('api_key_file'):
            self.api_key = read_api_key(config['api_key_file'])
        
    def load_progress(self) -> Dict:
        """進捗状況を読み込み"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"進捗ファイルの読み込みに失敗: {e}")
        return {
            'processed': [],
            'failed': [],
            'skipped': [],
            'start_time': None,
            'last_update': None
        }
    
    def save_progress(self, progress: Dict):
        """進捗状況を保存"""
        progress['last_update'] = datetime.now().isoformat()
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"進捗ファイルの保存に失敗: {e}")
    
    def get_card_files(self) -> List[Path]:
        """処理対象のカードファイル一覧を取得"""
        if not self.all_cards_list_dir.exists():
            raise FileNotFoundError(f"カードデータディレクトリが見つかりません: {self.all_cards_list_dir}")
        
        card_files = list(self.all_cards_list_dir.glob("*.json"))
        self.logger.info(f"処理対象カード数: {len(card_files)}")
        return card_files
    
    def check_already_processed(self, card_file: Path) -> bool:
        """既にOCR処理済みかチェック"""
        try:
            with open(card_file, 'r', encoding='utf-8') as f:
                card_data = json.load(f)
            
            card_number = card_data.get('number', '')
            card_name = card_data.get('name', '')
            series_name = card_data.get('series', '')
            
            # ファイル名に使用できない文字を置換
            safe_number = sanitize_filename(card_number)
            safe_name = sanitize_filename(card_name)
            safe_series = sanitize_filename(series_name)
            
            # 収録パック+カードナンバー+カード名.jsonの形式
            if safe_series:
                ocr_result_file = self.ocr_results_dir / f"{safe_series}_{safe_number}_{safe_name}.json"
            else:
                ocr_result_file = self.ocr_results_dir / f"{safe_number}_{safe_name}.json"
            
            return ocr_result_file.exists()
        except Exception as e:
            self.logger.warning(f"ファイル処理チェックエラー: {card_file.name} - {e}")
            return False
    
    def save_result_to_file(self, card_number: str, card_name: str, result_json: Dict, series_name: str = ""):
        """OCR結果をファイルに保存"""
        # ファイル名に使えない文字をアンダースコアに変換
        safe_number = sanitize_filename(card_number)
        safe_name = sanitize_filename(card_name)
        safe_series = sanitize_filename(series_name)
        
        # 収録パック+カードナンバー+カード名.jsonの形式
        if safe_series:
            filename = f"{safe_series}_{safe_number}_{safe_name}.json"
        else:
            filename = f"{safe_number}_{safe_name}.json"
        
        file_path = self.ocr_results_dir / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(result_json, f, ensure_ascii=False, indent=2)
    
    def run_single_ocr(self, card_file: Path) -> bool:
        """単一カードのOCR処理を実行"""
        try:
            # カードデータを読み込み
            with open(card_file, 'r', encoding='utf-8') as f:
                card_data = json.load(f)
            
            card_number = card_data.get('number', '')
            card_name = card_data.get('name', '')
            series_name = card_data.get('series', '')
            back_image_url = card_data.get('back', {}).get('image_url', '')
            
            # 裏面画像URLがない場合はスキップ
            if not back_image_url:
                self.logger.warning(f"裏面画像なし: {card_number} {card_name}")
                return False
            
            self.logger.info(f"OCR開始: {card_number} {card_name}")
            self.logger.debug(f"URL: {back_image_url}")
            
            # OCR実行
            result = extract_structured_data_from_url(back_image_url, self.api_key)
            
            # コードブロックを除去
            json_str = result
            if "```json" in result:
                json_str = result.split("```json")[1].split("```")[0].strip()
            elif "```" in result:
                json_str = result.split("```")[1].strip()
            
            # JSONとしてパース
            try:
                result_json = json.loads(json_str)
                # 必要なフィールドが存在するか確認
                if 'type' in result_json and 'name' in result_json:
                    self.logger.info(f"OCR成功: {card_number} {card_name}")
                    result_json['card_number'] = card_number
                    result_json['card_name'] = card_name
                    result_json['image_url'] = back_image_url
                else:
                    self.logger.warning(f"不完全なデータ: {card_number} {card_name}")
                    result_json = {
                        "warning": "不完全なデータ", 
                        "card_number": card_number, 
                        "card_name": card_name, 
                        "image_url": back_image_url, 
                        "raw": json_str
                    }
            except Exception as e:
                self.logger.error(f"JSONパース失敗: {card_number} {card_name} {str(e)}")
                result_json = {
                    "error": str(e), 
                    "card_number": card_number, 
                    "card_name": card_name, 
                    "image_url": back_image_url, 
                    "raw": json_str
                }
            
            # 結果を保存
            self.save_result_to_file(card_number, card_name, result_json, series_name)
            return True
                
        except Exception as e:
            self.logger.error(f"OCR実行エラー: {card_file.name} - {e}")
            # エラー結果も保存
            try:
                with open(card_file, 'r', encoding='utf-8') as f:
                    card_data = json.load(f)
                card_number = card_data.get('number', '')
                card_name = card_data.get('name', '')
                series_name = card_data.get('series', '')
                back_image_url = card_data.get('back', {}).get('image_url', '')
                
                error_result = {
                    "error": str(e), 
                    "card_number": card_number, 
                    "card_name": card_name, 
                    "image_url": back_image_url
                }
                self.save_result_to_file(card_number, card_name, error_result, series_name)
            except:
                pass
            return False
    
    def run_batch_ocr(self, batch_size: int = 10):
        """バッチ処理でOCRを実行"""
        if not self.api_key:
            raise ValueError("APIキーが設定されていません")
        
        card_files = self.get_card_files()
        progress = self.load_progress()
        
        if not progress['start_time']:
            progress['start_time'] = datetime.now().isoformat()
        
        total_cards = len(card_files)
        processed_count = len(progress['processed'])
        failed_count = len(progress['failed'])
        skipped_count = len(progress['skipped'])
        
        self.logger.info(f"=== OCR処理開始 ===")
        self.logger.info(f"総カード数: {total_cards}")
        self.logger.info(f"既処理済み: {processed_count}")
        self.logger.info(f"失敗済み: {failed_count}")
        self.logger.info(f"スキップ済み: {skipped_count}")
        self.logger.info(f"残り処理数: {total_cards - processed_count - failed_count - skipped_count}")
        
        # 処理対象を決定
        to_process = []
        for card_file in card_files:
            card_name = card_file.name
            
            if card_name in progress['processed']:
                continue
            elif card_name in progress['failed'] and not self.config.get('retry_failed', False):
                continue
            elif card_name in progress['skipped']:
                continue
            elif not self.config.get('force', False) and self.check_already_processed(card_file):
                progress['skipped'].append(card_name)
                skipped_count += 1
                continue
            
            to_process.append(card_file)
        
        self.logger.info(f"今回処理対象: {len(to_process)}")
        
        # バッチ処理実行
        for i in range(0, len(to_process), batch_size):
            batch = to_process[i:i + batch_size]
            self.logger.info(f"バッチ処理 {i//batch_size + 1}/{(len(to_process) + batch_size - 1)//batch_size}")
            
            for card_file in batch:
                card_name = card_file.name
                
                # 進捗表示
                current = processed_count + failed_count + len(progress['skipped'])
                self.logger.info(f"処理中 ({current + 1}/{total_cards}): {card_name}")
                
                # OCR実行
                success = self.run_single_ocr(card_file)
                
                if success:
                    progress['processed'].append(card_name)
                    processed_count += 1
                else:
                    progress['failed'].append(card_name)
                    failed_count += 1
                
                # 進捗保存
                self.save_progress(progress)
                
                # 遅延
                if self.config.get('delay', 1) > 0:
                    time.sleep(self.config.get('delay', 1))
            
            # バッチ間の遅延
            if self.config.get('batch_delay', 5) > 0:
                self.logger.info(f"バッチ間遅延: {self.config.get('batch_delay', 5)}秒")
                time.sleep(self.config.get('batch_delay', 5))
        
        # 最終統計
        self.save_final_stats(progress, total_cards)
        self.logger.info("=== OCR処理完了 ===")
    
    def save_final_stats(self, progress: Dict, total_cards: int):
        """最終統計を保存"""
        stats = {
            'total_cards': total_cards,
            'processed': len(progress['processed']),
            'failed': len(progress['failed']),
            'skipped': len(progress['skipped']),
            'success_rate': len(progress['processed']) / total_cards * 100 if total_cards > 0 else 0,
            'start_time': progress['start_time'],
            'end_time': datetime.now().isoformat(),
            'processed_files': progress['processed'],
            'failed_files': progress['failed'],
            'skipped_files': progress['skipped']
        }
        
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            self.logger.info(f"統計情報を保存: {self.stats_file}")
        except Exception as e:
            self.logger.error(f"統計情報の保存に失敗: {e}")
    
    def show_status(self):
        """現在の処理状況を表示"""
        progress = self.load_progress()
        card_files = self.get_card_files()
        total_cards = len(card_files)
        
        processed = len(progress['processed'])
        failed = len(progress['failed'])
        skipped = len(progress['skipped'])
        remaining = total_cards - processed - failed - skipped
        
        print(f"\n=== OCR処理状況 ===")
        print(f"総カード数: {total_cards}")
        print(f"処理済み: {processed} ({processed/total_cards*100:.1f}%)")
        print(f"失敗: {failed} ({failed/total_cards*100:.1f}%)")
        print(f"スキップ: {skipped} ({skipped/total_cards*100:.1f}%)")
        print(f"残り: {remaining} ({remaining/total_cards*100:.1f}%)")
        
        if progress['start_time']:
            print(f"開始時刻: {progress['start_time']}")
        if progress['last_update']:
            print(f"最終更新: {progress['last_update']}")
        
        if failed > 0:
            print(f"\n失敗したファイル (最新10件):")
            for failed_file in progress['failed'][-10:]:
                print(f"  - {failed_file}")
    
    def reset_progress(self):
        """進捗をリセット"""
        if self.progress_file.exists():
            self.progress_file.unlink()
            self.logger.info("進捗をリセットしました")
        else:
            self.logger.info("進捗ファイルが存在しません")

def main():
    parser = argparse.ArgumentParser(description="OCR実行マスタースクリプト")
    parser.add_argument("--config", "-c", default="ocr_config.json", help="設定ファイル")
    parser.add_argument("--batch-size", "-b", type=int, default=10, help="バッチサイズ")
    parser.add_argument("--force", "-f", action="store_true", help="既存ファイルを上書き")
    parser.add_argument("--retry-failed", "-r", action="store_true", help="失敗したファイルを再試行")
    parser.add_argument("--status", "-s", action="store_true", help="現在の状況を表示")
    parser.add_argument("--reset", action="store_true", help="進捗をリセット")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--api-key", help="APIキー")
    parser.add_argument("--api-key-file", default="APIkey.txt", help="APIキーファイル")
    
    args = parser.parse_args()
    
    # 設定ファイル読み込み
    config = {
        'log_level': args.log_level,
        'force': args.force,
        'retry_failed': args.retry_failed,
        'delay': 1,
        'batch_delay': 5,
        'max_retries': 3,
        'timeout': 300,
        'batch_size': 10,
        'api_key': args.api_key,
        'api_key_file': args.api_key_file
    }
    
    if Path(args.config).exists():
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                config.update(json.load(f))
        except Exception as e:
            print(f"設定ファイルの読み込みに失敗: {e}")
    
    # OCRマスター初期化
    master = OCRMaster(config)
    
    if args.reset:
        master.reset_progress()
        return
    
    if args.status:
        master.show_status()
        return
    
    # OCR実行
    try:
        master.run_batch_ocr(args.batch_size)
    except KeyboardInterrupt:
        print("\n処理を中断しました")
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 